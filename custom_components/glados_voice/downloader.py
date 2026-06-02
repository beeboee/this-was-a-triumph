"""Downloader/parser for Portal Wiki GLaDOS voice lines."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import hashlib
import json
import logging
from pathlib import Path
import re
from typing import Any
from urllib.parse import unquote, urljoin, urlparse

import aiohttp
from bs4 import BeautifulSoup

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    AUDIO_DIRNAME,
    INDEX_FILENAME,
    LOCAL_WEB_DIR,
    QUOTES_FILENAME,
    SOURCE_URL,
    USER_AGENT,
)

_LOGGER = logging.getLogger(__name__)

WAV_RE = re.compile(r"\.wav(?:$|[?#])", re.IGNORECASE)
SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9_.-]+")


@dataclass(slots=True)
class VoiceLine:
    """One downloaded voice line entry."""

    id: str
    quote: str
    chapter: str
    section: str
    source_url: str
    file: str
    audio: str


def get_storage_dir(hass: HomeAssistant) -> Path:
    """Return the web-exposed local storage directory."""
    return Path(hass.config.path("www", LOCAL_WEB_DIR))


def get_index_path(hass: HomeAssistant) -> Path:
    """Return the generated index path."""
    return get_storage_dir(hass) / INDEX_FILENAME


def _clean_heading(tag: Any) -> str:
    """Return a readable heading without MediaWiki edit cruft."""
    copy = BeautifulSoup(str(tag), "html.parser")
    for edit in copy.select(".mw-editsection"):
        edit.decompose()
    headline = copy.select_one(".mw-headline")
    text = headline.get_text(" ", strip=True) if headline else copy.get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text).strip()


def _safe_filename_from_url(url: str, fallback: str) -> str:
    """Build a filesystem-safe filename from a URL."""
    path_name = unquote(Path(urlparse(url).path).name)
    name = path_name or fallback
    name = SAFE_FILENAME_RE.sub("_", name).strip("._")
    if not name.lower().endswith(".wav"):
        name += ".wav"
    return name


def _make_id(source_url: str, quote: str) -> str:
    """Return a short stable id."""
    digest = hashlib.sha1(f"{source_url}|{quote}".encode("utf-8")).hexdigest()[:10]
    base = Path(urlparse(source_url).path).stem.lower()
    base = re.sub(r"[^a-z0-9]+", "_", base).strip("_")
    return f"{base}_{digest}" if base else digest


def parse_voice_lines(html: str) -> list[dict[str, str]]:
    """Parse the Portal Wiki page into source entries.

    We intentionally do not ship Valve/Portal audio or quotes with the integration.
    This parser discovers the lines from the user's own Home Assistant instance.
    """
    soup = BeautifulSoup(html, "html.parser")
    content = soup.select_one("#mw-content-text") or soup

    chapter = ""
    section = ""
    entries: list[dict[str, str]] = []
    seen_urls: set[str] = set()

    for node in content.find_all(["h2", "h3", "li"]):
        if node.name == "h2":
            chapter = _clean_heading(node)
            section = ""
            if chapter.lower() == "notes":
                break
            continue

        if node.name == "h3":
            section = _clean_heading(node)
            continue

        wav_urls: list[str] = []
        for link in node.find_all("a", href=True):
            href = str(link.get("href", ""))
            if not WAV_RE.search(href):
                continue
            absolute = urljoin(SOURCE_URL, href)
            filename = Path(urlparse(absolute).path).name.lower()
            # Avoid notes/chimes and keep this integration scoped to GLaDOS.
            if not filename.startswith("glados"):
                continue
            if absolute not in wav_urls:
                wav_urls.append(absolute)

        if not wav_urls:
            continue

        text = node.get_text(" ", strip=True)
        text = re.sub(r"\s+", " ", text).strip()
        quote = text.split("|", 1)[0].strip()
        quote = quote.strip("\u201c\u201d\"").strip()
        if not quote:
            continue

        for wav_url in wav_urls:
            if wav_url in seen_urls:
                continue
            seen_urls.add(wav_url)
            entries.append(
                {
                    "quote": quote,
                    "chapter": chapter,
                    "section": section,
                    "source_url": wav_url,
                }
            )

    return entries


def _write_bytes(path: Path, data: bytes) -> None:
    """Write bytes to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _write_text(path: Path, text: str) -> None:
    """Write text to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(path: Path, data: dict[str, Any]) -> None:
    """Write JSON to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _quotes_text(lines: Iterable[VoiceLine]) -> str:
    """Return a human-readable quote index."""
    rows = [
        "# GLaDOS Portal 2 voice lines",
        f"# Source: {SOURCE_URL}",
        "# Format: chapter > section | local file | quote",
        "",
    ]
    for line in lines:
        heading = " > ".join(part for part in (line.chapter, line.section) if part)
        rows.append(f"{heading} | {line.file} | {line.quote}")
    rows.append("")
    return "\n".join(rows)


async def _fetch_text(session: aiohttp.ClientSession, url: str) -> str:
    async with session.get(url, headers={"User-Agent": USER_AGENT}, timeout=aiohttp.ClientTimeout(total=90)) as response:
        response.raise_for_status()
        return await response.text()


async def _fetch_bytes(session: aiohttp.ClientSession, url: str) -> bytes:
    async with session.get(url, headers={"User-Agent": USER_AGENT}, timeout=aiohttp.ClientTimeout(total=120)) as response:
        response.raise_for_status()
        return await response.read()


async def download_all_voice_lines(
    hass: HomeAssistant,
    *,
    overwrite: bool = False,
    concurrency: int = 4,
) -> dict[str, Any]:
    """Download all voice lines and build local indexes."""
    storage_dir = get_storage_dir(hass)
    audio_dir = storage_dir / AUDIO_DIRNAME
    index_path = storage_dir / INDEX_FILENAME
    quotes_path = storage_dir / QUOTES_FILENAME

    await hass.async_add_executor_job(lambda: storage_dir.mkdir(parents=True, exist_ok=True))
    await hass.async_add_executor_job(lambda: audio_dir.mkdir(parents=True, exist_ok=True))

    session = async_get_clientsession(hass)
    page_html = await _fetch_text(session, SOURCE_URL)
    source_entries = await hass.async_add_executor_job(parse_voice_lines, page_html)

    if not source_entries:
        raise RuntimeError("No GLaDOS .wav links were found on the Portal Wiki page")

    semaphore = asyncio.Semaphore(max(1, concurrency))
    used_names: set[str] = set()
    lines: list[VoiceLine] = []
    downloaded = 0
    skipped = 0
    failed: list[dict[str, str]] = []

    for i, entry in enumerate(source_entries, start=1):
        fallback = f"glados_{i:04d}.wav"
        filename = _safe_filename_from_url(entry["source_url"], fallback)
        original = filename
        suffix = 2
        while filename.lower() in used_names:
            stem = Path(original).stem
            ext = Path(original).suffix or ".wav"
            filename = f"{stem}_{suffix}{ext}"
            suffix += 1
        used_names.add(filename.lower())

        rel_file = f"{AUDIO_DIRNAME}/{filename}"
        lines.append(
            VoiceLine(
                id=_make_id(entry["source_url"], entry["quote"]),
                quote=entry["quote"],
                chapter=entry.get("chapter", ""),
                section=entry.get("section", ""),
                source_url=entry["source_url"],
                file=rel_file,
                audio=f"/local/{LOCAL_WEB_DIR}/{rel_file}",
            )
        )

    async def download_one(line: VoiceLine) -> None:
        nonlocal downloaded, skipped
        target = storage_dir / line.file
        if target.exists() and not overwrite:
            skipped += 1
            return
        async with semaphore:
            try:
                data = await _fetch_bytes(session, line.source_url)
                await hass.async_add_executor_job(_write_bytes, target, data)
                downloaded += 1
            except Exception as err:  # noqa: BLE001 - report every failed asset, keep going.
                _LOGGER.warning("Failed downloading %s: %s", line.source_url, err)
                failed.append({"url": line.source_url, "error": str(err)})

    await asyncio.gather(*(download_one(line) for line in lines))

    available_lines = [line for line in lines if (storage_dir / line.file).exists()]
    payload: dict[str, Any] = {
        "source": SOURCE_URL,
        "generated_at": datetime.now(UTC).isoformat(),
        "count": len(available_lines),
        "downloaded": downloaded,
        "skipped": skipped,
        "failed": failed,
        "items": [asdict(line) for line in available_lines],
    }

    await hass.async_add_executor_job(_write_json, index_path, payload)
    await hass.async_add_executor_job(_write_text, quotes_path, _quotes_text(available_lines))

    return payload


def rebuild_index_from_existing_files(hass: HomeAssistant) -> dict[str, Any]:
    """Lightweight helper for future expansion; currently returns existing index if present."""
    index_path = get_index_path(hass)
    if not index_path.exists():
        raise FileNotFoundError(str(index_path))
    return json.loads(index_path.read_text(encoding="utf-8"))
