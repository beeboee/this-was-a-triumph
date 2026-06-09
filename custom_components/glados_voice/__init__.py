"""GLaDOS Voice Lines custom integration."""

from __future__ import annotations

from datetime import UTC, datetime
import json
import logging
from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant.components import persistent_notification
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import (
    DOMAIN,
    NAME,
    PROGRESS_FILENAME,
    SERVICE_DOWNLOAD,
    SERVICE_REBUILD_INDEX,
    SERVICE_RESET_PROGRESS,
    SERVICE_SAVE_PROGRESS,
    WEB_PATH_CARD,
)
from .downloader import (
    download_all_voice_lines,
    get_storage_dir,
    index_needs_refresh,
    rebuild_index_from_existing_files,
)

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

DOWNLOAD_SCHEMA = vol.Schema(
    {
        vol.Optional("overwrite", default=False): cv.boolean,
        vol.Optional("concurrency", default=4): vol.All(vol.Coerce(int), vol.Range(min=1, max=8)),
    }
)

REBUILD_SCHEMA = vol.Schema({})

SAVE_PROGRESS_SCHEMA = vol.Schema(
    {
        vol.Required("by_game"): dict,
    }
)

RESET_PROGRESS_SCHEMA = vol.Schema({})


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up services for the integration."""
    hass.data.setdefault(DOMAIN, {})
    await _async_register_static_paths(hass)
    _async_register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a config entry."""
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = entry.data
    await _async_register_static_paths(hass)
    _async_register_services(hass)

    if await hass.async_add_executor_job(index_needs_refresh, hass):
        hass.async_create_task(_download_with_notification(hass, overwrite=False, concurrency=4))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return True


async def _async_register_static_paths(hass: HomeAssistant) -> None:
    """Expose the card JS and the downloaded web directory."""
    if hass.data.setdefault(DOMAIN, {}).get("static_paths_registered"):
        return

    card_path = Path(__file__).parent / "frontend" / "glados-voice-card.js"
    storage_path = get_storage_dir(hass)

    await hass.async_add_executor_job(lambda: storage_path.mkdir(parents=True, exist_ok=True))
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(WEB_PATH_CARD, str(card_path), False),
            StaticPathConfig("/glados_voice/files", str(storage_path), False),
        ]
    )
    hass.data[DOMAIN]["static_paths_registered"] = True


def _progress_path(hass: HomeAssistant) -> Path:
    """Return the persistent progress file path."""
    return get_storage_dir(hass) / PROGRESS_FILENAME


def _normalize_progress(data: Any) -> dict[str, Any]:
    """Return a clean progress payload."""
    by_game = data.get("by_game", {}) if isinstance(data, dict) else {}
    clean_by_game: dict[str, list[str]] = {}

    if isinstance(by_game, dict):
        for game, ids in by_game.items():
            if not isinstance(game, str) or not isinstance(ids, list):
                continue
            clean_ids: list[str] = []
            seen: set[str] = set()
            for item_id in ids:
                if not isinstance(item_id, str) or item_id in seen:
                    continue
                seen.add(item_id)
                clean_ids.append(item_id)
            clean_by_game[game] = clean_ids

    return {
        "by_game": clean_by_game,
        "updated_at": datetime.now(UTC).isoformat(),
    }


def _write_progress(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Persist playback progress to the HA config/www storage directory."""
    payload = _normalize_progress(data)
    path = _progress_path(hass)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def _reset_progress(hass: HomeAssistant) -> dict[str, Any]:
    """Clear persisted playback progress."""
    return _write_progress(hass, {"by_game": {}})


def _async_register_services(hass: HomeAssistant) -> None:
    """Register integration services once."""
    if hass.data.setdefault(DOMAIN, {}).get("services_registered"):
        return

    async def handle_download(call: ServiceCall) -> None:
        overwrite = bool(call.data.get("overwrite", False))
        concurrency = int(call.data.get("concurrency", 4))
        await _download_with_notification(hass, overwrite=overwrite, concurrency=concurrency)

    async def handle_rebuild(call: ServiceCall) -> None:
        result = await hass.async_add_executor_job(rebuild_index_from_existing_files, hass)
        persistent_notification.async_create(
            hass,
            f"Loaded existing GLaDOS index with {result.get('line_count', result.get('count', 0))} voice lines.",
            title=NAME,
            notification_id="glados_voice_rebuild_done",
        )

    async def handle_save_progress(call: ServiceCall) -> None:
        await hass.async_add_executor_job(_write_progress, hass, dict(call.data))

    async def handle_reset_progress(call: ServiceCall) -> None:
        await hass.async_add_executor_job(_reset_progress, hass)

    hass.services.async_register(DOMAIN, SERVICE_DOWNLOAD, handle_download, schema=DOWNLOAD_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_REBUILD_INDEX, handle_rebuild, schema=REBUILD_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_SAVE_PROGRESS, handle_save_progress, schema=SAVE_PROGRESS_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_RESET_PROGRESS, handle_reset_progress, schema=RESET_PROGRESS_SCHEMA)
    hass.data[DOMAIN]["services_registered"] = True


async def _download_with_notification(hass: HomeAssistant, *, overwrite: bool, concurrency: int) -> None:
    """Download and notify."""
    persistent_notification.async_create(
        hass,
        "Downloading GLaDOS voice lines from Portal and Portal 2, plus completion songs when available.",
        title=NAME,
        notification_id="glados_voice_download_started",
    )
    try:
        result = await download_all_voice_lines(hass, overwrite=overwrite, concurrency=concurrency)
    except Exception as err:  # noqa: BLE001 - show useful HA notification.
        _LOGGER.exception("GLaDOS voice line download failed")
        persistent_notification.async_create(
            hass,
            f"Download failed: {err}",
            title=NAME,
            notification_id="glados_voice_download_failed",
        )
        return

    failed_count = len(result.get("failed", []))
    songs = result.get("completion_songs", {}) or {}
    song_status = f" Completion songs ready: {', '.join(songs.keys())}." if songs else " Completion songs were not downloaded."
    message = (
        f"Ready: {result.get('line_count', result.get('count', 0))} voice lines indexed. "
        f"Downloaded {result.get('downloaded', 0)}, skipped {result.get('skipped', 0)}."
        f"{song_status}"
    )
    if failed_count:
        message += f" {failed_count} downloads/pages failed; check Home Assistant logs."

    persistent_notification.async_create(
        hass,
        message,
        title=NAME,
        notification_id="glados_voice_download_done",
    )
