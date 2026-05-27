# ADR 001: ライブチャットメッセージ取得を `liveChatMessages.list` から `liveChatMessages.streamList` へ移行

- ステータス: 採用
- 決定日: 2026-05-26

## 議論の背景

ユーザー（配信者）から「コメントが流れてから `notify_wankome()` が動くまでが遅い」というフィードバックがあった。

現状の実装（[getStream.py:172-218](../../getStream.py)）は、以下の構造でライブチャットを取得している。

- `googleapiclient` 経由の REST API `liveChatMessages.list` をポーリング
- 1回の取得後、固定で `time.sleep(10)` 秒待機
- レスポンスに含まれる `pollingIntervalMillis`（YouTube が推奨する次回ポーリング間隔）は未使用
- 配信終了は `liveStreamingDetails.actualEndTime` の有無で判定

この構造では、メッセージ到達から検知までの遅延が最悪 `sleep_time + APIレスポンス時間` となり、構造的に縮められない。`sleep_time` を縮める対応は可能だが、`pollingIntervalMillis` を無視して短縮すれば `rateLimitExceeded (403)` を踏む可能性がある。

また、長時間配信（数時間以上）では OAuth トークンの有効期限切れがループ中に発生し得るが、現状コードは while ループ中にトークンリフレッシュを行っていない。

### 要件

- コメント着信から `notify_wankome()` 呼び出しまでの遅延を構造的に短縮する
- `rateLimitExceeded` を踏まずに低遅延を達成する
- 長時間配信中のトークン期限切れに対応する
- 配信終了検知は引き続き安定して動作する

### 制約

- YouTube Data API v3 が提供するエンドポイントの範囲内で実装する
- OAuth 2.0 ベースの既存認証フロー（`token.pickle`）と整合する

## 選択肢と結論

| 番号 | 選択肢 | 結論 |
|------|--------|------|
| 1 | `sleep_time` を短縮する（現状維持＋微調整） | 不採用 |
| 2 | レスポンスの `pollingIntervalMillis` を使ってポーリング間隔を最適化 | 不採用（中間案として却下） |
| 3 | `liveChatMessages.streamList`（gRPC server-streaming）へ全面移行 | **採用** |

**結論**: 選択肢 3 を採用し、一括移行で実装する。あわせてストリーム実行中の OAuth トークンリフレッシュ処理を追加する。

## 各選択肢の比較表

| 観点 | 選択肢1: sleep短縮 | 選択肢2: pollingIntervalMillis 活用 | 選択肢3: streamList 移行 |
|------|--------------------|--------------------------------------|---------------------------|
| 遅延 | 数秒〜10秒（短縮幅は限定的） | 数秒（YouTube推奨値依存） | 低遅延（サーバー側から push） |
| `rateLimitExceeded` リスク | 高（手動短縮の場合） | 低 | 低 |
| 実装コスト | 極小 | 小 | 中（gRPC 導入が必要） |
| 依存ライブラリ追加 | なし | なし | `grpcio`, `grpcio-tools` |
| 認証実装の変更 | 不要 | 不要 | 必要（gRPC metadata で Bearer 渡し） |
| 配信終了検知の変更 | 不要 | 不要 | 必要（接続切断＋`videos.list` で確認） |
| トークンリフレッシュとの相性 | 影響小 | 影響小 | ストリーム再接続契機で扱える |
| 公式推奨度 | — | 推奨 | 「最も効率的」と公式が明記 |
| 構造的限界 | あり（ポーリング上限） | あり（ポーリング上限） | なし |

## 結論を導いた重要な観点

1. **構造的な遅延解消**: 選択肢 1・2 はいずれもポーリング方式のままであり、最小遅延に下限がある。streamList は server-streaming で新着メッセージを push するため、構造的に低遅延を達成できる。公式ドキュメントも「This is the most efficient way to consume live chat messages」と明記している。

2. **API クォータ・レート制限の観点でも有利**: 「pushes new messages to your client as soon as they are available, rather than requiring you to poll for updates」と公式が説明しているとおり、ポーリング起因のクォータ浪費を回避できる。

3. **一括移行の合理性**: 中間案（選択肢 2）は本質的解決ではなくつなぎであり、二度実装する手戻りが発生する。ユーザーから「一括移行で」との明確な意向もある。

4. **トークンリフレッシュ対応の必要性**: streamList の long-lived connection ではトークン期限切れが顕在化しやすいため、本移行と同時にループ中のリフレッシュ処理を入れるのが自然。

## 帰結

### ポジティブな影響

- コメント検知 → `notify_wankome()` 呼び出しの遅延が大幅に短縮される見込み
- `rateLimitExceeded` を踏みづらくなる
- 長時間配信中のトークン期限切れによる停止が解消される

### ネガティブな影響・トレードオフ

- 依存ライブラリ（`grpcio`, `grpcio-tools`）が増える
- 公式 `.proto` ファイルから `stream_list_pb2.py` / `stream_list_pb2_grpc.py` を生成する手順がビルドに必要になる
- gRPC エラーコード `FAILED_PRECONDITION` では `LIVE_CHAT_DISABLED` と `LIVE_CHAT_ENDED` が区別できない（公式ドキュメント明記の制約）
- 配信終了検知ロジックの作り直しが必要
  - 一次判定: ストリーム切断・`offlineAt` の検出
  - 確認: 既存の `videos.list` ＋ `actualEndTime` チェックを併用するハイブリッド方式

### 将来の見直し条件

- YouTube が streamList を廃止/非推奨化した場合
- gRPC 経由でクォータや認証関連の運用上の問題が発生した場合
- 公式が WebSocket など別方式の低遅延 API を提供した場合

## 各選択肢の説明

### 選択肢 1: `sleep_time` を短縮する

現状の `time.sleep(10)` を数秒に縮める対応。コード変更は最小。

- 採用しなかった理由:
  - `pollingIntervalMillis` を無視して短縮すれば `rateLimitExceeded` のリスクが上がる
  - 仮にレート制限内で短縮できても、ポーリング方式である以上、遅延は最小でも数秒残る
  - 構造的解決にならない

### 選択肢 2: `pollingIntervalMillis` を活用したポーリング最適化

レスポンスに含まれる `pollingIntervalMillis` を `time.sleep()` の引数に渡すことで、YouTube 推奨間隔ぴったりでポーリングする方式。

- 採用しなかった理由:
  - 改善はするが、依然としてポーリング方式であり遅延の構造的下限が残る
  - 本質的な解決ではなく、streamList 移行までの「つなぎ」にしかならない
  - ユーザーから一括移行の方針が示されている

### 選択肢 3: `liveChatMessages.streamList` への全面移行（採用）

gRPC ベースの server-streaming エンドポイントに切り替え、サーバー側からの push でメッセージを受け取る方式。公式 Python デモ ([Streaming Live Chat](https://developers.google.com/youtube/v3/live/streaming-live-chat)) をベースに実装する。

- 採用理由:
  - 公式が「最も効率的」と明記する低遅延方式
  - ポーリング起因のクォータ消費・レート制限リスクを構造的に解消
  - 切断時は `nextPageToken` で再開可能なため、トークンリフレッシュ後の再接続フローと相性が良い

- 実装方針（概要）:
  - 依存追加: `grpcio`, `grpcio-tools` を `pyproject.toml` に追加
  - `stream_list.proto` から Python スタブを生成
  - 認証: 既存 `token.pickle` から `creds.token` を取り出し、gRPC metadata `("authorization", "Bearer " + token)` として渡す
  - トークンリフレッシュ: ストリーム実行中も期限を監視し、期限が近づいたら `creds.refresh(Request())` を実行 → 新トークンで再接続
  - 配信終了検知: ストリーム切断 or `offlineAt` 検出を一次トリガとし、最終確認として `videos.list` の `actualEndTime` をチェックするハイブリッド方式
  - メンバーシップ判定・`notify_wankome()` 呼び出しなど、メッセージ処理ロジックの本体は現状のまま移植

## 参考資料

- [LiveChatMessages: streamList (公式)](https://developers.google.com/youtube/v3/live/docs/liveChatMessages/streamList)
- [Streaming Live Chat: Python デモ (公式)](https://developers.google.com/youtube/v3/live/streaming-live-chat)
- [LiveChatMessages: list (公式)](https://developers.google.com/youtube/v3/live/docs/liveChatMessages/list)
