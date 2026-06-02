# GLaDOS Voice Lines for Home Assistant

A HACS-compatible custom integration that downloads GLaDOS voice lines from **Portal** and **Portal 2**, saves the audio locally, builds a quote index, and provides a compact Lovelace card that plays random lines in the browser.

This repo does **not** include Portal, Portal 2, Valve, GLaDOS audio, lyrics, or quote data. Your Home Assistant instance fetches the publicly linked files after you install and configure the integration.

## What it does

- Downloads GLaDOS `.wav` voice lines from Portal Wiki for:
  - Portal
  - Portal 2
- Tries to download the Portal 2 ending song, **Want You Gone**, from Valve's freely released Portal 2 soundtrack ZIP.
- Saves audio to:

  ```text
  /config/www/glados_voice/audio/
  ```

- Saves a machine-readable index to:

  ```text
  /config/www/glados_voice/index.json
  ```

- Saves a human-readable quote list to:

  ```text
  /config/www/glados_voice/quotes.txt
  ```

- Registers a custom Lovelace card at:

  ```text
  /glados_voice/card.js
  ```

## Card behavior

- Reloading the dashboard picks a random normal GLaDOS line from the combined Portal + Portal 2 pool.
- The shuffle button also picks a random normal line from the combined pool.
- Random really means random: it can repeat the same line immediately.
- Portal 1 and Portal 2 lines are mixed together. It does not play through one game before the other.
- The card tracks which normal voice lines this browser has successfully started playing.
- After every normal voice line has been heard at least once, the card plays **Want You Gone**, then resets that browser's heard-line tracker.
- Tapping the transcript:
  - pauses if the current line/song is still playing,
  - resumes if it is paused,
  - replays if it already finished.
- This plays through the device running the Home Assistant UI, not through a Home Assistant `media_player` entity.

## Important browser limitation

Browsers often block audio autoplay until the page has been tapped/clicked. The card still picks a random line on reload. If autoplay is blocked, tap the transcript once and future playback in that browser session should behave normally.

## Install through HACS as a custom repository

1. Use this repo URL: `https://github.com/beeboee/this-was-a-triumph`.
2. In Home Assistant, open **HACS**.
3. Open the three-dot menu and choose **Custom repositories**.
4. Add your repo URL.
5. Category: **Integration**.
6. Install **GLaDOS Voice Lines**.
7. Restart Home Assistant.
8. Go to **Settings → Devices & services → Add integration**.
9. Search for **GLaDOS Voice Lines** and add it.

After setup, the first download starts automatically if `/config/www/glados_voice/index.json` does not exist or if the existing index is from the older Portal-2-only version.

## Manual install

Copy this folder:

```text
custom_components/glados_voice
```

to:

```text
/config/custom_components/glados_voice
```

Restart Home Assistant, then add the integration from **Settings → Devices & services**.

## Lovelace resource

Add this dashboard resource manually:

```text
URL: /glados_voice/card.js
Resource type: JavaScript module
```

In most current HA installs:

```text
Settings → Dashboards → three-dot menu → Resources → Add resource
```

## Card YAML

```yaml
type: custom:glados-voice-card
index_url: /local/glados_voice/index.json
autoplay: true
show_context: true
show_progress: true
```

The visual layout stays close to the original request: left `1/7` shuffle button, right `6/7` transcript. Tapping the transcript pauses/resumes/replays.

Optional settings:

```yaml
volume: 0.8
show_progress: false
progress_storage_key: glados_voice_heard_v2
cache_bust: true
```

## Service

You can force a fresh download from **Developer Tools → Services**:

```yaml
service: glados_voice.download
data:
  overwrite: false
  concurrency: 4
```

Set `overwrite: true` to re-download existing audio files.

## Files exposed to the browser

Because files are saved under `/config/www`, Home Assistant exposes them under `/local`:

```text
/config/www/glados_voice/index.json  ->  /local/glados_voice/index.json
/config/www/glados_voice/audio/...   ->  /local/glados_voice/audio/...
```

## Notes

- Keep download concurrency low. The default is `4`.
- If Portal Wiki or Valve's soundtrack page changes its page structure, the parser/downloader may need adjustment.
- The completion tracker is browser-local. Your desktop, phone, and tablet each track heard lines separately.
- This is a local browser audio card. It does not call `media_player.play_media`.
