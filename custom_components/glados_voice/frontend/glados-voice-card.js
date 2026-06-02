class GladosVoiceCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
    this._items = [];
    this._current = null;
    this._loaded = false;
    this._loading = false;
    this._error = "";
    this._blocked = false;
    this._audio = null;
  }

  setConfig(config) {
    this._config = {
      index_url: "/local/glados_voice/index.json",
      autoplay: true,
      show_context: true,
      ...config,
    };
    this._loadIndex();
  }

  set hass(hass) {
    this._hass = hass;
  }

  connectedCallback() {
    this._render();
    if (!this._loaded && !this._loading) {
      this._loadIndex();
    }
  }

  getCardSize() {
    return 1;
  }

  async _loadIndex() {
    if (this._loading) return;
    this._loading = true;
    this._error = "";
    this._render();

    const cacheBust = this._config.cache_bust === false ? "" : `${this._config.index_url.includes("?") ? "&" : "?"}_=${Date.now()}`;
    try {
      const response = await fetch(`${this._config.index_url}${cacheBust}`, { cache: "no-store" });
      if (!response.ok) throw new Error(`Index fetch failed: ${response.status}`);
      const data = await response.json();
      this._items = Array.isArray(data.items) ? data.items : [];
      if (!this._items.length) throw new Error("No voice lines were found in the index.");
      this._loaded = true;
      this._pickRandom(false);
      this._render();
      if (this._config.autoplay !== false) {
        window.setTimeout(() => this._playCurrent(), 150);
      }
    } catch (err) {
      this._error = err?.message || String(err);
      this._render();
    } finally {
      this._loading = false;
    }
  }

  _pickRandom(play = true) {
    if (!this._items.length) return;
    let next = this._items[Math.floor(Math.random() * this._items.length)];
    if (this._items.length > 1 && this._current) {
      let guard = 0;
      while (next.id === this._current.id && guard < 10) {
        next = this._items[Math.floor(Math.random() * this._items.length)];
        guard += 1;
      }
    }
    this._current = next;
    this._blocked = false;
    this._render();
    if (play) this._playCurrent();
  }

  _stopAudio() {
    if (!this._audio) return;
    try {
      this._audio.pause();
      this._audio.currentTime = 0;
    } catch (_) {
      // Ignore browser audio cleanup errors.
    }
  }

  async _playCurrent() {
    if (!this._current?.audio) return;
    this._stopAudio();
    const src = this._current.audio;
    this._audio = new Audio(src);
    this._audio.preload = "auto";
    this._audio.volume = Number.isFinite(Number(this._config.volume)) ? Number(this._config.volume) : 1;
    try {
      await this._audio.play();
      this._blocked = false;
    } catch (_) {
      this._blocked = true;
    }
    this._render();
  }

  _contextText() {
    if (!this._current || this._config.show_context === false) return "";
    const bits = [this._current.chapter, this._current.section].filter(Boolean);
    return bits.join(" > ");
  }

  _render() {
    const quote = this._current?.quote || (this._loading ? "Loading GLaDOS voice lines…" : "No voice line selected.");
    const context = this._contextText();
    const blocked = this._blocked ? `<div class="hint">Browser blocked autoplay. Tap the quote.</div>` : "";
    const error = this._error ? `<div class="error">${this._escape(this._error)}</div>` : "";

    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
        }
        ha-card {
          overflow: hidden;
        }
        .wrap {
          display: grid;
          grid-template-columns: minmax(44px, 1fr) minmax(0, 6fr);
          align-items: stretch;
          min-height: 56px;
        }
        button {
          border: 0;
          border-right: 1px solid var(--divider-color, rgba(255,255,255,.12));
          background: color-mix(in srgb, var(--card-background-color) 88%, var(--primary-color));
          color: var(--primary-text-color);
          font: inherit;
          font-size: 22px;
          cursor: pointer;
          min-width: 44px;
        }
        button:hover {
          background: color-mix(in srgb, var(--card-background-color) 74%, var(--primary-color));
        }
        .quote {
          padding: 10px 12px;
          cursor: pointer;
          user-select: none;
          line-height: 1.25;
        }
        .quoteText {
          font-size: 0.96rem;
          white-space: normal;
          overflow-wrap: anywhere;
        }
        .context, .hint, .error {
          margin-top: 3px;
          font-size: 0.72rem;
          opacity: 0.72;
        }
        .error {
          color: var(--error-color, #db4437);
          opacity: 1;
        }
        .hint {
          color: var(--warning-color, #f4b400);
          opacity: 1;
        }
      </style>
      <ha-card>
        <div class="wrap">
          <button title="Shuffle GLaDOS line">🔀</button>
          <div class="quote" title="Replay this voice line">
            <div class="quoteText">${this._escape(quote)}</div>
            ${context ? `<div class="context">${this._escape(context)}</div>` : ""}
            ${blocked}
            ${error}
          </div>
        </div>
      </ha-card>
    `;

    this.shadowRoot.querySelector("button")?.addEventListener("click", (event) => {
      event.stopPropagation();
      this._pickRandom(true);
    });
    this.shadowRoot.querySelector(".quote")?.addEventListener("click", () => this._playCurrent());
  }

  _escape(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }
}

customElements.define("glados-voice-card", GladosVoiceCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "glados-voice-card",
  name: "GLaDOS Voice Line",
  description: "Random local Portal 2 GLaDOS quote player.",
});
