# GetLiveStreamMessageMember

## これはなに？

配信しているYoutubeのチャット内の発言のあったメンバー一覧を取得するスクリプトです。

## 使い方

### 動作環境
Python 3.7以降なら動くはず
開発は Python 3.10.7を用いています。

### 事前準備
Youtube Data API V3を使えるようにしておきます。
取得したOAuth 2.0 のJSONは client_secrets.json としてフォルダの中に配置します。

必要なライブラリの取得を行います。
```
pip install -r requirements.txt
```

youtubechannnel.ini.sampleを参考にyoutubechannnel.iniファイルを作成します
上記のiniファイルには取得対象のYoutubeのchannerl_idを入力します。

該当のチャンネルが配信中の際に
```
python ./getStream.py
```
と実行することで発言のあったメンバーを取得します。
`result/日付.txt` というファイルにメンバーの一覧を格納します。

配信が終了するとプログラムは終了します。
