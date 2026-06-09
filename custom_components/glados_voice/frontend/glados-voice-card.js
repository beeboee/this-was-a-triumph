class GladosVoiceCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
    this._items = [];
    this._lineItems = [];
    this._linesByGame = new Map();
    this._completionSongs = {};
    this._current = null;
    this._loaded = false;
    this._loading = false;
    this._error = "";
    this._blocked = false;
    this._audio = null;
    this._isPlaying = false;
    this._isFinished = false;
    this._heardByGame = {};
    this._queuedCompletionGame = null;
    this._completionSongPlaying = false;
    this._storageKey = "glados_voice_heard_v3";
  }

  setConfig(config) {
    this._config = {
      index_url: "/local/glados_voice/index.json",
      progress_url: "/local/glados_voice/progress.json",
      autoplay: true,
      show_context: true,
      show_progress: true,
      persist_progress: true,
      progress_storage_key: "glados_voice_heard_v3",
      ...config,
    };
    this._storageKey = this._config.progress_storage_key || "glados_voice_heard_v3";
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
      this._lineItems = this._items.filter((item) => (item.kind || "line") === "line");
      this._completionSongs = data.completion_songs || {};
      if (!Object.keys(this._completionSongs).length && data.end_song) {
        this._completionSongs = { [data.end_song.game || "Portal 2"]: data.end_song };
      }
      if (!this._lineItems.length) throw new Error("No voice lines were found in the index.");
      this._buildLineGroups();
      await this._loadProgress();
      this._loaded = true;
      this._render();
      if (this._config.autoplay !== false) {
        window.setTimeout(() => this._pickRandom(true), 150);
      } else {
        this._pickRandom(false);
      }
    } catch (err) {
      this._error = err?.message || String(err);
      this._render();
    } finally {
      this._loading = false;
    }
  }

  _buildLineGroups() {
    this._linesByGame = new Map();
    for (const item of this._lineItems) {
      const game = item.game || "Unknown";
      if (!this._linesByGame.has(game)) this._linesByGame.set(game, []);
      this._linesByGame.get(game).push(item);
    }
  }

  _emptyProgress() {
    const progress = {};
    for (const game of this._linesByGame.keys()) {
      progress[game] = new Set();
    }
    return progress;
  }

  _validIdsByGame() {
    const validByGame = {};
    for (const [game, lines] of this._linesByGame.entries()) {
      validByGame[game] = new Set(lines.map((item) => item.id));
    }
    return validByGame;
  }

  _mergeProgressPayload(target, payload) {
    const validByGame = this._validIdsByGame();
    const byGame = payload?.by_game && typeof payload.by_game === "object" ? payload.by_game : {};
    for (const [game, ids] of Object.entries(byGame)) {
      if (!validByGame[game] || !Array.isArray(ids)) continue;
      if (!target[game]) target[game] = new Set();
      for (const id of ids) {
        if (validByGame[game].has(id)) target[game].add(id);
      }
    }
  }

  _loadLocalProgressPayload() {
    try {
      const raw = window.localStorage.getItem(this._storageKey);
      const parsed = raw ? JSON.parse(raw) : {};
      if (parsed.by_game && typeof parsed.by_game === "object") return parsed;

      if (Array.isArray(parsed.ids)) {
        // Graceful migration from v2 combined progress.
        const validByGame = this._validIdsByGame();
        const byGame = {};
        for (const game of Object.keys(validByGame)) byGame[game] = [];
        for (const id of parsed.ids) {
          for (const [game, validIds] of Object.entries(validByGame)) {
            if (validIds.has(id)) byGame[game].push(id);
          }
        }
        return { by_game: byGame };
      }
    } catch (_) {
      // Ignore corrupt/unavailable localStorage and start clean.
    }
    return { by_game: {} };
  }

  async _loadServerProgressPayload() {
    if (this._config.persist_progress === false || !this._config.progress_url) return { by_game: {} };
    const cacheBust = this._config.cache_bust === false ? "" : `${this._config.progress_url.includes("?") ? "&" : "?"}_=${Date.now()}`;
    try {
      const response = await fetch(`${this._config.progress_url}${cacheBust}`, { cache: "no-store" });
      if (!response.ok) return { by_game: {} };
      return await response.json();
    } catch (_) {
      return { by_game: {} };
    }
  }

  async _loadProgress() {
    const nextProgress = this._emptyProgress();
    this._mergeProgressPayload(nextProgress, this._loadLocalProgressPayload());
    this._mergeProgressPayload(nextProgress, await this._loadServerProgressPayload());
    this._heardByGame = nextProgress;
    this._saveProgress();
  }

  _progressPayload() {
    const byGame = {};
    for (const [game, ids] of Object.entries(this._heardByGame)) {
      byGame[game] = [...ids];
    }
    return {
      by_game: byGame,
      updated_at: new Date().toISOString(),
    };
  }

  _saveProgress() {
    const payload = this._progressPayload();
    try {
      window.localStorage.setItem(this._storageKey, JSON.stringify(payload));
    } catch (_) {
      // Storage can be blocked in some webviews; the card still works for the session.
    }

    if (this._config.persist_progress === false || !this._hass?.callService) return;
    this._hass.callService("glados_voice", "save_progress", { by_game: payload.by_game }).catch(() => {
      // Server-side persistence is best effort; localStorage remains as a fallback.
    });
  }

  _resetProgress(game = null) {
    if (game) {
      this._heardByGame[game] = new Set();
    } else {
      this._heardByGame = this._emptyProgress();
    }
    this._queuedCompletionGame = null;
    this._completionSongPlaying = false;
    this._saveProgress();
  }

  _markHeard(item) {
    if (!item || (item.kind || "line") !== "line") return;
    const game = item.game || "Unknown";
    if (!this._heardByGame[game]) this._heardByGame[game] = new Set();

    const wasComplete = this._isGameComplete(game);
    if (!this._heardByGame[game].has(item.id)) {
      this._heardByGame[game].add(item.id);
      this._saveProgress();
    }

    if (!wasComplete && this._isGameComplete(game)) {
      this._queuedCompletionGame = game;
    }
  }

  _isGameComplete(game) {
    const total = this._linesByGame.get(game)?.length || 0;
    if (!total) return false;
    return (this._heardByGame[game]?.size || 0) >= total;
  }

  _pickRandom(play = true) {
    if (!this._lineItems.length) return;

    // If the user shuffles away from a completion song, count that game's cycle as done.
    if ((this._completionSongPlaying || this._current?.kind === "song") && this._current?.game) {
      this._resetProgress(this._current.game);
    }

    const next = this._lineItems[Math.floor(Math.random() * this._lineItems.length)];
    this._current = next;
    this._blocked = false;
    this._isFinished = false;
    this._completionSongPlaying = false;
    this._render();
    if (play) this._playCurrent({ restart: true });
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

  _makeAudio(item) {
    this._stopAudio();
    const audio = new Audio(item.audio);
    audio.preload = "auto";
    audio.volume = Number.isFinite(Number(this._config.volume)) ? Number(this._config.volume) : 1;
    audio._gladosItemId = item.id;
    audio.addEventListener("ended", () => this._handleAudioEnded(item));
    audio.addEventListener("pause", () => {
      if (this._audio === audio && !audio.ended) {
        this._isPlaying = false;
        this._isFinished = false;
        this._render();
      }
    });
    this._audio = audio;
    return audio;
  }

  async _playCurrent({ restart = true } = {}) {
    if (!this._current?.audio) return;

    let audio = this._audio;
    if (!audio || audio._gladosItemId !== this._current.id) {
      audio = this._makeAudio(this._current);
    } else if (restart || audio.ended) {
      audio.currentTime = 0;
    }

    try {
      await audio.play();
      this._blocked = false;
      this._isPlaying = true;
      this._isFinished = false;
      this._markHeard(this._current);
    } catch (_) {
      this._blocked = true;
      this._isPlaying = false;
    }
    this._render();
  }

  _toggleCurrent() {
    if (!this._current?.audio) return;

    const audioMatches = this._audio && this._audio._gladosItemId === this._current.id;
    if (audioMatches && !this._audio.paused && !this._audio.ended) {
      this._audio.pause();
      this._isPlaying = false;
      this._isFinished = false;
      this._render();
      return;
    }

    if (audioMatches && this._audio.paused && !this._audio.ended) {
      this._playCurrent({ restart: false });
      return;
    }

    this._playCurrent({ restart: true });
  }

  _handleAudioEnded(item) {
    if (!this._audio || this._audio._gladosItemId !== item.id) return;

    this._isPlaying = false;
    this._isFinished = true;
    this._render();

    if ((item.kind || "line") === "line" && this._queuedCompletionGame === item.game) {
      const song = this._completionSongs[item.game];
      if (song?.audio) {
        window.setTimeout(() => this._playCompletionSong(item.game), 350);
      } else {
        this._resetProgress(item.game);
        this._render();
      }
      return;
    }

    if (item.kind === "song") {
      this._resetProgress(item.game);
      this._isFinished = true;
      this._render();
    }
  }

  _playCompletionSong(game) {
    const song = this._completionSongs[game];
    if (!song?.audio) return;
    this._queuedCompletionGame = null;
    this._completionSongPlaying = true;
    this._current = song;
    this._blocked = false;
    this._isFinished = false;
    this._render();
    this._playCurrent({ restart: true });
  }

  _contextText() {
    if (!this._current || this._config.show_context === false) return "";
    const bits = [this._current.game, this._current.chapter, this._current.section].filter(Boolean);
    return bits.join(" > ");
  }

  _progressText() {
    if (this._config.show_progress === false || !this._lineItems.length) return "";
    const bits = [];
    for (const [game, lines] of this._linesByGame.entries()) {
      const label = game === "Portal" ? "P1" : game === "Portal 2" ? "P2" : game;
      bits.push(`${label} ${this._heardByGame[game]?.size || 0}/${lines.length}`);
    }
    return bits.join(" · ");
  }

  _statusText() {
    if (this._blocked) return "Browser blocked autoplay. Tap the transcript.";
    if (this._isPlaying) return "Playing — tap transcript to pause.";
    if (this._audio && this._audio._gladosItemId === this._current?.id && this._audio.paused && !this._audio.ended) {
      return "Paused — tap transcript to resume.";
    }
    if (this._isFinished) return "Finished — tap transcript to replay.";
    return "";
  }

  _render() {
    const quote = this._current?.quote || this._current?.title || (this._loading ? "Loading GLaDOS voice lines…" : "No voice line selected.");
    const context = this._contextText();
    const progress = this._progressText();
    const status = this._statusText();
    const error = this._error ? `<div class="error">${this._escape(this._error)}</div>` : "";
    const metaBits = [progress, context].filter(Boolean);
    const meta = metaBits.length ? `<div class="context">${this._escape(metaBits.join(" · "))}</div>` : "";
    const statusLine = status ? `<div class="${this._blocked ? "hint" : "status"}">${this._escape(status)}</div>` : "";

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
          grid-template-columns: minmax(0, 1fr) 44px;
          align-items: stretch;
          min-height: 56px;
        }
        button {
          border: 0;
          background: transparent;
          color: var(--secondary-text-color, var(--primary-text-color));
          cursor: pointer;
          min-width: 44px;
          padding: 0 10px 0 6px;
          display: flex;
          align-items: center;
          justify-content: center;
          opacity: 0.72;
          -webkit-tap-highlight-color: transparent;
        }
        button:hover {
          color: var(--primary-text-color);
          opacity: 1;
          background: color-mix(in srgb, var(--card-background-color) 92%, var(--primary-color));
        }
        ha-icon {
          --mdc-icon-size: 22px;
        }
        .quote {
          padding: 10px 8px 10px 12px;
          cursor: pointer;
          user-select: none;
          line-height: 1.25;
          min-width: 0;
        }
        .quoteText {
          font-size: 0.96rem;
          white-space: normal;
          overflow-wrap: anywhere;
        }
        .context, .hint, .error, .status {
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
        .status {
          opacity: 0.62;
        }
      </style>
      <ha-card>
        <div class="wrap">
          <div class="quote" title="Tap to pause, resume, or replay this voice line">
            <div class="quoteText">${this._escape(quote)}</div>
            ${meta}
            ${statusLine}
            ${error}
          </div>
          <button title="Shuffle random GLaDOS line" aria-label="Shuffle random GLaDOS line">
            <ha-icon icon="mdi:shuffle"></ha-icon>
          </button>
        </div>
      </ha-card>
    `;

    this.shadowRoot.querySelector("button")?.addEventListener("click", (event) => {
      event.stopPropagation();
      this._pickRandom(true);
    });
    this.shadowRoot.querySelector(".quote")?.addEventListener("click", () => this._toggleCurrent());
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
  description: "Random local Portal and Portal 2 GLaDOS quote player.",
});
