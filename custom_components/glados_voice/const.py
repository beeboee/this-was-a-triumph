"""Constants for the GLaDOS Voice Lines integration."""

DOMAIN = "glados_voice"
NAME = "GLaDOS Voice Lines"
INDEX_VERSION = 3

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

COMPLETION_SONGS = [
    {
        "title": "Still Alive",
        "game": "Portal",
        "page_urls": [
            "https://theportalwiki.com/wiki/Still_Alive",
            "https://theportalwiki.com/wiki/Portal_soundtrack",
        ],
        "zip_url_candidates": [],
        "direct_url_candidates": [],
        "filename_hints": ["still alive", "still_alive", "stillalive"],
    },
    {
        "title": "Want You Gone",
        "game": "Portal 2",
        "page_urls": [
            "https://www.thinkwithportals.com/music.php",
            "https://theportalwiki.com/wiki/Want_You_Gone",
            "https://theportalwiki.com/wiki/Portal_2_soundtrack",
        ],
        "zip_url_candidates": [
            "https://media.steampowered.com/apps/portal2/soundtrack/Portal2-OST-Volume3.zip",
            "https://cdn.cloudflare.steamstatic.com/apps/portal2/soundtrack/Portal2-OST-Volume3.zip",
        ],
        "direct_url_candidates": [],
        "filename_hints": ["want you gone", "want_you_gone", "wantyougone"],
    },
]

USER_AGENT = "HomeAssistant-GLaDOS-Voice-Lines/0.3 (+https://www.home-assistant.io/)"

SERVICE_DOWNLOAD = "download"
SERVICE_REBUILD_INDEX = "rebuild_index"
SERVICE_SAVE_PROGRESS = "save_progress"
SERVICE_RESET_PROGRESS = "reset_progress"

WEB_PATH_CARD = "/glados_voice/card.js"
LOCAL_WEB_DIR = "glados_voice"
INDEX_FILENAME = "index.json"
PROGRESS_FILENAME = "progress.json"
QUOTES_FILENAME = "quotes.txt"
AUDIO_DIRNAME = "audio"
