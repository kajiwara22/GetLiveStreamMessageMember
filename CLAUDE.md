# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## プロジェクト概要

YouTube Liveの配信チャットを監視し、発言したユーザー一覧を取得するPythonスクリプト。メンバーシップ加入者が特定のメッセージ (`w` を含む) を投稿したら、外部の「わんこめ」HTTP APIへ通知も送る。

## 実行コマンド

依存関係のセットアップ（uvまたはpipのどちらかを使用、`uv.lock` / `requirements.txt` の双方が存在する）:

```bash
pip install -r requirements.txt
# あるいは
uv sync
```

スクリプト実行（対象チャンネルがLive配信中の時に走らせる）:

```bash
python ./getStream.py
```

事前準備として以下が必要:
- `client_secrets.json`: Google CloudのOAuth 2.0クライアント認証情報。初回実行時にブラウザでのOAuth同意フローが走り、`token.pickle` が生成される
- `youtubechannel.ini`: `youtubechannel.ini.sample` を参考に作成。`[SETTING] channel_id` と `[WANKOME] url` を記載

## アーキテクチャ

二つのモジュールから構成されるシンプルな構造:

- [getStream.py](getStream.py): メインロジック。OAuth認証→対象チャンネルの配信検索→ライブチャットID取得→ポーリングループ（`youtube.liveChatMessages().list()` を `slp_time`=10秒間隔で実行）。配信終了 (`actualEndTime` が立つ) でループを抜け、最後にトークンをリフレッシュして終了する
- [wankomeNotifier.py](wankomeNotifier.py): メンバーシップメンバーの発言検知時に外部HTTPエンドポイントへPOSTする通知用モジュール

### 配信対象の判定ロジック

[getStream.py](getStream.py) の起動時に `youtube.search().list(eventType="upcoming")` で配信予定を取得し、各動画の `liveStreamingDetails.scheduledStartTime` を見て **本日と同じ日付** かつ **`actualEndTime` が未設定** のものを取得対象とする ([getStream.py:147-150](getStream.py#L147-L150))。`activeLiveChatId` が取れなければ「まだ配信開始していない」と判断して終了する。

### メンバーシップ通知の流れ

各メッセージで `authorDetails.isChatSponsor` が `True` かつ `snippet.displayMessage` に `w`（大文字小文字問わず）が含まれる場合に `notify_wankome()` を呼ぶ ([getStream.py:196-204](getStream.py#L196-L204))。通知URLは `youtubechannel.ini` の `[WANKOME] url` から読む。

### 出力

- `result/YYYY-MM-DD.txt`: 発言ユーザー一覧。ユーザーが増えるたびに **上書き** 保存される（追記ではない）
- `log/YYYY-MM-DD.log`: DEBUGレベル以上のログ（標準出力にはINFO以上）

## アーキテクチャ決定記録

[docs/adr/](docs/adr/) にADR (Architecture Decision Records) を蓄積する運用。新規決定時はフォーマット（議論の背景／選択肢／比較表／帰結／各選択肢の詳細）に従い、`docs/adr/README.md` の一覧に追加すること。

## Python環境

`.python-version` は 3.10.7、`.tool-versions` は 3.10.14 を指す。`pyproject.toml` の `requires-python` は `>=3.10`。実体の依存リストは `requirements.txt` 側にあり、`pyproject.toml` の `dependencies` は空のため、依存追加の際は `requirements.txt` を更新する必要がある点に注意。
