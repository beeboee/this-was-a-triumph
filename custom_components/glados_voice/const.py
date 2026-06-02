"""Constants for the GLaDOS Voice Lines integration."""

DOMAIN = "glados_voice"
NAME = "GLaDOS Voice Lines"
INDEX_VERSION = 2

SOURCE_PAGES = [
    {
        "game": "Portal",
        "url": "https://theportalwiki.com/wiki/GLaDOS_voice_lines_(Portal)",
    },
    {
        "game": "Portal 2",
        "url": "https://theportalwiki.com/wiki/GLaDOS_voice_lines_(Portal_2)",
    },
]

END_SONG = {
    "title": "Want You Gone",
    "game": "Portal 2",
    "page_url": "https://www.thinkwithportals.com/music.php",
    "zip_url_candidates": [
        "https://media.steampowered.com/apps/portal2/soundtrack/Portal2-OST-Volume3.zip",
        "https://cdn.cloudflare.steamstatic.com/apps/portal2/soundtrack/Portal2-OST-Volume3.zip",
    ],
    "filename_hints": ["want you gone", "want_you_gone", "wantyougone"],
}

USER_AGENT = "HomeAssistant-GLaDOS-Voice-Lines/0.2 (+https://www.home-assistant.io/)"

SERVICE_DOWNLOAD = "download"
SERVICE_REBUILD_INDEX = "rebuild_index"

WEB_PATH_CARD = "/glados_voice/card.js"
LOCAL_WEB_DIR = "glados_voice"
INDEX_FILENAME = "index.json"
QUOTES_FILENAME = "quotes.txt"
AUDIO_DIRNAME = "audio"
