import configparser
import urllib.request
from logging import getLogger

logger = getLogger(__name__)

_config = configparser.ConfigParser()
_config.optionxform = str
_config.read("youtubechannel.ini")

_base_url = _config["WANKOME"]["base_url"]

# ロールごとの ini セクション名。{ role: セクション名 } の形式で保持
_ROLE_SECTION_NAMES = {
    "sponsor": "WANKOME_KEYWORDS_SPONSOR",
    "moderator": "WANKOME_KEYWORDS_MODERATOR",
}

# { role: { wordparty_id: [キーワード, ...] } } の形式で保持
_keyword_maps: dict[str, dict[str, list[str]]] = {}
for role, section_name in _ROLE_SECTION_NAMES.items():
    keyword_map: dict[str, list[str]] = {}
    if _config.has_section(section_name):
        for wordparty_id, keywords_raw in _config[section_name].items():
            keyword_map[wordparty_id] = [k.strip() for k in keywords_raw.split(",")]
    _keyword_maps[role] = keyword_map


def _post(url: str) -> None:
    try:
        req = urllib.request.Request(url, method="POST")
        with urllib.request.urlopen(req, timeout=5) as resp:
            logger.info(f"わんこめ通知成功: status={resp.status} url={url}")
    except Exception:
        logger.exception(f"わんこめ通知に失敗しました: url={url}")


def notify_wankome_for_message(display_message: str, role: str) -> None:
    """メッセージ内容を見て、ロールに対応するキーワードと一致したwordparty IDへPOSTする。

    Args:
        display_message: チャットの表示メッセージ
        role: "sponsor" または "moderator"
    """
    keyword_map = _keyword_maps.get(role, {})
    for wordparty_id, keywords in keyword_map.items():
        if any(kw in display_message for kw in keywords):
            url = f"{_base_url}/{wordparty_id}"
            _post(url)
