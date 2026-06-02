# GLaDOS Voice Lines for Home Assistant

A HACS-compatible custom integration that downloads GLaDOS Portal 2 voice lines from Portal Wiki, saves the `.wav` files locally, builds a quote index, and provides a compact Lovelace card that plays a random line in the browser.

This repo does **not** include Portal, Portal 2, Valve, GLaDOS audio, or quote data. Your Home Assistant instance fetches the publicly linked files from Portal Wiki after you install and configure the integration.

## What it does

- Downloads GLaDOS Portal 2 `.wav` files from Portal Wiki.
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

- The card:
  - chooses a random line when loaded,
  - tries to play it immediately,
  - has a left-side shuffle button,
  - shows the full quote on the right,
  - replays the current line when the quote is tapped.

## Important browser limitation

Browsers often block audio autoplay until the page has been tapped/clicked. The card still picks a random line on reload. If autoplay is blocked, tap the quote once and future playback in that session should behave normally.

This plays through the device running the Home Assistant UI, not through a Home Assistant media player entity.

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

After setup, the first download starts automatically if `/config/www/glados_voice/index.json` does not exist.

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
```

The visual layout is intentionally close to what you described: left `1/7` shuffle button, right `6/7` full quote. Tapping the quote replays the current line.

## Service

You can force a fresh download from **Developer Tools → Services**:

```yaml
service: glados_voice.download
data:
  overwrite: false
  concurrency: 4
```

Set `overwrite: true` to re-download existing `.wav` files.

## Files exposed to the browser

Because files are saved under `/config/www`, Home Assistant exposes them under `/local`:

```text
/config/www/glados_voice/index.json  ->  /local/glados_voice/index.json
/config/www/glados_voice/audio/...   ->  /local/glados_voice/audio/...
```

## Notes

- Keep download concurrency low. The default is `4`.
- If Portal Wiki changes its page structure, the parser may need adjustment.
- This is a local browser audio card. It does not call `media_player.play_media`.
