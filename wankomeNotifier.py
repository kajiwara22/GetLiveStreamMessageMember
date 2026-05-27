import configparser
import urllib.request
from logging import getLogger

logger = getLogger(__name__)

_config = configparser.ConfigParser()
_config.read("youtubechannel.ini")

_base_url = _config["WANKOME"]["base_url"]

# { wordparty_id: [キーワード, ...] } の形式で保持
_keyword_map: dict[str, list[str]] = {}
if _config.has_section("WANKOME_KEYWORDS"):
    for wordparty_id, keywords_raw in _config["WANKOME_KEYWORDS"].items():
        _keyword_map[wordparty_id] = [k.strip() for k in keywords_raw.split(",")]


def _post(url: str) -> None:
    try:
        req = urllib.request.Request(url, method="POST")
        with urllib.request.urlopen(req, timeout=5) as resp:
            logger.info(f"わんこめ通知成功: status={resp.status} url={url}")
    except Exception:
        logger.exception(f"わんこめ通知に失敗しました: url={url}")


def notify_wankome_for_message(display_message: str) -> None:
    """メッセージ内容を見て、一致したキーワードのwordparty IDへPOSTする。"""
    for wordparty_id, keywords in _keyword_map.items():
        if any(kw in display_message for kw in keywords):
            url = f"{_base_url}/{wordparty_id}"
            _post(url)
