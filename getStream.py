import pickle
import os
import sys
import time
import configparser
from datetime import date, datetime, timedelta, timezone
from logging import getLogger, FileHandler, DEBUG, Formatter, StreamHandler, INFO

import grpc
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

# 生成済み gRPC スタブを import するため、proto ディレクトリを sys.path に追加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "proto"))
import stream_list_pb2  # noqa: E402
import stream_list_pb2_grpc  # noqa: E402

from wankomeNotifier import notify_wankome_for_message  # noqa: E402

logger = getLogger(__name__)
log_file_path = f"log/{date.today().strftime('%Y-%m-%d')}.log"
file_handler = FileHandler(filename=log_file_path, encoding="utf-8")
logger.setLevel(DEBUG)
file_handler.setLevel(DEBUG)
file_handler.setFormatter(Formatter("%(asctime)s %(levelname)8s %(message)s"))
logger.addHandler(file_handler)
stream_handler = StreamHandler(sys.stdout)
stream_handler.setLevel(INFO)
logger.addHandler(stream_handler)
config = configparser.ConfigParser()
config.read("youtubechannel.ini")

CLIENT_SECRETS_FILE = "client_secrets.json"
SCOPES = ["https://www.googleapis.com/auth/youtube"]
API_SERVICE_NAME = "youtube"
API_VERSION = "v3"
YOUTUBE_GRPC_TARGET = "dns:///youtube.googleapis.com:443"

# トークンの期限切れ何分前にリフレッシュするか
TOKEN_REFRESH_MARGIN = timedelta(minutes=5)
# ストリーム終了後、配信が継続しているときに再接続する間隔（秒）
RECONNECT_BACKOFF_SEC = 5

JST = timezone(timedelta(hours=+9), "JST")


def conv_jst(d: datetime):
    if d.tzinfo is None or d.tzinfo.utcoffset is None:
        return (d.replace(tzinfo=timezone.utc)).astimezone(JST)


def load_or_refresh_credentials():
    """token.pickle から credentials を読み込み、必要ならリフレッシュする。"""
    creds = None
    if os.path.exists("token.pickle"):
        with open("token.pickle", "rb") as token:
            creds = pickle.load(token)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            old_expiry_time = creds.expiry
            logger.debug(
                f"tokenのリフレッシュが必要です。 有効期限: {conv_jst(old_expiry_time)}"
            )
            creds.refresh(Request())
            logger.debug("リフレッシュを実施しました。")
            logger.debug(
                f"更新前 {conv_jst(old_expiry_time)} -> 更新後: {conv_jst(creds.expiry)}"
            )
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                CLIENT_SECRETS_FILE, SCOPES
            )
            creds = flow.run_local_server(port=0)
        with open("token.pickle", "wb") as token:
            pickle.dump(creds, token)
    return creds


def ensure_fresh_token(creds):
    """有効期限が近づいていればリフレッシュして token.pickle を更新する。"""
    if creds.expiry is None:
        return creds
    # creds.expiry は naive な UTC 時刻
    remaining = creds.expiry - datetime.utcnow()
    if remaining <= TOKEN_REFRESH_MARGIN:
        logger.info(
            f"アクセストークンの期限が近いためリフレッシュします。残り: {remaining}"
        )
        creds.refresh(Request())
        with open("token.pickle", "wb") as token:
            pickle.dump(creds, token)
        logger.info(f"リフレッシュ完了。新しい有効期限: {conv_jst(creds.expiry)}")
    return creds


def build_youtube_client(creds):
    return build(API_SERVICE_NAME, API_VERSION, credentials=creds)


def youtube_search(youtube, channel_id: str) -> list:
    search_response = (
        youtube.search()
        .list(
            channelId=channel_id,
            part="id",
            order="date",
            eventType="upcoming",
            type="video",
        )
        .execute()
    )
    return search_response.get("items", [])


def youtube_video_live_stream_details(youtube, video_id: str) -> list:
    video_response = (
        youtube.videos().list(id=video_id, part="liveStreamingDetails").execute()
    )
    return video_response.get("items", [])


def is_stream_ended(youtube, video_id: str) -> bool:
    """videos.list で actualEndTime をチェックして配信終了を判定する。"""
    details = youtube_video_live_stream_details(youtube, video_id)
    if not details:
        # 取れない場合は配信終了とみなす
        logger.warning("videos.list が空のため配信終了とみなします。")
        return True
    live_streaming_details = details[0].get("liveStreamingDetails", {})
    return live_streaming_details.get("actualEndTime") is not None


def find_active_live_chat(youtube, channel_id: str):
    """配信中の video_id と activeLiveChatId を取得する。見つからなければ (None, None)。"""
    logger.info("配信対象日比較に用いる日付")
    today_obj = datetime.today().astimezone(timezone.utc)
    logger.info(today_obj)

    for item in youtube_search(youtube, channel_id):
        video_id = item["id"].get("videoId")
        if video_id is None:
            continue
        details = youtube_video_live_stream_details(youtube, video_id)
        if len(details) == 0:
            continue
        for detail in details:
            live_chat_detail = detail.get("liveStreamingDetails")
            if not live_chat_detail:
                logger.warn("liveStreamingDetailsが見つかりませんでした")
                logger.warn(detail)
                continue
            logger.info(f"配信情報はこちら video_id: {video_id}")
            logger.info(live_chat_detail)
            scheduled_start_time = datetime.strptime(
                live_chat_detail["scheduledStartTime"], "%Y-%m-%dT%H:%M:%S%z"
            )
            logger.info(
                f"{today_obj.day} == {scheduled_start_time.day} : "
                f"{today_obj.day == scheduled_start_time.day}"
            )
            if (
                today_obj.day == scheduled_start_time.day
                and "actualEndTime" not in live_chat_detail.keys()
                and "activeLiveChatId" in live_chat_detail.keys()
            ):
                logger.info("取得対象を見つけました！")
                return video_id, live_chat_detail["activeLiveChatId"]
    return None, None


def save_user_list(user_list: dict) -> None:
    with open(
        f"result/{date.today().strftime('%Y-%m-%d')}.txt",
        mode="w",
        encoding="UTF-8",
    ) as f:
        for listener in user_list:
            f.write(f"{listener}\n")


def process_message(message, user_list: dict) -> None:
    """1 件のメッセージを処理し、ユーザーリスト更新・わんこめ通知を行う。"""
    author = message.author_details
    display_name = author.display_name if author.HasField("display_name") else None

    old_len = len(user_list)
    if display_name:
        user_list[display_name] = True

    # logger.debug(message)
    snippet = message.snippet
    display_message = snippet.display_message if snippet.HasField("display_message") else ""
    logger.debug(display_message)
    if author.HasField("is_chat_sponsor") and author.is_chat_sponsor:
        try:
            notify_wankome_for_message(display_message)
        except Exception:
            logger.exception("メンバー通知関数の呼び出しに失敗しました。")

    if len(user_list) > old_len:
        logger.debug(f"発言ユーザーが増えました。{old_len} > {len(user_list)} ")
        logger.debug(f"発言ユーザーは下記の通り {user_list.keys()}")
        save_user_list(user_list)


def stream_live_chat(creds, chat_id: str, user_list: dict, page_token: str | None):
    """liveChatMessages.streamList でメッセージを受信する。

    Returns:
        tuple[str | None, bool, bool]:
            - 最後に受信した next_page_token（再接続に使用）
            - 配信終了の疑い（True なら呼び出し側で actualEndTime を確認）
            - チャット側で明確に終了と判明したか（True なら videos.list 確認をスキップして終了）
    """
    metadata = (("authorization", "Bearer " + creds.token),)
    ssl_creds = grpc.ssl_channel_credentials()
    last_token = page_token
    suspect_end = False
    confirmed_end = False

    with grpc.secure_channel(YOUTUBE_GRPC_TARGET, ssl_creds) as channel:
        stub = stream_list_pb2_grpc.V3DataLiveChatMessageServiceStub(channel)
        request = stream_list_pb2.LiveChatMessageListRequest(
            part=["snippet", "authorDetails"],
            live_chat_id=chat_id,
            page_token=last_token,
        )
        #logger.info(
        #    f"streamList を開始します。page_token={'(あり)' if last_token else '(なし)'}"
        #)
        try:
            for response in stub.StreamList(request, metadata=metadata):
                if response.HasField("next_page_token"):
                    last_token = response.next_page_token
                for message in response.items:
                    snippet = message.snippet
                    if snippet.HasField("type") and (
                        snippet.type
                        == stream_list_pb2.LiveChatMessageSnippet.TypeWrapper.CHAT_ENDED_EVENT
                    ):
                        logger.info("CHAT_ENDED_EVENT を受信しました。配信終了とみなします。")
                        confirmed_end = True
                        break
                    process_message(message, user_list)
                if response.HasField("offline_at"):
                    logger.info(
                        f"offline_at を受信しました: {response.offline_at}。配信終了の可能性。"
                    )
                    suspect_end = True
                    break
                if confirmed_end:
                    break
        except grpc.RpcError as e:
            code = e.code() if hasattr(e, "code") else None
            details = e.details() if hasattr(e, "details") else ""
            logger.warning(f"gRPC エラーを受信しました: code={code} details={details}")
            if code == grpc.StatusCode.FAILED_PRECONDITION:
                # LIVE_CHAT_DISABLED / LIVE_CHAT_ENDED は区別不可（公式仕様）
                logger.info(
                    "FAILED_PRECONDITION のためチャットは終了または無効と判断します。"
                )
                confirmed_end = True
            elif code == grpc.StatusCode.UNAUTHENTICATED:
                # 認証エラーは呼び出し側でトークンリフレッシュ後に再接続
                logger.info("UNAUTHENTICATED のためトークンリフレッシュを試みます。")
                suspect_end = False
            else:
                suspect_end = True

    return last_token, suspect_end, confirmed_end


def main() -> int:
    try:
        creds = load_or_refresh_credentials()
    except Exception:
        logger.exception("トークンの更新または取得に失敗しました。処理を中断します。")
        return 1

    youtube = build_youtube_client(creds)
    channel_id = config["SETTING"]["channel_id"]

    video_id, chat_id = find_active_live_chat(youtube, channel_id)
    if not chat_id:
        logger.error(
            "チャットIDが取れませんでした。まだLive配信は開始してない模様です。処理を終了します。"
        )
        return 0

    logger.info("チャットIDがとれました。")
    logger.debug(chat_id)

    user_list: dict = {}
    page_token: str | None = None

    while True:
        try:
            creds = ensure_fresh_token(creds)
        except Exception:
            logger.exception("トークンのリフレッシュに失敗しました。処理を中断します。")
            return 1

        last_token, suspect_end, confirmed_end = stream_live_chat(
            creds, chat_id, user_list, page_token
        )
        if last_token:
            page_token = last_token

        if confirmed_end:
            logger.info("配信終了が確定しました。ループを抜けます。")
            break

        # ストリームが切れたので videos.list で actualEndTime を確認
        try:
            ended = is_stream_ended(youtube, video_id)
        except Exception:
            logger.exception("videos.list での終了確認に失敗しました。再接続します。")
            ended = False

        if ended:
            logger.info("actualEndTime を検出したためループを抜けます。")
            break

        if suspect_end:
            logger.info(
                "配信終了の疑いがありましたが actualEndTime 未検出。再接続します。"
            )
        # else:
            # logger.info("ストリームが切断されたため再接続します。")
        time.sleep(RECONNECT_BACKOFF_SEC)

    try:
        logger.debug("次回の配信向けにトークンの更新処理を行います。")
        load_or_refresh_credentials()
    except Exception:
        logger.exception("トークンの更新または取得に失敗しました。")
    finally:
        logger.info("配信が終わったようなので、処理を終了します。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
