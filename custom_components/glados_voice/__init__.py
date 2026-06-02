"""GLaDOS Voice Lines custom integration."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant.components import persistent_notification
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN, NAME, SERVICE_DOWNLOAD, SERVICE_REBUILD_INDEX, WEB_PATH_CARD
from .downloader import download_all_voice_lines, get_index_path, get_storage_dir, rebuild_index_from_existing_files

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

DOWNLOAD_SCHEMA = vol.Schema(
    {
        vol.Optional("overwrite", default=False): cv.boolean,
        vol.Optional("concurrency", default=4): vol.All(vol.Coerce(int), vol.Range(min=1, max=8)),
    }
)

REBUILD_SCHEMA = vol.Schema({})


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

    index_path = get_index_path(hass)
    if not index_path.exists():
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
            f"Loaded existing GLaDOS index with {result.get('count', 0)} voice lines.",
            title=NAME,
            notification_id="glados_voice_rebuild_done",
        )

    hass.services.async_register(DOMAIN, SERVICE_DOWNLOAD, handle_download, schema=DOWNLOAD_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_REBUILD_INDEX, handle_rebuild, schema=REBUILD_SCHEMA)
    hass.data[DOMAIN]["services_registered"] = True


async def _download_with_notification(hass: HomeAssistant, *, overwrite: bool, concurrency: int) -> None:
    """Download and notify."""
    persistent_notification.async_create(
        hass,
        "Downloading GLaDOS Portal 2 voice lines from Portal Wiki. This can take a bit on the first run.",
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
    message = (
        f"Ready: {result.get('count', 0)} voice lines indexed. "
        f"Downloaded {result.get('downloaded', 0)}, skipped {result.get('skipped', 0)}."
    )
    if failed_count:
        message += f" {failed_count} files failed; check Home Assistant logs."

    persistent_notification.async_create(
        hass,
        message,
        title=NAME,
        notification_id="glados_voice_download_done",
    )
