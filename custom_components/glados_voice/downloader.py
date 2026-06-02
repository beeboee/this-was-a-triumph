"""Downloader/parser for Portal Wiki GLaDOS voice lines."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from functools import partial
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import hashlib
import io
import json
import logging
from pathlib import Path
import re
from typing import Any
from urllib.parse import unquote, urljoin, urlparse
import zipfile

import aiohttp
from bs4 import BeautifulSoup

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    AUDIO_DIRNAME,
    COMPLETION_SONGS,
    INDEX_FILENAME,
    INDEX_VERSION,
    LOCAL_WEB_DIR,
    QUOTES_FILENAME,
    SOURCE_PAGES,
    USER_AGENT,
)

_LOGGER = logging.getLogger(__name__)

MEDIA_RE = re.compile(r"\.(?:wav|mp3|ogg|flac)(?:$|[?#])", re.IGNORECASE)
WAV_RE = re.compile(r"\.wav(?:$|[?#])", re.IGNORECASE)
ZIP_RE = re.compile(r"\.zip(?:$|[?#])", re.IGNORECASE)
SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9_.-]+")
MEDIA_EXTENSIONS = (".mp3", ".wav", ".ogg", ".flac")


@dataclass(slots=True)
class MediaItem:
    """One downloaded playable item."""

    id: str
    kind: str
    game: str
    quote: str
    chapter: str
    section: str
    source_url: str
    file: str
    audio: str
    title: str = ""


def get_storage_dir(hass: HomeAssistant) -> Path:
    """Return the web-exposed local storage directory."""
    return Path(hass.config.path("www", LOCAL_WEB_DIR))


def get_index_path(hass: HomeAssistant) -> Path:
    """Return the generated index path."""
    return get_storage_dir(hass) / INDEX_FILENAME


def index_needs_refresh(hass: HomeAssistant) -> bool:
    """Return true when the generated index is missing or from an older schema."""
    index_path = get_index_path(hass)
    if not index_path.exists():
        return True

    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return True

    if int(payload.get("index_version", 0)) < INDEX_VERSION:
        return True

    games = {item.get("game") for item in payload.get("items", [])}
    song_games = set((payload.get("completion_songs") or {}).keys())
    expected_games = {str(source["game"]) for source in SOURCE_PAGES}
    return not expected_games.issubset(games) or not expected_games.issubset(song_games)


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
    if "." not in Path(name).name:
        name += ".wav"
    return name


def _safe_filename(name: str, fallback: str) -> str:
    """Build a filesystem-safe filename from a plain name."""
    cleaned = SAFE_FILENAME_RE.sub("_", name).strip("._")
    return cleaned or fallback


def _slug(value: str) -> str:
    """Return a filesystem-ish slug."""
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_") or "item"


def _make_id(kind: str, game: str, source_url: str, quote: str) -> str:
    """Return a short stable id."""
    digest = hashlib.sha1(f"{kind}|{game}|{source_url}|{quote}".encode("utf-8")).hexdigest()[:10]
    base = Path(urlparse(source_url).path).stem.lower()
    base = re.sub(r"[^a-z0-9]+", "_", base).strip("_")
    return f"{base}_{digest}" if base else digest


def _hint_match(name: str, hints: Iterable[str]) -> bool:
    """Return true when a filename/link text appears to match song hints."""
    normalized_name = re.sub(r"[^a-z0-9]+", "", name.lower())
    for hint in hints:
        normalized_hint = re.sub(r"[^a-z0-9]+", "", str(hint).lower())
        if normalized_hint and normalized_hint in normalized_name:
            return True
    return False


def parse_voice_lines(html: str, *, page_url: str, game: str) -> list[dict[str, str]]:
    """Parse a Portal Wiki voice-line page into source entries.

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
            absolute = urljoin(page_url, href)
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
                    "kind": "line",
                    "game": game,
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


def _quotes_text(lines: Iterable[MediaItem], completion_songs: dict[str, MediaItem]) -> str:
    """Return a human-readable quote index."""
    rows = [
        "# GLaDOS Portal voice lines",
        "# Sources:",
        *[f"# - {source['game']}: {source['url']}" for source in SOURCE_PAGES],
        *[f"# - {song['game']} completion song: {song['title']}" for song in COMPLETION_SONGS],
        "# Format: game | chapter > section | local file | transcript/title",
        "",
    ]
    for line in lines:
        heading = " > ".join(part for part in (line.chapter, line.section) if part)
        rows.append(f"{line.game} | {heading} | {line.file} | {line.quote}")

    if completion_songs:
        rows.extend(["", "# Completion songs"])
        for song in completion_songs.values():
            rows.append(f"{song.game} | end credits | {song.file} | {song.title}")

    rows.append("")
    return "\n".join(rows)


async def _fetch_text(session: aiohttp.ClientSession, url: str) -> str:
    async with session.get(url, headers={"User-Agent": USER_AGENT}, timeout=aiohttp.ClientTimeout(total=90)) as response:
        response.raise_for_status()
        return await response.text()


async def _fetch_bytes(session: aiohttp.ClientSession, url: str) -> bytes:
    async with session.get(url, headers={"User-Agent": USER_AGENT}, timeout=aiohttp.ClientTimeout(total=180)) as response:
        response.raise_for_status()
        return await response.read()


def _discover_song_urls(html: str, base_url: str, song: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Find direct media and soundtrack zip links on an HTML page."""
    soup = BeautifulSoup(html, "html.parser")
    direct_urls: list[str] = []
    zip_urls: list[str] = []
    hints = song.get("filename_hints", [])

    for link in soup.find_all("a", href=True):
        href = str(link["href"])
        text = link.get_text(" ", strip=True)
        url = urljoin(base_url, href)
        candidate_name = f"{href} {text}"

        if ZIP_RE.search(href):
            if url not in zip_urls:
                zip_urls.append(url)
            continue

        if MEDIA_RE.search(href) and _hint_match(candidate_name, hints):
            if url not in direct_urls:
                direct_urls.append(url)

    return direct_urls, zip_urls


def _select_song_from_zip(data: bytes, song: dict[str, Any]) -> tuple[str, bytes]:
    """Extract a completion song from a soundtrack zip."""
    hints = song.get("filename_hints", [])
    title = str(song["title"])

    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            filename = info.filename
            lower = filename.lower()
            if not lower.endswith(MEDIA_EXTENSIONS):
                continue
            if _hint_match(filename, hints):
                return filename, archive.read(info)

    raise FileNotFoundError(f"Could not find {title} in soundtrack zip")


def _media_item_for_existing_song(song: dict[str, Any], rel_file: str) -> MediaItem:
    """Return a MediaItem for a previously downloaded song."""
    title = str(song["title"])
    game = str(song["game"])
    source_url = f"local:completion_song:{_slug(game)}:{_slug(title)}"
    return MediaItem(
        id=_make_id("song", game, source_url, title),
        kind="song",
        game=game,
        quote=title,
        title=title,
        chapter="End credits",
        section="",
        source_url=source_url,
        file=rel_file,
        audio=f"/local/{LOCAL_WEB_DIR}/{rel_file}",
    )


async def _download_completion_song(
    hass: HomeAssistant,
    session: aiohttp.ClientSession,
    *,
    storage_dir: Path,
    song: dict[str, Any],
    overwrite: bool,
) -> tuple[MediaItem | None, int, int, list[dict[str, str]]]:
    """Download one completion song when possible."""
    failed: list[dict[str, str]] = []
    title = str(song["title"])
    game = str(song["game"])
    base_name = f"{_slug(game)}_completion_song_{_slug(title)}"

    existing_matches = sorted((storage_dir / AUDIO_DIRNAME).glob(f"{base_name}.*"))
    if existing_matches and not overwrite:
        rel_file = f"{AUDIO_DIRNAME}/{existing_matches[0].name}"
        return _media_item_for_existing_song(song, rel_file), 0, 1, failed

    direct_urls: list[str] = [str(url) for url in song.get("direct_url_candidates", [])]
    zip_urls: list[str] = [str(url) for url in song.get("zip_url_candidates", [])]

    for page_url in song.get("page_urls", []):
        try:
            page_html = await _fetch_text(session, str(page_url))
            discovered_direct, discovered_zips = await hass.async_add_executor_job(
                _discover_song_urls,
                page_html,
                str(page_url),
                song,
            )
            for url in discovered_direct:
                if url not in direct_urls:
                    direct_urls.append(url)
            for url in discovered_zips:
                if url not in zip_urls:
                    zip_urls.append(url)
        except Exception as err:  # noqa: BLE001 - fall back to explicit candidates.
            failed.append({"url": str(page_url), "error": str(err)})

    for direct_url in direct_urls:
        try:
            data = await _fetch_bytes(session, direct_url)
            extension = Path(urlparse(direct_url).path).suffix.lower() or ".mp3"
            rel_file = f"{AUDIO_DIRNAME}/{_safe_filename(base_name + extension, base_name + extension)}"
            await hass.async_add_executor_job(_write_bytes, storage_dir / rel_file, data)
            return (
                MediaItem(
                    id=_make_id("song", game, direct_url, title),
                    kind="song",
                    game=game,
                    quote=title,
                    title=title,
                    chapter="End credits",
                    section="",
                    source_url=direct_url,
                    file=rel_file,
                    audio=f"/local/{LOCAL_WEB_DIR}/{rel_file}",
                ),
                1,
                0,
                failed,
            )
        except Exception as err:  # noqa: BLE001 - try the next source.
            _LOGGER.warning("Failed downloading completion song %s from %s: %s", title, direct_url, err)
            failed.append({"url": direct_url, "error": str(err)})

    for zip_url in zip_urls:
        try:
            archive_data = await _fetch_bytes(session, zip_url)
            source_name, song_data = await hass.async_add_executor_job(_select_song_from_zip, archive_data, song)
            extension = Path(source_name).suffix.lower() or ".mp3"
            rel_file = f"{AUDIO_DIRNAME}/{_safe_filename(base_name + extension, base_name + extension)}"
            await hass.async_add_executor_job(_write_bytes, storage_dir / rel_file, song_data)
            source_url = f"{zip_url}#{source_name}"
            return (
                MediaItem(
                    id=_make_id("song", game, source_url, title),
                    kind="song",
                    game=game,
                    quote=title,
                    title=title,
                    chapter="End credits",
                    section="",
                    source_url=source_url,
                    file=rel_file,
                    audio=f"/local/{LOCAL_WEB_DIR}/{rel_file}",
                ),
                1,
                0,
                failed,
            )
        except Exception as err:  # noqa: BLE001 - try the next source.
            _LOGGER.warning("Failed downloading completion song %s from %s: %s", title, zip_url, err)
            failed.append({"url": zip_url, "error": str(err)})

    return None, 0, 0, failed


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
    source_entries: list[dict[str, str]] = []
    page_failures: list[dict[str, str]] = []

    for source in SOURCE_PAGES:
        try:
            page_html = await _fetch_text(session, str(source["url"]))
            parsed = await hass.async_add_executor_job(
                partial(parse_voice_lines, page_html, page_url=str(source["url"]), game=str(source["game"]))
            )
            source_entries.extend(parsed)
        except Exception as err:  # noqa: BLE001 - keep other sources working.
            _LOGGER.warning("Failed parsing %s: %s", source["url"], err)
            page_failures.append({"url": str(source["url"]), "error": str(err)})

    if not source_entries:
        raise RuntimeError("No GLaDOS .wav links were found on the Portal Wiki voice-line pages")

    semaphore = asyncio.Semaphore(max(1, concurrency))
    used_names: set[str] = set()
    lines: list[MediaItem] = []
    downloaded = 0
    skipped = 0
    failed: list[dict[str, str]] = [*page_failures]

    for i, entry in enumerate(source_entries, start=1):
        game_slug = _slug(entry["game"])
        fallback = f"{game_slug}_glados_{i:04d}.wav"
        filename = f"{game_slug}_{_safe_filename_from_url(entry['source_url'], fallback)}"
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
            MediaItem(
                id=_make_id("line", entry["game"], entry["source_url"], entry["quote"]),
                kind="line",
                game=entry["game"],
                quote=entry["quote"],
                chapter=entry.get("chapter", ""),
                section=entry.get("section", ""),
                source_url=entry["source_url"],
                file=rel_file,
                audio=f"/local/{LOCAL_WEB_DIR}/{rel_file}",
            )
        )

    async def download_one(line: MediaItem) -> None:
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

    completion_songs: dict[str, MediaItem] = {}
    for song in COMPLETION_SONGS:
        song_item, song_downloaded, song_skipped, song_failed = await _download_completion_song(
            hass,
            session,
            storage_dir=storage_dir,
            song=song,
            overwrite=overwrite,
        )
        downloaded += song_downloaded
        skipped += song_skipped
        failed.extend(song_failed)
        if song_item is not None:
            completion_songs[song_item.game] = song_item

    available_lines = [line for line in lines if (storage_dir / line.file).exists()]
    payload: dict[str, Any] = {
        "index_version": INDEX_VERSION,
        "sources": SOURCE_PAGES,
        "source": ", ".join(str(source["url"]) for source in SOURCE_PAGES),
        "generated_at": datetime.now(UTC).isoformat(),
        "count": len(available_lines),
        "line_count": len(available_lines),
        "downloaded": downloaded,
        "skipped": skipped,
        "failed": failed,
        "items": [asdict(line) for line in available_lines],
        "completion_songs": {game: asdict(song) for game, song in completion_songs.items()},
        "end_song": asdict(completion_songs["Portal 2"]) if "Portal 2" in completion_songs else None,
    }

    await hass.async_add_executor_job(_write_json, index_path, payload)
    await hass.async_add_executor_job(_write_text, quotes_path, _quotes_text(available_lines, completion_songs))

    return payload


def rebuild_index_from_existing_files(hass: HomeAssistant) -> dict[str, Any]:
    """Lightweight helper for future expansion; currently returns existing index if present."""
    index_path = get_index_path(hass)
    if not index_path.exists():
        raise FileNotFoundError(str(index_path))
    return json.loads(index_path.read_text(encoding="utf-8"))
