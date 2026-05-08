import configparser
import urllib.request
from logging import getLogger

logger = getLogger(__name__)

_config = configparser.ConfigParser()
_config.read("youtubechannel.ini")


def notify_wankome() -> None:
    """わんこめ HTTP API へ POST リクエストを送信する。"""
    url = _config["WANKOME"]["url"]
    try:
        req = urllib.request.Request(url, method="POST")
        with urllib.request.urlopen(req, timeout=5) as resp:
            logger.info(f"わんこめ通知成功: status={resp.status} url={url}")
    except Exception:
        logger.exception(f"わんこめ通知に失敗しました: url={url}")
