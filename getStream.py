import pickle
from googleapiclient.discovery import build
from datetime import date
import os
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import sys
import time
from logging import getLogger, FileHandler, DEBUG, Formatter, StreamHandler, INFO
from datetime import datetime, timedelta, timezone
import configparser

logger = getLogger(__name__)
log_file_path = f"log/{date.today().strftime('%Y-%m-%d')}.log"
file_handler = FileHandler(filename=log_file_path, encoding='utf-8')  # handler2はファイル出力
logger.setLevel(DEBUG)
file_handler.setLevel(DEBUG)  # handler2はLevel.WARN以上
file_handler.setFormatter(Formatter("%(asctime)s %(levelname)8s %(message)s"))
logger.addHandler(file_handler)
stream_handler = StreamHandler(sys.stdout)
stream_handler.setLevel(INFO)
logger.addHandler(stream_handler)
config = configparser.ConfigParser()
config.read("youtubechannel.ini")

# The CLIENT_SECRETS_FILE variable specifies the name of a file that contains
# the OAuth 2.0 information for this application, including its client_id and
# client_secret.
CLIENT_SECRETS_FILE = "client_secrets.json"

# This access scope grants read-only access to the authenticated user's Drive
# account.
SCOPES = ["https://www.googleapis.com/auth/youtube"]
API_SERVICE_NAME = "youtube"
API_VERSION = "v3"
youtube = None
slp_time = 10  # sec

JST = timezone(timedelta(hours=+9), 'JST')


def conv_jst(d:datetime):
    if d.tzinfo is None or d.tzinfo.utcoffset is None:
        return (d.replace(tzinfo=timezone.utc)).astimezone(JST)


def get_authenticated_service():
    creds = None
    # The file token.pickle stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    if os.path.exists("token.pickle"):
        with open("token.pickle", "rb") as token:
            creds = pickle.load(token)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            old_expiry_time = creds.expiry
            logger.debug(f"tokenのリフレッシュが必要です。 有効期限: {conv_jst(old_expiry_time)}")
            creds.refresh(Request())
            logger.debug("リフレッシュを実施しました。")
            logger.debug(f"更新前 {conv_jst(old_expiry_time)} -> 更新後: {conv_jst(creds.expiry)}")
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                CLIENT_SECRETS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open("token.pickle", "wb") as token:
            pickle.dump(creds, token)

    return build(API_SERVICE_NAME, API_VERSION, credentials=creds)


def youtube_search(channel_id: str, max_results: int = 10) -> list:
    # Search: list で channel_id から検索する
    search_response = (youtube.search().list(channelId=channel_id,
                                             part="id",
                                             order="date", eventType="upcoming", type="video").execute())
    return search_response.get("items", [])


def youtube_video_live_stream_details(video_id: str) -> list:
    # Videos: list で video_id から検索する
    video_response = (youtube.videos().list(
        id=video_id, part="liveStreamingDetails").execute())
    return video_response.get("items", [])


if __name__ == "__main__":
    try:
        youtube = get_authenticated_service()
    except:
        logger.exception("トークンの更新または取得に失敗しました。処理を中断します。")
        sys.exit(1)
    # youtube = youtube = build('youtube', 'v3', developerKey=API_KEY)
    live_chat_detail = None
    chat_id = None
    channel_id = config["SETTING"]["channel_id"]
    logger.info("配信対象日比較に用いる日付")
    today_obj = datetime.today().astimezone(timezone.utc)   
    logger.info(today_obj)
    for item in youtube_search(channel_id):
        video_id = item["id"].get("videoId")
        if video_id is None:
            logger.error("まだLive配信は開始してない模様です。処理を終了します。")
            sys.exit()
        details = youtube_video_live_stream_details(video_id)
        if len(details) == 0:
            logger.error("まだLive配信は開始してない模様です。処理を終了します。")
            sys.exit()
        for detail in details:
            live_chat_detail = detail.get("liveStreamingDetails")
            if live_chat_detail:
                logger.info(f"配信情報はこちら video_id: {video_id}")
                logger.info(live_chat_detail)
                # {'scheduledStartTime': '2023-10-20T12:30:46Z'
                scheduledStartTime = datetime.strptime(live_chat_detail["scheduledStartTime"], '%Y-%m-%dT%H:%M:%S%z')
                logger.info("日付比較は以下のdayで実施")
                logger.info(today_obj)
                logger.info(scheduledStartTime)
                if scheduledStartTime.day == today_obj.day and "actualEndTime" not in live_chat_detail.keys():
                    break
            else:
                logger.warn("liveStreamingDetailsが見つかりませんでした")
                logger.warn(detail)
    if "activeLiveChatId" in live_chat_detail.keys():
        chat_id = live_chat_detail["activeLiveChatId"]
        logger.info("チャットIDがとれました。")
        logger.debug(chat_id)
    else:
        logger.error("チャットIDが取れませんでした。まだLive配信は開始してない模様です。処理を終了します。")
        sys.exit()
    token = None
    user_list = []

    while youtube_video_live_stream_details(
            video_id)[0]['liveStreamingDetails'].get("actualEndTime") is None:
        logger.debug("メッセージを取得します")
        logger.debug(f"token={token}")
        request = youtube.liveChatMessages().list(liveChatId=chat_id,
                                                  part="authorDetails",
                                                  maxResults=2000,
                                                  pageToken=token)
        response = request.execute()
        old_len = len(user_list)
        for message in response["items"]:
            logger.debug(message)
            if (message.get("authorDetails")):
                usr = message["authorDetails"]["displayName"]
                if usr not in user_list:
                    user_list.append(usr)
        current_len = len(user_list)
        token = response["nextPageToken"]
        if current_len > old_len:
            logger.debug(f"発言ユーザーが増えました。{old_len} > {current_len} ")
            logger.debug("発言ユーザーは下記の通り ")
            logger.debug(f"{user_list}")
            with open(f"result/{date.today().strftime('%Y-%m-%d')}.txt",
                      mode="w", encoding="UTF-8") as f:
                for listener in user_list:
                    f.write(f"{listener}\n")
        time.sleep(slp_time)
    try:
        logger.debug("次回の配信向けにトークンの更新処理を行います。")
        get_authenticated_service()
    except:
        logger.exception("トークンの更新または取得に失敗しました。")
    finally:
        logger.info("配信が終わったようなので、処理を終了します。")
