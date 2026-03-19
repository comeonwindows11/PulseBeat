(function () {
  const STORAGE_KEY = "music_player_state_v2";
  const WAVE_STORAGE_KEY = "music_player_wave_v1";
  const DEFAULT_PAGE_TITLE = document.title;
  const i18n = window.I18N || {
    playerNoSong: "Aucune musique",
    playerUnknown: "Inconnu",
    playerUntitled: "Sans titre",
    playerPlay: "Lecture",
    playerPause: "Pause",
    playerModeNormal: "Lecture normale",
    playerModeShuffle: "Lecture aléatoire",
    playerModeRepeatOne: "Répéter 1 chanson",
    playerAutoMode: "Lecture automatique",
    playerViewMini: "Lecteur minimal",
    playerViewNormal: "Lecteur normal",
    playerViewFullscreen: "Lecteur plein écran",
    playerStreamError: "Une erreur s'est produite lors de l'obtention de la chanson.",
    playerStreamErrorCode: "Code {code}.",
    playerStreamErrorRecovered: "Le fichier audio a été reconstruit depuis la base de données.",
    playerStreamErrorRebuildWait: "Le fichier audio est en cours de reconstruction depuis la base de données.",
    playerTryNext: "Essaie de passer à la chanson suivante.",
    playerTabBlockedNotice: "Lecture bloquée sur cet onglet tant que tu n'as pas confirmé l'activation audio.",
    playerAlbum: "PulseBeat",
  };

  const audio = document.getElementById("global-audio");
  const playerShell = document.querySelector(".player-shell");
  const titleEl = document.getElementById("player-title");
  const titleLinkEl = document.getElementById("player-title-link");
  const artistEl = document.getElementById("player-artist");
  const playPauseBtn = document.getElementById("play-pause-btn");
  const prevBtn = document.getElementById("prev-btn");
  const nextBtn = document.getElementById("next-btn");
  const modeBtn = document.getElementById("play-mode-btn");
  const addToPlaylistBtn = document.getElementById("add-to-playlist-btn");
  const playerViewBtn = document.getElementById("player-view-btn");
  const playerViewStatus = document.getElementById("player-view-status");
  const playerErrorBanner = document.getElementById("player-error-banner");
  const playerErrorText = document.getElementById("player-error-text");
  const seek = document.getElementById("seek-range");
  const playlistModal = document.getElementById("player-playlist-modal");
  const playlistModalClose = document.getElementById("player-playlist-close");
  const playlistSearch = document.getElementById("player-playlist-search");
  const playlistSuggestions = document.getElementById("player-playlist-suggestions");
  const playlistStatus = document.getElementById("player-playlist-status");
  const playlistToast = document.getElementById("player-playlist-toast");
  const queueEditorBtn = document.getElementById("queue-editor-btn");
  const queueEditorModal = document.getElementById("player-queue-modal");
  const queueEditorClose = document.getElementById("queue-editor-close");
  const queueList = document.getElementById("player-queue-list");
  const queueInfo = document.getElementById("player-queue-info");
  const queueEmpty = document.getElementById("player-queue-empty");
  const queueClearBtn = document.getElementById("queue-clear-btn");
  const queueCrossfadeToggle = document.getElementById("queue-crossfade-toggle");
  const queueNormalizeToggle = document.getElementById("queue-normalize-toggle");
  const openCreatePlaylistBtn = document.getElementById("player-open-create-playlist-modal");
  const createPlaylistModal = document.getElementById("player-create-playlist-modal");
  const createPlaylistNameInput = document.getElementById("player-create-playlist-name");
  const createPlaylistConfirmBtn = document.getElementById("player-create-playlist-confirm");
  const createPlaylistCancelBtn = document.getElementById("player-create-playlist-cancel");
  const likeBtn = document.getElementById("player-like-btn");
  const dislikeBtn = document.getElementById("player-dislike-btn");
  const likeCountEl = document.getElementById("player-like-count");
  const dislikeCountEl = document.getElementById("player-dislike-count");
  const playerShareBtn = document.getElementById("player-share-btn");
  const playerMoreBtn = document.getElementById("player-more-btn");
  const playerContextMenu = document.getElementById("player-context-menu");
  const playerMenuBlockSong = document.getElementById("player-menu-block-song");
  const playerMenuBlockArtist = document.getElementById("player-menu-block-artist");
  const playerActionToast = document.getElementById("player-action-toast");
  const playerActionToastText = document.getElementById("player-action-toast-text");
  const playerActionToastUndo = document.getElementById("player-action-toast-undo");
  const speedSelect = document.getElementById("speed-select");
  const currentTimeEl = document.getElementById("time-current");
  const remainingTimeEl = document.getElementById("time-remaining");
  const waveform = document.getElementById("waveform");
  const youtubeHost = document.getElementById("youtube-player-host");
  const lyricsPanel = document.getElementById("player-lyrics-panel");
  const lyricsCuesEl = document.getElementById("player-lyrics-cues");
  const lyricsFullEl = document.getElementById("player-lyrics-full");
  const lyricsEmptyEl = document.getElementById("player-lyrics-empty");
  const tabGuardModal = document.getElementById("tab-audio-guard-modal");
  const tabGuardAllowBtn = document.getElementById("tab-audio-guard-allow");
  const tabGuardDenyBtn = document.getElementById("tab-audio-guard-deny");

  const TAB_REGISTRY_KEY = "pulsebeat_active_tabs_v1";
  const TAB_ID_KEY = "pulsebeat_tab_id_v1";
  const TAB_OPENED_AT_KEY = "pulsebeat_tab_opened_at_v1";
  const TAB_AUDIO_DECISION_KEY = "pulsebeat_tab_audio_decision_v1";
  const TAB_HEARTBEAT_MS = 5000;
  const TAB_STALE_MS = 20000;
  const MOBILE_PLAYER_BREAKPOINT_QUERY = "(max-width: 768px)";
  const mobilePlayerMediaQuery = window.matchMedia ? window.matchMedia(MOBILE_PLAYER_BREAKPOINT_QUERY) : null;

  if (!audio) return;

  const isAuthenticated = Number(i18n.isAuthenticated || 0) === 1;
  if (!isAuthenticated && playerMoreBtn) {
    playerMoreBtn.classList.add("hidden");
    playerMoreBtn.setAttribute("aria-hidden", "true");
    playerMoreBtn.setAttribute("tabindex", "-1");
  }

  let audioCtx = null;
  let analyser = null;
  let sourceNode = null;
  let gainNode = null;
  let ytPlayer = null;
  let ytReadyPromise = null;
  let ytProgressTimer = null;
  let ytCurrentVideoId = "";
  let waveformRaf = 0;
  let gainFadeTimer = null;
  let normalizationProbe = { samples: 0, sumRms: 0, locked: false };
  const playbackMetaCache = new Map();
  let cachedWaveBars = [];
  try {
    const waveRaw = sessionStorage.getItem(WAVE_STORAGE_KEY);
    if (waveRaw) {
      const parsed = JSON.parse(waveRaw);
      if (Array.isArray(parsed)) cachedWaveBars = parsed;
    }
  } catch (_e) {
    cachedWaveBars = [];
  }

  let state = {
    queue: [],
    index: 0,
    isPlaying: false,
    time: 0,
    playMode: "normal",
    shuffleHistory: [],
    queueContext: "auto",
    playbackRate: 1,
    startedSongId: null,
    playlistModalOpen: false,
    queueEditorOpen: false,
    viewMode: mobilePlayerMediaQuery && mobilePlayerMediaQuery.matches ? "mini" : "normal",
    crossfadeEnabled: true,
    normalizeVolumeEnabled: true,
    normalizationGain: 1,
    isTransitioning: false,
    activeEngine: "audio",
    manualStartSongId: "",
    manualRecoverySongId: "",
    unavailableSkipCounter: 0,
  };





  let toastTimer = null;
  let actionToastTimer = null;
  let pendingUndoAction = null;
  let lyricsState = { songId: "", text: "", cues: [], autoSync: false };
  let playerVoteState = { likes: 0, dislikes: 0, user_vote: 0 };
  const youtubeErrorAttempts = new Map();
  let youtubeSkipLocked = false;
  let lastPrevActionAt = 0;
  let creatingPlaylist = false;
  let tabGuardNoticeAt = 0;
  let playerShellVisible = false;
  let playerShellAnimateOnNextReveal = false;
  let manualPlaybackAssistTimers = [];
  const tabGuardState = {
    tabId: "",
    runtimeId: "",
    openedAt: 0,
    decision: "ask",
    blocked: false,
    heartbeatTimer: null,
  };
  let playerGestureState = null;

  function jsonHeaders(withJsonContent = true) {
    const headers = {
      "X-Requested-With": "XMLHttpRequest",
    };
    if (window.CSRF_TOKEN) {
      headers["X-CSRF-Token"] = window.CSRF_TOKEN;
    }
    if (withJsonContent) {
      headers["Content-Type"] = "application/json";
    }
    return headers;
  }

  function safeParseJson(raw, fallback) {
    if (!raw) return fallback;
    try {
      const parsed = JSON.parse(raw);
      return parsed && typeof parsed === "object" ? parsed : fallback;
    } catch (_e) {
      return fallback;
    }
  }

  function createRuntimeId() {
    if (window.crypto && typeof window.crypto.randomUUID === "function") {
      return window.crypto.randomUUID();
    }
    return `pb_runtime_${Date.now()}_${Math.random().toString(36).slice(2, 12)}`;
  }

  function getOrCreateTabId() {
    let tabId = String(sessionStorage.getItem(TAB_ID_KEY) || "").trim();
    if (tabId) return tabId;
    tabId = `pb_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
    sessionStorage.setItem(TAB_ID_KEY, tabId);
    return tabId;
  }

  function getOrCreateOpenedAt() {
    const existing = Number(sessionStorage.getItem(TAB_OPENED_AT_KEY) || 0);
    if (Number.isFinite(existing) && existing > 0) return existing;
    const now = Date.now();
    sessionStorage.setItem(TAB_OPENED_AT_KEY, String(now));
    return now;
  }

  function readTabRegistry() {
    return safeParseJson(localStorage.getItem(TAB_REGISTRY_KEY), {});
  }

  function writeTabRegistry(registry) {
    try {
      localStorage.setItem(TAB_REGISTRY_KEY, JSON.stringify(registry || {}));
    } catch (_e) {}
  }

  function cleanupTabRegistry(registry) {
    const now = Date.now();
    const next = {};
    Object.entries(registry || {}).forEach(([id, info]) => {
      const openedAt = Number((info && info.openedAt) || 0);
      const lastSeen = Number((info && info.lastSeen) || 0);
      const runtimeId = String((info && info.runtimeId) || "").trim();
      if (!id || !openedAt || !lastSeen) return;
      if (now - lastSeen > TAB_STALE_MS) return;
      next[id] = { openedAt, lastSeen, runtimeId };
    });
    return next;
  }

  function forceNewTabIdentity() {
    const nextId = `pb_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
    const now = Date.now();
    tabGuardState.tabId = nextId;
    tabGuardState.openedAt = now;
    tabGuardState.decision = "ask";
    try {
      sessionStorage.setItem(TAB_ID_KEY, nextId);
      sessionStorage.setItem(TAB_OPENED_AT_KEY, String(now));
      sessionStorage.setItem(TAB_AUDIO_DECISION_KEY, "ask");
    } catch (_e) {}
  }

  function ensureTabRegistered() {
    const now = Date.now();
    let registry = cleanupTabRegistry(readTabRegistry());
    const existingEntry = registry[tabGuardState.tabId];
    if (
      existingEntry
      && existingEntry.runtimeId
      && tabGuardState.runtimeId
      && existingEntry.runtimeId !== tabGuardState.runtimeId
      && now - Number(existingEntry.lastSeen || 0) <= TAB_STALE_MS
    ) {
      forceNewTabIdentity();
      registry = cleanupTabRegistry(readTabRegistry());
    }
    const existing = registry[tabGuardState.tabId] || {};
    registry[tabGuardState.tabId] = {
      openedAt: tabGuardState.openedAt || Number(existing.openedAt || 0) || now,
      lastSeen: now,
      runtimeId: tabGuardState.runtimeId,
    };
    tabGuardState.openedAt = Number(registry[tabGuardState.tabId].openedAt || now) || now;
    writeTabRegistry(registry);
    return registry;
  }

  function unregisterTab() {
    const registry = cleanupTabRegistry(readTabRegistry());
    if (registry[tabGuardState.tabId]) {
      delete registry[tabGuardState.tabId];
      writeTabRegistry(registry);
    }
  }

  function hideTabGuardModal() {
    if (!tabGuardModal) return;
    tabGuardModal.classList.add("hidden");
    tabGuardModal.setAttribute("aria-hidden", "true");
  }

  function showTabGuardModal() {
    if (!tabGuardModal) return;
    tabGuardModal.classList.remove("hidden");
    tabGuardModal.setAttribute("aria-hidden", "false");
  }

  function stopPlaybackForTabGuard() {
    try {
      if (ytPlayer && typeof ytPlayer.pauseVideo === "function") {
        ytPlayer.pauseVideo();
      }
    } catch (_e) {}
    try {
      audio.pause();
    } catch (_e) {}
    state.isPlaying = false;
    updateMeta(currentSong());
    saveState();
  }

  function setTabAudioDecision(decision) {
    const normalized = decision === "allow" ? "allow" : "deny";
    tabGuardState.decision = normalized;
    try {
      sessionStorage.setItem(TAB_AUDIO_DECISION_KEY, normalized);
    } catch (_e) {}
    tabGuardState.blocked = normalized !== "allow";
    if (tabGuardState.blocked) {
      stopPlaybackForTabGuard();
    }
  }

  function evaluateTabGuard(showPrompt = true) {
    const registry = ensureTabRegistered();
    const entries = Object.entries(registry).sort((a, b) => {
      const aOpened = Number((a[1] && a[1].openedAt) || 0);
      const bOpened = Number((b[1] && b[1].openedAt) || 0);
      if (aOpened !== bOpened) return aOpened - bOpened;
      return String(a[0]).localeCompare(String(b[0]));
    });
    const activeCount = entries.length;
    const oldestTabId = entries.length ? String(entries[0][0]) : tabGuardState.tabId;
    const isOldestTab = oldestTabId === tabGuardState.tabId;

    if (activeCount <= 1 || isOldestTab) {
      tabGuardState.blocked = false;
      hideTabGuardModal();
      return;
    }

    const decision = tabGuardState.decision || "ask";
    tabGuardState.blocked = decision !== "allow";
    if (tabGuardState.blocked) {
      stopPlaybackForTabGuard();
      if (showPrompt) {
        showTabGuardModal();
      }
    } else {
      hideTabGuardModal();
    }
  }

  function isPlaybackBlocked(showPrompt = false) {
    evaluateTabGuard(showPrompt);
    if (!tabGuardState.blocked) return false;
    if (showPrompt) {
      const now = Date.now();
      if (now - tabGuardNoticeAt > 1500) {
        showPlaylistToast(i18n.playerTabBlockedNotice || "Playback is blocked on this tab.", "error");
        tabGuardNoticeAt = now;
      }
    }
    return true;
  }

  function initTabGuard() {
    tabGuardState.runtimeId = createRuntimeId();
    tabGuardState.tabId = getOrCreateTabId();
    tabGuardState.openedAt = getOrCreateOpenedAt();
    const decision = String(sessionStorage.getItem(TAB_AUDIO_DECISION_KEY) || "ask").trim().toLowerCase();
    tabGuardState.decision = decision === "allow" ? "allow" : (decision === "deny" ? "deny" : "ask");

    ensureTabRegistered();
    evaluateTabGuard(true);

    if (tabGuardAllowBtn) {
      tabGuardAllowBtn.addEventListener("click", () => {
        setTabAudioDecision("allow");
        hideTabGuardModal();
      });
    }
    if (tabGuardDenyBtn) {
      tabGuardDenyBtn.addEventListener("click", () => {
        setTabAudioDecision("deny");
        hideTabGuardModal();
      });
    }

    window.addEventListener("storage", (event) => {
      if (event.key !== TAB_REGISTRY_KEY) return;
      evaluateTabGuard(false);
    });

    window.addEventListener("beforeunload", unregisterTab);
    window.addEventListener("pagehide", unregisterTab);
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") {
        ensureTabRegistered();
        evaluateTabGuard(false);
      }
    });

    if (tabGuardState.heartbeatTimer) {
      clearInterval(tabGuardState.heartbeatTimer);
    }
    tabGuardState.heartbeatTimer = setInterval(() => {
      ensureTabRegistered();
      evaluateTabGuard(false);
    }, TAB_HEARTBEAT_MS);
  }

  function extractYouTubeVideoId(rawValue) {
    const value = String(rawValue || "").trim();
    if (!value) return "";
    try {
      const parsed = new URL(value, window.location.origin);
      const host = (parsed.hostname || "").toLowerCase();
      if (host.includes("youtube.com")) {
        const fromQuery = (parsed.searchParams.get("v") || "").trim();
        if (fromQuery) return fromQuery;
        if (parsed.pathname.startsWith("/shorts/")) return parsed.pathname.replace("/shorts/", "").split("/")[0].trim();
        if (parsed.pathname.startsWith("/embed/")) return parsed.pathname.replace("/embed/", "").split("/")[0].trim();
      }
      if (host.includes("youtu.be")) {
        return (parsed.pathname || "").replace("/", "").split("/")[0].trim();
      }
    } catch (_e) {
      return "";
    }
    return "";
  }

  function isYouTubeSong(song) {
    if (!song) return false;
    if (song.playback_mode === "youtube") return true;
    if (song.external_provider === "youtube") return true;
    if (song.youtube_video_id) return true;
    const fromUrl = extractYouTubeVideoId(song.source_url || song.external_url || "");
    return Boolean(fromUrl);
  }

  function isSongAvailable(song) {
    if (!song) return false;
    return song.is_available !== false;
  }

  function isSongAudioPlayable(song) {
    if (!song) return false;
    if (song.is_audio_playable === false) return false;
    if (song.is_audio_playable === true) return true;
    if (!isSongAvailable(song)) return false;
    return !isYouTubeSong(song);
  }

  function isYoutubeEngineActive() {
    return state.activeEngine === "youtube";
  }

  function applyMetaToSong(song, metaItem) {
    if (!song || !metaItem) return song;
    song.playback_mode = metaItem.playback_mode || song.playback_mode || "";
    song.is_available = metaItem.is_available !== false;
    song.is_audio_playable = !!metaItem.is_audio_playable;
    song.source_type = metaItem.source_type || song.source_type || "";
    song.source_url = metaItem.source_url || song.source_url || "";
    song.external_provider = metaItem.external_provider || song.external_provider || "";
    song.youtube_video_id = metaItem.youtube_video_id || song.youtube_video_id || extractYouTubeVideoId(song.source_url || "");
    song.external_url = metaItem.external_url || song.external_url || song.source_url || "";
    if (metaItem.visibility) song.visibility = metaItem.visibility;
    if (metaItem.stream_url) song.url = metaItem.stream_url;
    if (!song.url && !song.is_audio_playable) song.url = "";
    return song;
  }

  function updateSongInQueueById(songId, updater) {
    if (!songId || typeof updater !== "function") return;
    state.queue = (state.queue || []).map((row) => {
      if (!row || String(row.id) !== String(songId)) return row;
      return updater(row) || row;
    });
    renderQueueEditor();
  }

  function markSongAvailabilityUI(songId, available) {
    if (!songId) return;
    const rows = document.querySelectorAll(`li[data-song-id="${CSS.escape(String(songId))}"]`);
    rows.forEach((row) => {
      row.classList.toggle("song-unavailable", !available);
    });

    const playButtons = document.querySelectorAll(".play-one[data-song]");
    playButtons.forEach((btn) => {
      const raw = btn.getAttribute("data-song");
      if (!raw) return;
      const item = parseSong(raw);
      if (!item || String(item.id) !== String(songId)) return;
      item.is_available = !!available;
      if (!available) item.is_audio_playable = false;
      btn.setAttribute("data-song", JSON.stringify(item));
      const parentRow = btn.closest("li");
      if (parentRow) parentRow.classList.toggle("song-unavailable", !available);
    });
  }

  async function setSongAvailability(song, available, reason) {
    if (!song || !song.id) return false;
    try {
      const res = await fetch(`/songs/${encodeURIComponent(song.id)}/availability`, {
        method: "POST",
        credentials: "same-origin",
        headers: jsonHeaders(true),
        body: JSON.stringify({ available: !!available, reason: reason || "" }),
      });
      if (!res.ok) return false;
      song.is_available = !!available;
      if (song.id) {
        playbackMetaCache.delete(String(song.id));
      }
      if (Array.isArray(window.PAGE_SONG_OBJECTS)) {
        window.PAGE_SONG_OBJECTS = window.PAGE_SONG_OBJECTS.map((row) => {
          if (!row || String(row.id) !== String(song.id)) return row;
          row.is_available = !!available;
          if (!available) row.is_audio_playable = false;
          return row;
        });
      }
      if (Array.isArray(window.PAGE_RECOMMENDED_SONGS)) {
        window.PAGE_RECOMMENDED_SONGS = window.PAGE_RECOMMENDED_SONGS.map((row) => {
          if (!row || String(row.id) !== String(song.id)) return row;
          row.is_available = !!available;
          if (!available) row.is_audio_playable = false;
          return row;
        });
      }
      updateSongInQueueById(song.id, (row) => {
        row.is_available = !!available;
        if (!available) row.is_audio_playable = false;
        return row;
      });
      markSongAvailabilityUI(song.id, !!available);
      return true;
    } catch (_e) {
      return false;
    }
  }

  async function ensureSongPlaybackMeta(song) {
    if (!song || !song.id) return song;
    if (song.__metaLoaded) return song;
    const songId = String(song.id);
    if (playbackMetaCache.has(songId)) {
      applyMetaToSong(song, playbackMetaCache.get(songId));
      song.__metaLoaded = true;
      return song;
    }
    const shouldFetchServerMeta = isYouTubeSong(song);
    if (!shouldFetchServerMeta && (song.playback_mode || song.source_type || song.youtube_video_id || song.external_provider)) {
      const inferred = {
        playback_mode: isYouTubeSong(song) ? "youtube" : "audio",
        is_available: isSongAvailable(song),
        is_audio_playable: isSongAudioPlayable(song),
        source_type: song.source_type || "",
        source_url: song.source_url || "",
        external_provider: song.external_provider || "",
        youtube_video_id: song.youtube_video_id || extractYouTubeVideoId(song.source_url || ""),
        stream_url: song.url || "",
        external_url: song.external_url || song.source_url || "",
      };
      playbackMetaCache.set(songId, inferred);
      applyMetaToSong(song, inferred);
      song.__metaLoaded = true;
      return song;
    }
    try {
      const res = await fetch(`/songs/${encodeURIComponent(songId)}/playback-meta`, {
        credentials: "same-origin",
        cache: "no-store",
        headers: jsonHeaders(false),
      });
      if (!res.ok) {
        song.__metaLoaded = true;
        return song;
      }
      const data = await res.json();
      if (data && data.ok && data.item) {
        playbackMetaCache.set(songId, data.item);
        applyMetaToSong(song, data.item);
      }
    } catch (_e) {
    }
    song.__metaLoaded = true;
    return song;
  }

  async function ensureYouTubeApiReady() {
    if (window.YT && window.YT.Player) return window.YT;
    if (ytReadyPromise) return ytReadyPromise;
    ytReadyPromise = new Promise((resolve, reject) => {
      const previous = window.onYouTubeIframeAPIReady;
      window.onYouTubeIframeAPIReady = function () {
        if (typeof previous === "function") {
          try { previous(); } catch (_e) {}
        }
        resolve(window.YT);
      };
      const script = document.createElement("script");
      script.src = "https://www.youtube.com/iframe_api";
      script.async = true;
      script.onerror = () => reject(new Error("youtube_api_load_failed"));
      document.head.appendChild(script);
    });
    return ytReadyPromise;
  }

  function clearYoutubeTimer() {
    if (ytProgressTimer) {
      window.clearInterval(ytProgressTimer);
      ytProgressTimer = null;
    }
  }

  function refreshProgressUI(current, duration) {
    const safeCurrent = Math.max(0, Number(current) || 0);
    const safeDuration = Math.max(0, Number(duration) || 0);
    if (safeDuration > 0) {
      seek.value = Math.floor((safeCurrent / safeDuration) * 1000);
      if (currentTimeEl) currentTimeEl.textContent = formatTime(safeCurrent);
      if (remainingTimeEl) remainingTimeEl.textContent = `-${formatTime(Math.max(0, safeDuration - safeCurrent))}`;
      renderLyricsAt(safeCurrent);
      updateMediaSessionPosition(safeCurrent, safeDuration);
    } else {
      seek.value = 0;
      if (currentTimeEl) currentTimeEl.textContent = "00:00";
      if (remainingTimeEl) remainingTimeEl.textContent = "-00:00";
    }
  }

  function startYoutubeTimer() {
    if (!ytPlayer) return;
    clearYoutubeTimer();
    ytProgressTimer = window.setInterval(() => {
      if (!isYoutubeEngineActive() || !ytPlayer) return;
      try {
        const current = Number(ytPlayer.getCurrentTime ? ytPlayer.getCurrentTime() : 0) || 0;
        const duration = Number(ytPlayer.getDuration ? ytPlayer.getDuration() : 0) || 0;
        refreshProgressUI(current, duration);
      } catch (_e) {}
    }, 250);
  }

  function getPlaybackTimeSeconds() {
    if (isYoutubeEngineActive() && ytPlayer && typeof ytPlayer.getCurrentTime === "function") {
      try {
        return Number(ytPlayer.getCurrentTime() || 0) || 0;
      } catch (_e) {}
    }
    return Number(audio.currentTime || 0) || 0;
  }

  function getPlaybackDurationSeconds() {
    if (isYoutubeEngineActive() && ytPlayer && typeof ytPlayer.getDuration === "function") {
      try {
        return Number(ytPlayer.getDuration() || 0) || 0;
      } catch (_e) {}
    }
    return Number(audio.duration || 0) || 0;
  }

  function restartCurrentSongFromStart() {
    state.time = 0;
    if (isYoutubeEngineActive() && ytPlayer && typeof ytPlayer.seekTo === "function") {
      try {
        ytPlayer.seekTo(0, true);
        if (!state.isPlaying && typeof ytPlayer.pauseVideo === "function") {
          ytPlayer.pauseVideo();
        }
      } catch (_e) {}
      refreshProgressUI(0, getPlaybackDurationSeconds());
      saveState();
      if (!state.isPlaying) {
        updateMeta(currentSong());
      }
      return;
    }

    audio.currentTime = 0;
    saveState();
    if (audio.paused) {
      updateMeta(currentSong());
    }
  }

  function isMobilePlayerLayout() {
    if (mobilePlayerMediaQuery) return !!mobilePlayerMediaQuery.matches;
    return window.innerWidth <= 768;
  }

  function allowedViewModes() {
    return isMobilePlayerLayout() ? ["mini", "fullscreen"] : ["normal", "fullscreen"];
  }

  function defaultViewMode() {
    return isMobilePlayerLayout() ? "mini" : "normal";
  }

  function normalizeViewMode(mode) {
    const allowedModes = allowedViewModes();
    return allowedModes.includes(mode) ? mode : defaultViewMode();
  }

  function viewModeLabel(mode) {
    if (mode === "mini") return i18n.playerViewMini || "Mini player";
    if (mode === "fullscreen") return i18n.playerViewFullscreen || "Fullscreen player";
    return i18n.playerViewNormal || "Standard player";
  }

  function nextViewMode() {
    const allowedModes = allowedViewModes();
    const currentMode = normalizeViewMode(state.viewMode);
    const currentIndex = allowedModes.indexOf(currentMode);
    if (currentIndex < 0) return defaultViewMode();
    return allowedModes[(currentIndex + 1) % allowedModes.length] || defaultViewMode();
  }

  function syncPlayerOffset() {
    const root = document.documentElement;
    if (!root || !playerShell) return;
    const song = currentSong();
    const offset = (!song || !song.id || playerShell.classList.contains("player-shell-hidden") || state.viewMode === "fullscreen")
      ? 0
      : playerShell.offsetHeight || 0;
    root.style.setProperty("--player-offset", `${offset}px`);
  }

  function updateViewModeUI() {
    if (playerShell) playerShell.dataset.viewMode = state.viewMode;
    if (playerViewBtn) {
      const upcomingMode = nextViewMode();
      playerViewBtn.dataset.viewMode = upcomingMode;
      playerViewBtn.setAttribute("aria-label", viewModeLabel(upcomingMode));
      playerViewBtn.title = viewModeLabel(upcomingMode);
    }
    if (playerViewStatus) playerViewStatus.textContent = viewModeLabel(state.viewMode);
    document.body.classList.toggle("player-fullscreen-open", state.viewMode === "fullscreen");
    syncPlayerOffset();
    renderLyricsAt(getPlaybackTimeSeconds());
  }

  function setViewMode(mode, persist) {
    state.viewMode = normalizeViewMode(mode);
    updateViewModeUI();
    if (persist) saveState();
  }

  function cycleViewMode() {
    setViewMode(nextViewMode(), true);
  }

  function syncViewModeToViewport() {
    const normalized = normalizeViewMode(state.viewMode);
    const changed = normalized !== state.viewMode;
    state.viewMode = normalized;
    updateViewModeUI();
    if (changed) saveState();
  }

  function initPlayerTouchGestures() {
    if (!playerShell) return;

    playerShell.addEventListener("pointerdown", (event) => {
      if (!isMobilePlayerLayout()) return;
      if (!event.target || !event.target.closest) return;
      if (!event.target.closest(".player-gesture-handle, .song-meta")) return;
      playerGestureState = {
        startX: event.clientX,
        startY: event.clientY,
        startMode: state.viewMode,
      };
    }, { passive: true });

    playerShell.addEventListener("pointerup", (event) => {
      if (!playerGestureState || !isMobilePlayerLayout()) {
        playerGestureState = null;
        return;
      }
      const dx = event.clientX - playerGestureState.startX;
      const dy = event.clientY - playerGestureState.startY;
      const startMode = playerGestureState.startMode;
      playerGestureState = null;
      if (Math.abs(dy) < 52 || Math.abs(dy) < Math.abs(dx)) return;

      if (startMode === "mini" && dy < -52) {
        setViewMode("fullscreen", true);
      } else if (startMode === "fullscreen" && dy > 52) {
        setViewMode("mini", true);
      }
    }, { passive: true });
  }

  function clearLyricsUI() {
    if (lyricsPanel) lyricsPanel.classList.add("hidden");
    if (lyricsCuesEl) {
      lyricsCuesEl.classList.add("hidden");
      lyricsCuesEl.innerHTML = "";
    }
    if (lyricsFullEl) {
      lyricsFullEl.classList.add("hidden");
      lyricsFullEl.textContent = "";
    }
    if (lyricsEmptyEl) lyricsEmptyEl.classList.add("hidden");
  }

  function renderLyricsAt(timeSec) {
    if (!lyricsPanel) return;
    if (!isAuthenticated) {
      lyricsPanel.classList.add("hidden");
      return;
    }
    if (state.viewMode !== "fullscreen") {
      lyricsPanel.classList.add("hidden");
      return;
    }

    lyricsPanel.classList.remove("hidden");

    const hasText = Boolean(lyricsState.text);
    if (!hasText) {
      if (lyricsEmptyEl) lyricsEmptyEl.classList.remove("hidden");
      if (lyricsCuesEl) {
        lyricsCuesEl.classList.add("hidden");
        lyricsCuesEl.innerHTML = "";
      }
      if (lyricsFullEl) {
        lyricsFullEl.classList.add("hidden");
        lyricsFullEl.textContent = "";
      }
      return;
    }

    const cues = lyricsState.autoSync && Array.isArray(lyricsState.cues) ? lyricsState.cues : [];
    if (cues.length) {
      let idx = 0;
      const t = Number(timeSec) || 0;
      for (let i = 0; i < cues.length; i += 1) {
        if ((Number(cues[i].time) || 0) <= t) idx = i;
        else break;
      }
      const start = Math.max(0, idx - 1);
      const end = Math.min(cues.length, idx + 2);
      if (lyricsCuesEl) {
        lyricsCuesEl.innerHTML = "";
        for (let i = start; i < end; i += 1) {
          const line = document.createElement("div");
          line.className = `lyric-line${i === idx ? " active" : ""}`;
          line.textContent = cues[i].text || "";
          lyricsCuesEl.appendChild(line);
        }
        lyricsCuesEl.classList.remove("hidden");
      }
      if (lyricsFullEl) lyricsFullEl.classList.add("hidden");
      if (lyricsEmptyEl) lyricsEmptyEl.classList.add("hidden");
      return;
    }

    if (lyricsFullEl) {
      lyricsFullEl.textContent = lyricsState.text;
      lyricsFullEl.classList.remove("hidden");
    }
    if (lyricsCuesEl) lyricsCuesEl.classList.add("hidden");
    if (lyricsEmptyEl) lyricsEmptyEl.classList.add("hidden");
  }

  async function loadLyricsForSong(song) {
    if (!isAuthenticated) {
      lyricsState = { songId: "", text: "", cues: [], autoSync: false };
      clearLyricsUI();
      return;
    }
    if (!song || !song.id) {
      lyricsState = { songId: "", text: "", cues: [], autoSync: false };
      clearLyricsUI();
      return;
    }
    if (lyricsState.songId === song.id) {
      renderLyricsAt(getPlaybackTimeSeconds());
      return;
    }

    lyricsState = { songId: song.id, text: "", cues: [], autoSync: false };
    clearLyricsUI();

    try {
      const res = await fetch(`/songs/${encodeURIComponent(song.id)}/lyrics`, {
        credentials: "same-origin",
        cache: "no-store",
      });
      if (!res.ok) {
        renderLyricsAt(getPlaybackTimeSeconds());
        return;
      }
      const data = await res.json();
      if (!data || !data.ok || !data.has_lyrics) {
        renderLyricsAt(getPlaybackTimeSeconds());
        return;
      }
      if (lyricsState.songId !== song.id) return;
      lyricsState.text = data.lyrics_text || "";
      lyricsState.autoSync = Boolean(data.lyrics_auto_sync);
      lyricsState.cues = Array.isArray(data.lyrics_cues) ? data.lyrics_cues : [];
      renderLyricsAt(getPlaybackTimeSeconds());
    } catch (_e) {
      renderLyricsAt(getPlaybackTimeSeconds());
    }
  }


  function clearPlayerError() {
    if (!playerErrorBanner || !playerErrorText) return;
    playerErrorBanner.classList.add("hidden");
    playerErrorText.textContent = "";
  }

  function showPlayerError(statusCode) {
    if (!playerErrorBanner || !playerErrorText) return;
    if (typeof statusCode === "string") {
      playerErrorText.textContent = statusCode;
      playerErrorBanner.classList.remove("hidden");
      return;
    }
    const code = Number.isFinite(statusCode) ? String(statusCode) : "404";
    const codePart = (i18n.playerStreamErrorCode || "Code {code}.").replace("{code}", code);
    const suffix = i18n.playerTryNext || "Try skipping to the next song.";
    playerErrorText.textContent = `${i18n.playerStreamError || "An error occurred while fetching this song."} ${codePart} ${suffix}`;
    playerErrorBanner.classList.remove("hidden");
  }

  async function tryRecoverSongAudio(song) {
    if (!song || !song.id) return null;
    try {
      const res = await fetch(`/songs/${encodeURIComponent(song.id)}/recover-audio`, {
        method: "POST",
        credentials: "same-origin",
        headers: jsonHeaders(true),
        body: JSON.stringify({ reason: "stream_404" }),
      });
      const data = await res.json().catch(() => null);
      if (!data) return null;
      return {
        httpStatus: res.status,
        ok: !!data.ok,
        recoverable: !!data.recoverable,
        status: data.status || "",
        message: data.message || "",
        streamUrl: data.stream_url || "",
      };
    } catch (_e) {
      return null;
    }
  }

  async function detectSongHttpStatus(song) {
    if (!song || !song.url) return null;
    const req = { credentials: "same-origin", cache: "no-store", headers: { Range: "bytes=0-0" } };
    try {
      const res = await fetch(song.url, req);
      return res.status;
    } catch (_e) {
      return null;
    }
  }

  async function handleSongStreamError(song) {
    const status = await detectSongHttpStatus(song);
    if (status === 404 && song && song.source_type === "upload") {
      const recovery = await tryRecoverSongAudio(song);
      if (recovery && recovery.ok && recovery.status === "ready") {
        if (recovery.streamUrl) {
          song.url = recovery.streamUrl;
          song.__forceReload = true;
          updateSongInQueueById(song.id, (row) => {
            row.url = recovery.streamUrl;
            row.__forceReload = true;
            return row;
          });
        }
        clearPlayerError();
        showPlaylistToast(recovery.message || i18n.playerStreamErrorRecovered || "Audio rebuilt from database.", "success");
        await applySong(true, { manual: true });
        return;
      }
      if (recovery && recovery.recoverable && recovery.status === "rebuilding") {
        showPlayerError(recovery.message || i18n.playerStreamErrorRebuildWait || "Audio rebuild in progress. Please wait or skip.");
      } else if (recovery && recovery.message) {
        showPlayerError(recovery.message);
      } else {
        showPlayerError(404);
      }
    } else if (status === 404) {
      showPlayerError(404);
    } else {
      if (typeof status === "number" && status >= 400) {
        showPlayerError(status);
      } else {
        showPlayerError(`${i18n.playerStreamError || "An error occurred while fetching this song."} ${(i18n.playerTryNext || "Try skipping to the next song.").trim()}`.trim());
      }
    }
    state.isPlaying = false;
    updateMeta(song || currentSong());
    saveState();
  }

  function showPlaylistToast(message, type) {
    if (!playlistToast || !message) return;
    playlistToast.textContent = message;
    playlistToast.classList.remove("hidden", "success", "error", "show");
    playlistToast.classList.add(type === "success" ? "success" : "error");

    requestAnimationFrame(() => {
      playlistToast.classList.add("show");
    });

    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
      playlistToast.classList.remove("show");
      setTimeout(() => {
        playlistToast.classList.add("hidden");
      }, 220);
    }, 2200);
  }

  function setVoteButtonActive(button, active) {
    if (!button) return;
    button.classList.toggle("active", !!active);
  }

  function renderPlayerVoteState() {
    if (likeCountEl) likeCountEl.textContent = String(playerVoteState.likes || 0);
    if (dislikeCountEl) dislikeCountEl.textContent = String(playerVoteState.dislikes || 0);

    const hasSong = Boolean(currentSongOrNull());
    const canReact = isAuthenticated && hasSong;
    if (likeBtn) likeBtn.disabled = !canReact;
    if (dislikeBtn) dislikeBtn.disabled = !canReact;

    setVoteButtonActive(likeBtn, Number(playerVoteState.user_vote || 0) === 1);
    setVoteButtonActive(dislikeBtn, Number(playerVoteState.user_vote || 0) === -1);
  }

  function resetPlayerVoteState() {
    playerVoteState = { likes: 0, dislikes: 0, user_vote: 0 };
    renderPlayerVoteState();
  }

  async function refreshPlayerVoteState(song) {
    if (!song || !song.id) {
      resetPlayerVoteState();
      return;
    }
    try {
      const res = await fetch(`/songs/${encodeURIComponent(song.id)}/stats`, {
        credentials: "same-origin",
        cache: "no-store",
        headers: { "X-Requested-With": "XMLHttpRequest", Accept: "application/json" },
      });
      const data = res.ok ? await res.json() : null;
      if (!res.ok || !data || !data.ok) {
        resetPlayerVoteState();
        return;
      }
      playerVoteState.likes = Number(data.likes || 0);
      playerVoteState.dislikes = Number(data.dislikes || 0);
      playerVoteState.user_vote = Number(data.user_vote || 0);
      renderPlayerVoteState();
    } catch (_e) {
      resetPlayerVoteState();
    }
  }

  async function voteCurrentSong(voteValue) {
    const song = currentSongOrNull();
    if (!song || !song.id) return;
    if (!isAuthenticated) {
      showPlaylistToast(i18n.authRequired || "Login required.", "error");
      return;
    }

    const payload = new URLSearchParams();
    payload.set("vote", String(voteValue));

    try {
      const res = await fetch(`/songs/${encodeURIComponent(song.id)}/vote`, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "X-Requested-With": "XMLHttpRequest",
          Accept: "application/json",
          "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        },
        body: payload.toString(),
      });
      const data = res.ok ? await res.json() : null;
      if (!res.ok || !data || !data.ok) {
        showPlaylistToast((data && data.message) || i18n.playerPlaylistError || "Error", "error");
        return;
      }
      playerVoteState.likes = Number(data.likes || 0);
      playerVoteState.dislikes = Number(data.dislikes || 0);
      playerVoteState.user_vote = Number(data.user_vote || 0);
      renderPlayerVoteState();
    } catch (_e) {
      showPlaylistToast(i18n.playerPlaylistError || "Error", "error");
    }
  }

  function hidePlayerContextMenu() {
    if (!playerContextMenu) return;
    playerContextMenu.classList.add("hidden");
    playerContextMenu.setAttribute("aria-hidden", "true");
  }

  function showPlayerContextMenu(x, y) {
    const song = currentSongOrNull();
    if (!isAuthenticated || !playerContextMenu || !song) return;

    const artist = (song.artist || i18n.playerUnknown || "Unknown").trim();
    if (playerMenuBlockSong) {
      playerMenuBlockSong.textContent = i18n.playerMenuBlockSong || "Do not recommend this song";
    }
    if (playerMenuBlockArtist) {
      const tpl = i18n.playerMenuBlockArtist || "Do not recommend songs from {artist}";
      playerMenuBlockArtist.textContent = tpl.replace("{artist}", artist);
    }

    playerContextMenu.classList.remove("hidden");
    playerContextMenu.setAttribute("aria-hidden", "false");

    const rect = playerContextMenu.getBoundingClientRect();
    const maxLeft = Math.max(8, window.innerWidth - rect.width - 8);
    const maxTop = Math.max(8, window.innerHeight - rect.height - 8);
    const left = Math.max(8, Math.min(x, maxLeft));
    const top = Math.max(8, Math.min(y, maxTop));
    playerContextMenu.style.left = `${left}px`;
    playerContextMenu.style.top = `${top}px`;
  }

  function shareCurrentSongFromPlayer() {
    const song = currentSongOrNull();
    if (!song || !song.id || !canShareSong(song)) {
      return;
    }
    const detailHref = String(song.detail_url || `/songs/${encodeURIComponent(song.id)}`).trim();
    const shareUrl = new URL(detailHref, window.location.origin).toString();
    const shareTitle = [song.title || i18n.playerUntitled || "Untitled", song.artist || i18n.playerUnknown || "Unknown"]
      .map((part) => String(part || "").trim())
      .filter(Boolean)
      .join(" - ") || document.title || "PulseBeat";
    const payload = {
      url: shareUrl,
      title: shareTitle,
      text: shareTitle,
    };

    if (window.PulseBeatShare && typeof window.PulseBeatShare.open === "function") {
      window.PulseBeatShare.open(payload);
      return;
    }

    const fallbackTrigger = document.createElement("button");
    fallbackTrigger.type = "button";
    fallbackTrigger.className = "open-share-modal hidden";
    fallbackTrigger.setAttribute("data-share-url", payload.url);
    fallbackTrigger.setAttribute("data-share-title", payload.title);
    fallbackTrigger.setAttribute("data-share-text", payload.text);
    document.body.appendChild(fallbackTrigger);
    fallbackTrigger.click();
    fallbackTrigger.remove();
  }

  function canShareSong(song) {
    if (!song) return false;
    const visibility = String(song.visibility || "").trim().toLowerCase();
    return visibility === "public" || visibility === "unlisted";
  }

  function hideActionToast() {
    if (!playerActionToast) return;
    playerActionToast.classList.add("hidden");
    pendingUndoAction = null;
    clearTimeout(actionToastTimer);
  }

  async function runUndoAction() {
    if (!pendingUndoAction) return;
    const action = pendingUndoAction;
    pendingUndoAction = null;
    await sendRecommendationAction(action.action, action.song, action.artist, false);
    hideActionToast();
  }

  function showActionToast(message, undoAction) {
    if (!playerActionToast || !playerActionToastText) return;
    playerActionToastText.textContent = message || "";
    pendingUndoAction = undoAction || null;
    playerActionToast.classList.remove("hidden");

    clearTimeout(actionToastTimer);
    actionToastTimer = setTimeout(() => {
      hideActionToast();
    }, 10000);
  }

  function normalizeArtistName(value) {
    return String(value || "").trim().toLowerCase();
  }

  function removeFromLocalRecommendations(song, action, artistName) {
    if (!Array.isArray(window.PAGE_RECOMMENDED_SONGS)) return;

    if (action === "block_song" && song && song.id) {
      window.PAGE_RECOMMENDED_SONGS = window.PAGE_RECOMMENDED_SONGS.filter((item) => String(item.id) !== String(song.id));
      return;
    }

    if (action === "block_artist") {
      const artistNorm = normalizeArtistName(artistName || (song && song.artist));
      if (!artistNorm) return;
      window.PAGE_RECOMMENDED_SONGS = window.PAGE_RECOMMENDED_SONGS.filter((item) => normalizeArtistName(item.artist) !== artistNorm);
    }
  }

  async function sendRecommendationAction(action, song, artistName, withUndo = true) {
    if (!song || !song.id) return;
    if (!isAuthenticated) {
      showPlaylistToast(i18n.authRequired || "Login required.", "error");
      return;
    }

    const payload = { action, song_id: song.id };
    if (artistName) payload.artist = artistName;

    try {
      const res = await fetch("/songs/preferences/recommendations", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "X-Requested-With": "XMLHttpRequest",
          Accept: "application/json",
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      });
      const data = res.ok ? await res.json() : null;
      if (!res.ok || !data || !data.ok) {
        showPlaylistToast((data && data.message) || i18n.playerPlaylistError || "Error", "error");
        return;
      }

      if (withUndo) {
        let undoAction = null;
        if (action === "block_song") undoAction = { action: "unblock_song", song, artist: "" };
        if (action === "block_artist") undoAction = { action: "unblock_artist", song, artist: artistName || song.artist || "" };
        showActionToast(data.message || (i18n.playerMenuDone || "Done"), undoAction);
      }

      removeFromLocalRecommendations(song, action, artistName);
      hidePlayerContextMenu();
    } catch (_e) {
      showPlaylistToast(i18n.playerPlaylistError || "Error", "error");
    }
  }

  function setPlaylistModalOpen(opened) {
    if (opened && !requireAuthenticatedPlayerAction()) return;
    state.playlistModalOpen = !!opened;
    if (!playlistModal) return;
    if (opened) {
      playlistModal.classList.remove("hidden");
      playlistModal.setAttribute("aria-hidden", "false");
    } else {
      playlistModal.classList.add("hidden");
      playlistModal.setAttribute("aria-hidden", "true");
      if (playlistSuggestions) playlistSuggestions.innerHTML = "";
      if (playlistStatus) playlistStatus.textContent = "";
      if (playlistSearch) playlistSearch.value = "";
      if (playlistToast) playlistToast.classList.add("hidden");
      setCreatePlaylistModalOpen(false);
    }
  }

  function setCreatePlaylistModalOpen(opened) {
    if (!createPlaylistModal) return;
    creatingPlaylist = false;
    if (opened) {
      createPlaylistModal.classList.remove("hidden");
      createPlaylistModal.setAttribute("aria-hidden", "false");
      if (createPlaylistNameInput) {
        setTimeout(() => createPlaylistNameInput.focus(), 30);
      }
      return;
    }
    createPlaylistModal.classList.add("hidden");
    createPlaylistModal.setAttribute("aria-hidden", "true");
    if (createPlaylistNameInput) createPlaylistNameInput.value = "";
    if (createPlaylistConfirmBtn) createPlaylistConfirmBtn.disabled = false;
    if (createPlaylistCancelBtn) createPlaylistCancelBtn.disabled = false;
  }

  function closeRestrictedPlayerPanels() {
    state.playlistModalOpen = false;
    if (playlistModal) {
      playlistModal.classList.add("hidden");
      playlistModal.setAttribute("aria-hidden", "true");
    }
    if (playlistSuggestions) playlistSuggestions.innerHTML = "";
    if (playlistStatus) playlistStatus.textContent = "";
    if (playlistSearch) playlistSearch.value = "";
    if (playlistToast) playlistToast.classList.add("hidden");

    state.queueEditorOpen = false;
    if (queueEditorModal) {
      queueEditorModal.classList.add("hidden");
      queueEditorModal.setAttribute("aria-hidden", "true");
    }

    setCreatePlaylistModalOpen(false);
  }

  function requireAuthenticatedPlayerAction() {
    if (isAuthenticated) return true;
    closeRestrictedPlayerPanels();
    if (playlistStatus) playlistStatus.textContent = i18n.authRequired || "Please sign in to continue.";
    showPlaylistToast(i18n.authRequired || "Please sign in to continue.", "error");
    return false;
  }

  function setQueueEditorOpen(opened) {
    if (opened && !requireAuthenticatedPlayerAction()) return;
    state.queueEditorOpen = !!opened;
    if (!queueEditorModal) return;
    if (opened) {
      queueEditorModal.classList.remove("hidden");
      queueEditorModal.setAttribute("aria-hidden", "false");
      renderQueueEditor();
      return;
    }
    queueEditorModal.classList.add("hidden");
    queueEditorModal.setAttribute("aria-hidden", "true");
  }

  function moveQueueItem(fromIndex, toIndex) {
    if (!Array.isArray(state.queue) || !state.queue.length) return;
    if (fromIndex < 0 || fromIndex >= state.queue.length) return;
    if (toIndex < 0 || toIndex >= state.queue.length || fromIndex === toIndex) return;
    const nextQueue = state.queue.slice();
    const [item] = nextQueue.splice(fromIndex, 1);
    nextQueue.splice(toIndex, 0, item);
    state.queue = nextQueue;

    if (state.index === fromIndex) {
      state.index = toIndex;
    } else if (fromIndex < state.index && toIndex >= state.index) {
      state.index -= 1;
    } else if (fromIndex > state.index && toIndex <= state.index) {
      state.index += 1;
    }
    saveState();
    renderQueueEditor();
    showPlaylistToast(i18n.playerQueueMoved || "Queue reordered.", "success");
  }

  function removeQueueItem(index) {
    if (!Array.isArray(state.queue) || !state.queue.length) return;
    if (index < 0 || index >= state.queue.length) return;
    if (state.queue.length <= 1) return;

    state.queue.splice(index, 1);
    if (index < state.index) {
      state.index -= 1;
    } else if (index === state.index) {
      state.index = Math.max(0, Math.min(state.index, state.queue.length - 1));
      applySong(state.isPlaying).catch(() => {});
    }
    saveState();
    renderQueueEditor();
    showPlaylistToast(i18n.playerQueueRemoved || "Removed from queue.", "success");
  }

  function jumpToQueueIndex(index) {
    if (!Array.isArray(state.queue) || !state.queue.length) return;
    if (index < 0 || index >= state.queue.length) return;
    if (index === state.index) return;
    transitionWithCrossfade(() => {
      state.index = index;
      state.time = 0;
      return applySong(true, { manual: true });
    }).catch(() => {});
  }

  function renderQueueEditor() {
    if (!queueList || !queueEmpty || !queueInfo) return;
    queueList.innerHTML = "";
    const queue = Array.isArray(state.queue) ? state.queue : [];
    if (!queue.length) {
      queueEmpty.classList.remove("hidden");
      queueInfo.textContent = i18n.playerQueueEmpty || "Queue is empty.";
      return;
    }

    queueEmpty.classList.add("hidden");
    queueInfo.textContent = `${queue.length} - ${i18n.playerQueueNow || "Now playing"}: ${(queue[state.index] && queue[state.index].title) || i18n.playerNoSong || ""}`;

    queue.forEach((song, index) => {
      const li = document.createElement("li");
      li.dataset.index = String(index);
      li.draggable = true;
      if (song && song.is_available === false) li.classList.add("song-unavailable");

      const row = document.createElement("div");
      row.className = "queue-row";

      const meta = document.createElement("div");
      meta.className = "queue-row-meta";
      const title = document.createElement("strong");
      const unavailablePrefix = song && song.is_available === false ? "⛔ " : "";
      title.textContent = `${index === state.index ? "▶ " : ""}${unavailablePrefix}${song.title || i18n.playerUntitled || "Untitled"}`;
      const artist = document.createElement("p");
      artist.className = "muted small";
      artist.textContent = song && song.is_available === false
        ? `${song.artist || i18n.playerUnknown || "Unknown"} - ${i18n.songUnavailable || "Unavailable"}`
        : (song.artist || i18n.playerUnknown || "Unknown");
      meta.appendChild(title);
      meta.appendChild(artist);

      const actions = document.createElement("div");
      actions.className = "queue-row-actions";

      const playBtn = document.createElement("button");
      playBtn.type = "button";
      playBtn.className = "btn secondary";
      playBtn.dataset.action = "play";
      playBtn.dataset.index = String(index);
      playBtn.textContent = i18n.playerPlay || "Play";
      actions.appendChild(playBtn);

      const upBtn = document.createElement("button");
      upBtn.type = "button";
      upBtn.className = "btn secondary";
      upBtn.dataset.action = "up";
      upBtn.dataset.index = String(index);
      upBtn.textContent = "↑";
      upBtn.disabled = index === 0;
      actions.appendChild(upBtn);

      const downBtn = document.createElement("button");
      downBtn.type = "button";
      downBtn.className = "btn secondary";
      downBtn.dataset.action = "down";
      downBtn.dataset.index = String(index);
      downBtn.textContent = "↓";
      downBtn.disabled = index === queue.length - 1;
      actions.appendChild(downBtn);

      const removeBtn = document.createElement("button");
      removeBtn.type = "button";
      removeBtn.className = "btn-danger";
      removeBtn.dataset.action = "remove";
      removeBtn.dataset.index = String(index);
      removeBtn.textContent = "×";
      removeBtn.disabled = queue.length <= 1;
      actions.appendChild(removeBtn);

      row.appendChild(meta);
      row.appendChild(actions);
      li.appendChild(row);

      li.addEventListener("dragstart", (event) => {
        li.classList.add("dragging");
        event.dataTransfer.setData("text/plain", String(index));
        event.dataTransfer.effectAllowed = "move";
      });
      li.addEventListener("dragend", () => {
        li.classList.remove("dragging");
      });
      li.addEventListener("dragover", (event) => {
        event.preventDefault();
      });
      li.addEventListener("drop", (event) => {
        event.preventDefault();
        const from = Number(event.dataTransfer.getData("text/plain"));
        const to = Number(li.dataset.index || "-1");
        if (!Number.isInteger(from) || !Number.isInteger(to)) return;
        moveQueueItem(from, to);
      });

      queueList.appendChild(li);
    });
  }

  function currentSongOrNull() {
    const song = currentSong();
    return song && song.id ? song : null;
  }

  function renderPlaylistSuggestions(items) {
    if (!playlistSuggestions) return;
    playlistSuggestions.innerHTML = "";
    items.forEach((item) => {
      const row = document.createElement("button");
      row.type = "button";
      row.className = "autocomplete-item";
      row.textContent = `${item.name} (${item.visibility})`;
      row.addEventListener("click", () => addCurrentSongToPlaylist(item.id));
      playlistSuggestions.appendChild(row);
    });
  }

  async function fetchPlaylistSuggestions(q) {
    if (!playlistSuggestions) return;
    try {
      const url = `/playlists/suggest?q=${encodeURIComponent(q || "")}`;
      const res = await fetch(url, { credentials: "same-origin" });
      if (!res.ok) {
        renderPlaylistSuggestions([]);
        return;
      }
      const data = await res.json();
      const items = Array.isArray(data.items) ? data.items : [];
      renderPlaylistSuggestions(items);
    } catch (_e) {
      renderPlaylistSuggestions([]);
    }
  }

  async function addCurrentSongToPlaylist(playlistId) {
    if (!isAuthenticated) {
      showPlaylistToast(i18n.authRequired || "Login required.", "error");
      return;
    }
    const song = currentSongOrNull();
    if (!song) {
      if (playlistStatus) playlistStatus.textContent = i18n.playerNoSongToAdd || "No song to add.";
      showPlaylistToast(i18n.playerNoSongToAdd || "No song to add.", "error");
      return;
    }
    try {
      const res = await fetch("/playlists/quick-add", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ playlist_id: playlistId, song_id: song.id }),
      });
      const data = await res.json();
      if (!res.ok || !data.ok) {
        if (playlistStatus) playlistStatus.textContent = data.message || i18n.playerPlaylistError || "Error";
        showPlaylistToast(data.message || i18n.playerPlaylistError || "Error", "error");
        return;
      }
      if (playlistStatus) {
        playlistStatus.textContent = data.already_exists
          ? (i18n.playerPlaylistExists || data.message || "Already in playlist")
          : (i18n.playerPlaylistAdded || data.message || "Added");
      }
      showPlaylistToast(
        data.already_exists
          ? (i18n.playerPlaylistExists || data.message || "Already in playlist")
          : (i18n.playerPlaylistAdded || data.message || "Added"),
        data.already_exists ? "error" : "success"
      );
    } catch (_e) {
      if (playlistStatus) playlistStatus.textContent = i18n.playerPlaylistError || "Error";
      showPlaylistToast(i18n.playerPlaylistError || "Error", "error");
    }
  }

  async function createPlaylistWithCurrentSong(playlistName) {
    if (!isAuthenticated) {
      showPlaylistToast(i18n.authRequired || "Login required.", "error");
      return { ok: false };
    }
    const song = currentSongOrNull();
    if (!song) {
      if (playlistStatus) playlistStatus.textContent = i18n.playerNoSongToAdd || "No song to add.";
      showPlaylistToast(i18n.playerNoSongToAdd || "No song to add.", "error");
      return { ok: false };
    }

    const rawName = String(playlistName || "").trim();
    if (!rawName) {
      const msg = i18n.playerPlaylistNameRequired || "Playlist name is required.";
      if (playlistStatus) playlistStatus.textContent = msg;
      showPlaylistToast(msg, "error");
      return { ok: false };
    }

    try {
      const res = await fetch("/playlists/quick-create", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: rawName, song_id: song.id }),
      });
      const data = res.ok ? await res.json() : null;
      if (!res.ok || !data || !data.ok) {
        if (playlistStatus) playlistStatus.textContent = (data && data.message) || i18n.playerPlaylistError || "Error";
        showPlaylistToast((data && data.message) || i18n.playerPlaylistError || "Error", "error");
        return { ok: false };
      }

      if (playlistStatus) playlistStatus.textContent = data.message || i18n.playerPlaylistCreated || "Playlist created.";
      showPlaylistToast(data.message || i18n.playerPlaylistCreated || "Playlist created.", "success");
      fetchPlaylistSuggestions(playlistSearch ? playlistSearch.value.trim() : "");
      return { ok: true };
    } catch (_e) {
      if (playlistStatus) playlistStatus.textContent = i18n.playerPlaylistError || "Error";
      showPlaylistToast(i18n.playerPlaylistError || "Error", "error");
      return { ok: false };
    }
  }



  function drawBars(ctx, w, h, bars) {
    const count = bars.length || 48;
    const barWidth = w / count;
    for (let i = 0; i < count; i += 1) {
      const value = Math.max(0, Math.min(1, bars[i] || 0));
      const barHeight = Math.max(2, value * h);
      const x = i * barWidth;
      const y = h - barHeight;
      ctx.fillStyle = "rgba(255,122,24,0.9)";
      ctx.fillRect(x + 1, y, Math.max(1, barWidth - 2), barHeight);
    }
  }

  function fallbackWaveBars() {
    const src = cachedWaveBars.length ? cachedWaveBars : new Array(48).fill(0.18);
    const t = getPlaybackTimeSeconds();
    return src.map((v, i) => {
      const wiggle = Math.sin(t * 2.8 + i * 0.35) * 0.08;
      return Math.max(0.06, Math.min(0.98, v + wiggle));
    });
  }

  function formatTime(value) {
    const n = Number.isFinite(value) ? Math.max(0, Math.floor(value)) : 0;
    const m = Math.floor(n / 60);
    const s = n % 60;
    return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  }

  function modeLabel() {
    if (state.queueContext !== "playlist") return i18n.playerAutoMode;
    if (state.playMode === "shuffle") return i18n.playerModeShuffle;
    if (state.playMode === "repeat_one") return i18n.playerModeRepeatOne;
    return i18n.playerModeNormal;
  }

  function updateModeUI() {
    if (!modeBtn) return;
    const isPlaylist = state.queueContext === "playlist";
    modeBtn.classList.toggle("hidden", !isPlaylist);
    modeBtn.dataset.mode = state.playMode;
    modeBtn.setAttribute("aria-label", modeLabel());
    modeBtn.title = modeLabel();
  }

  function syncAudioOptionControls() {
    if (queueCrossfadeToggle) queueCrossfadeToggle.checked = !!state.crossfadeEnabled;
    if (queueNormalizeToggle) queueNormalizeToggle.checked = !!state.normalizeVolumeEnabled;
  }

  function saveState() {
    state.time = getPlaybackTimeSeconds();
    const persistedState = Object.assign({}, state, {
      // UI transient state must not survive page changes.
      playlistModalOpen: false,
      queueEditorOpen: false,
      activeEngine: "audio",
      manualStartSongId: "",
      manualRecoverySongId: "",
      unavailableSkipCounter: 0,
    });
    localStorage.setItem(STORAGE_KEY, JSON.stringify(persistedState));
  }

  function loadState() {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return;
    try {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed.queue)) {
        state = Object.assign(state, parsed);
      }
      if (!["normal", "shuffle", "repeat_one"].includes(state.playMode)) {
        state.playMode = "normal";
      }
      if (!["auto", "playlist"].includes(state.queueContext)) {
        state.queueContext = "auto";
      }
      if (!Array.isArray(state.shuffleHistory)) {
        state.shuffleHistory = [];
      }
      if (![1, 1.25, 1.5].includes(Number(state.playbackRate))) {
        state.playbackRate = 1;
      }
      state.viewMode = normalizeViewMode(state.viewMode);
      state.playlistModalOpen = false;
      state.queueEditorOpen = false;
      state.activeEngine = "audio";
      state.manualStartSongId = "";
      state.manualRecoverySongId = "";
      state.unavailableSkipCounter = 0;
      state.crossfadeEnabled = state.crossfadeEnabled !== false;
      state.normalizeVolumeEnabled = state.normalizeVolumeEnabled !== false;
      if (!Number.isFinite(Number(state.normalizationGain || 1))) {
        state.normalizationGain = 1;
      }
    } catch (_e) {
      localStorage.removeItem(STORAGE_KEY);
    }
  }

  function normalizeSongId(value) {
    return String(value || "").trim();
  }

  function clearManualPlaybackAssist() {
    if (!manualPlaybackAssistTimers.length) return;
    manualPlaybackAssistTimers.forEach((timerId) => {
      window.clearTimeout(timerId);
    });
    manualPlaybackAssistTimers = [];
  }

  function isSongActuallyPlaying(song) {
    if (!song) return false;
    if (isYouTubeSong(song)) {
      return !!state.isPlaying;
    }
    return !audio.paused;
  }

  function scheduleManualPlaybackAssist(songId) {
    const expectedId = normalizeSongId(songId);
    if (!expectedId) return;
    clearManualPlaybackAssist();
    const delays = [180, 700, 1400];
    delays.forEach((delay) => {
      const timerId = window.setTimeout(() => {
        const song = currentSong();
        if (!song || normalizeSongId(song.id) !== expectedId) return;
        if (isPlaybackBlocked(false)) return;
        if (isSongActuallyPlaying(song)) return;
        if (!isYouTubeSong(song) && audio.readyState < 2) return;
        togglePlayPause().catch(() => {});
      }, delay);
      manualPlaybackAssistTimers.push(timerId);
    });
  }

  function getUniqueQueue(items) {
    if (!Array.isArray(items) || !items.length) return [];
    const seen = new Set();
    const unique = [];
    items.forEach((item) => {
      if (!item) return;
      const id = normalizeSongId(item.id);
      if (!id || seen.has(id)) return;
      seen.add(id);
      unique.push(item);
    });
    return unique;
  }

  function sanitizeQueueState(preferredSongId = "") {
    const uniqueQueue = getUniqueQueue(state.queue);
    if (!uniqueQueue.length) {
      state.queue = [];
      state.index = 0;
      return;
    }
    const preferredId = normalizeSongId(preferredSongId);
    let nextIndex = Math.max(0, Math.min(Number(state.index) || 0, uniqueQueue.length - 1));
    if (preferredId) {
      const preferredIndex = uniqueQueue.findIndex((item) => normalizeSongId(item && item.id) === preferredId);
      if (preferredIndex >= 0) {
        nextIndex = preferredIndex;
      }
    }
    state.queue = uniqueQueue;
    state.index = nextIndex;
  }

  function currentSong() {
    return state.queue[state.index] || null;
  }

  function updatePlayerShellVisibility(song) {
    if (!playerShell) return;
    const shouldShow = Boolean(song && song.id);
    playerShell.classList.toggle("player-shell-hidden", !shouldShow);
    playerShell.setAttribute("aria-hidden", shouldShow ? "false" : "true");
    if (shouldShow && !playerShellVisible && playerShellAnimateOnNextReveal) {
      playerShell.classList.remove("player-shell-entering");
      void playerShell.offsetWidth;
      playerShell.classList.add("player-shell-entering");
      window.setTimeout(() => {
        if (playerShell) playerShell.classList.remove("player-shell-entering");
      }, 380);
      playerShellAnimateOnNextReveal = false;
    } else if (shouldShow && !playerShellVisible) {
      playerShell.classList.remove("player-shell-entering");
      playerShellAnimateOnNextReveal = false;
    } else if (!shouldShow) {
      playerShell.classList.remove("player-shell-entering");
      playerShellAnimateOnNextReveal = false;
    }
    playerShellVisible = shouldShow;
    syncPlayerOffset();
  }

  function updateMeta(song) {
    updatePlayerShellVisibility(song);
    titleEl.textContent = song ? song.title : i18n.playerNoSong;
    artistEl.textContent = song ? (song.artist || i18n.playerUnknown) : "-";
    playPauseBtn.dataset.state = state.isPlaying ? "playing" : "paused";
    playPauseBtn.setAttribute("aria-label", state.isPlaying ? i18n.playerPause : i18n.playerPlay);

    if (song && song.detail_url) {
      titleLinkEl.href = song.detail_url;
      titleLinkEl.classList.remove("disabled");
    } else {
      titleLinkEl.href = "#";
      titleLinkEl.classList.add("disabled");
    }

    if (song && song.id) {
      refreshPlayerVoteState(song);
    } else {
      resetPlayerVoteState();
    }

    if (playerShareBtn) {
      const allowShare = canShareSong(song);
      playerShareBtn.classList.toggle("hidden", !allowShare);
      playerShareBtn.setAttribute("aria-hidden", allowShare ? "false" : "true");
      playerShareBtn.tabIndex = allowShare ? 0 : -1;
    }

    updateModeUI();
    updateViewModeUI();
    updateMediaSession(song);
    loadLyricsForSong(song);
    renderQueueEditor();
    document.title = song ? `${song.title} - ${i18n.playerAlbum || "PulseBeat"}` : DEFAULT_PAGE_TITLE;
  }

  function updateMediaSessionPosition(currentSec, durationSec) {
    if (!("mediaSession" in navigator)) return;
    const duration = Math.max(0, Number(durationSec) || 0);
    if (!duration) return;
    const position = Math.max(0, Math.min(Number(currentSec) || 0, duration));
    const playbackRate = Number(state.playbackRate) || 1;
    try {
      navigator.mediaSession.setPositionState({
        duration,
        position,
        playbackRate,
      });
    } catch (_e) {
    }
  }

  function updateMediaSessionPlaybackState() {
    if (!("mediaSession" in navigator)) return;
    try {
      if (!currentSong()) {
        navigator.mediaSession.playbackState = "none";
      } else {
        navigator.mediaSession.playbackState = state.isPlaying ? "playing" : "paused";
      }
    } catch (_e) {
    }
  }

  function bindMediaSessionHandlers() {
    if (!("mediaSession" in navigator)) return;
    const mediaSession = navigator.mediaSession;
    const safeSet = (action, handler) => {
      try {
        mediaSession.setActionHandler(action, handler);
      } catch (_e) {
      }
    };
    const invokeNextTrack = () => {
      next(true).catch(() => {});
    };
    safeSet("play", () => {
      if (!state.isPlaying) {
        togglePlayPause();
      }
    });
    safeSet("pause", () => {
      if (state.isPlaying) {
        togglePlayPause();
      }
    });
    safeSet("previoustrack", invokePrevTrack);
    safeSet("nexttrack", invokeNextTrack);
    // Certains périphériques multimédias envoient seekbackward/seekforward
    // au lieu de previoustrack/nexttrack. On les mappe vers la navigation
    // de piste pour garder un comportement cohérent.
    safeSet("seekbackward", () => {
      invokePrevTrack();
    });
    safeSet("seekforward", () => {
      invokeNextTrack();
    });
    safeSet("seekto", (details) => {
      if (!details || typeof details.seekTime !== "number") return;
      const duration = getPlaybackDurationSeconds();
      if (!duration || !Number.isFinite(duration)) return;
      const target = Math.max(0, Math.min(Number(details.seekTime) || 0, duration));
      if (isYoutubeEngineActive()) {
        if (!ytPlayer || typeof ytPlayer.seekTo !== "function") return;
        try {
          ytPlayer.seekTo(target, true);
        } catch (_e) {
          return;
        }
      } else {
        if (!audio.duration || !Number.isFinite(audio.duration)) return;
        audio.currentTime = target;
      }
      refreshProgressUI(target, duration);
      saveState();
    });
  }

  function updateMediaSession(song) {
    if (!("mediaSession" in navigator)) return;
    bindMediaSessionHandlers();

    if (!song) {
      try {
        navigator.mediaSession.metadata = null;
      } catch (_e) {
      }
      updateMediaSessionPlaybackState();
      return;
    }

    try {
      navigator.mediaSession.metadata = new MediaMetadata({
        title: song.title || i18n.playerUntitled,
        artist: song.artist || i18n.playerUnknown,
        album: i18n.playerAlbum,
      });
    } catch (_e) {
    }
    updateMediaSessionPlaybackState();
    updateMediaSessionPosition(getPlaybackTimeSeconds(), getPlaybackDurationSeconds());
  }

  function initAudioGraph() {
    if (!waveform) return;
    if (audioCtx) return;
    try {
      audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      analyser = audioCtx.createAnalyser();
      analyser.fftSize = 256;
      gainNode = audioCtx.createGain();
      gainNode.gain.value = 1;
      sourceNode = audioCtx.createMediaElementSource(audio);
      sourceNode.connect(gainNode);
      gainNode.connect(analyser);
      analyser.connect(audioCtx.destination);
    } catch (_e) {
      audioCtx = null;
      analyser = null;
      gainNode = null;
      sourceNode = null;
    }
  }

  function stopYouTubePlayback() {
    clearYoutubeTimer();
    if (!ytPlayer) return;
    try {
      if (typeof ytPlayer.stopVideo === "function") {
        ytPlayer.stopVideo();
      }
    } catch (_e) {}
  }

  async function ensureYouTubePlayer() {
    if (!youtubeHost) return null;
    if (ytPlayer) return ytPlayer;
    try {
      await ensureYouTubeApiReady();
    } catch (_e) {
      return null;
    }
    if (!window.YT || !window.YT.Player) return null;
    ytPlayer = new window.YT.Player(youtubeHost, {
      height: "1",
      width: "1",
      videoId: "",
      playerVars: {
        autoplay: 0,
        controls: 0,
        rel: 0,
        modestbranding: 1,
        iv_load_policy: 3,
      },
      events: {
        onReady: () => {},
        onStateChange: (event) => {
          const song = currentSong();
          if (!song || !isYouTubeSong(song)) return;
          const YTState = (window.YT && window.YT.PlayerState) || {};
          if (event.data === YTState.PLAYING) {
            clearManualPlaybackAssist();
            state.isPlaying = true;
            state.activeEngine = "youtube";
            youtubeSkipLocked = false;
            bindMediaSessionHandlers();
            window.setTimeout(() => {
              bindMediaSessionHandlers();
            }, 180);
            window.setTimeout(() => {
              bindMediaSessionHandlers();
            }, 700);
            if (song && song.id) {
              const prefix = `${String(song.id)}:`;
              for (const key of Array.from(youtubeErrorAttempts.keys())) {
                if (key.startsWith(prefix)) {
                  youtubeErrorAttempts.delete(key);
                }
              }
            }
            clearPlayerError();
            updateMeta(song);
            startYoutubeTimer();
            if (state.startedSongId !== song.id) {
              sendProgress(song, false, true);
              state.startedSongId = song.id;
            }
            if (state.manualRecoverySongId && String(state.manualRecoverySongId) === String(song.id)) {
              setSongAvailability(song, true, "").catch(() => {});
              state.manualRecoverySongId = "";
            }
            state.unavailableSkipCounter = 0;
            saveState();
            return;
          }
          if (event.data === YTState.PAUSED) {
            state.isPlaying = false;
            updateMeta(song);
            sendProgress(song, false, false);
            saveState();
            return;
          }
          if (event.data === YTState.ENDED) {
            state.isPlaying = false;
            updateMeta(song);
            sendProgress(song, true, false);
            next(false).catch(() => {});
          }
        },
        onError: (event) => {
          const song = currentSong();
          const code = Number(event && event.data ? event.data : 0) || 0;
          const shouldDisable = code === 100;
          const retryable = !shouldDisable && [2, 5, 101, 150].includes(code);
          const songId = song && song.id ? String(song.id) : "";
          const retryKey = `${songId}:${code}`;
          const retries = youtubeErrorAttempts.get(retryKey) || 0;

          if (retryable && songId && retries < 1) {
            youtubeErrorAttempts.set(retryKey, retries + 1);
            const message = (i18n.playerYoutubeError || "YouTube error ({code}).").replace("{code}", String(code));
            showPlayerError(`${message} ${i18n.playerTryNext || ""}`.trim());
            showPlaylistToast(i18n.playerYoutubeRetry || "Playback issue detected, retrying once...", "error");
            window.setTimeout(() => {
              const current = currentSong();
              if (!current || String(current.id) !== songId || !isYouTubeSong(current)) return;
              applySong(true, { manual: true }).catch(() => {});
            }, 950);
            return;
          }

          if (songId) {
            youtubeErrorAttempts.delete(retryKey);
          }
          if (shouldDisable) {
            showPlayerError(404);
          } else {
            const message = (i18n.playerYoutubeError || "YouTube error ({code}).").replace("{code}", String(code));
            showPlayerError(`${message} ${(i18n.playerTryNext || "").trim()}`.trim());
          }
          state.isPlaying = false;
          updateMeta(song);
          if (song && shouldDisable) {
            setSongAvailability(song, false, `youtube_${code}`).catch(() => {});
          }
          if (state.queue.length > 1 && !youtubeSkipLocked) {
            youtubeSkipLocked = true;
            showPlaylistToast(i18n.playerUnavailableSkipped || "Song unavailable, automatically skipping to the next one.", "error");
            window.setTimeout(() => {
              next(false).catch(() => {});
              window.setTimeout(() => {
                youtubeSkipLocked = false;
              }, 850);
            }, 700);
          }
        },
      },
    });
    return ytPlayer;
  }

  function clearGainFadeTimer() {
    if (!gainFadeTimer) return;
    window.clearInterval(gainFadeTimer);
    gainFadeTimer = null;
  }

  function setMasterGain(targetValue, durationMs = 0) {
    const clampedTarget = Math.max(0, Math.min(2, Number(targetValue) || 1));
    if (!gainNode) {
      audio.volume = Math.max(0, Math.min(1, clampedTarget));
      return Promise.resolve();
    }
    clearGainFadeTimer();
    if (!durationMs || durationMs <= 0) {
      gainNode.gain.value = clampedTarget;
      return Promise.resolve();
    }
    const start = Number(gainNode.gain.value || 1);
    const delta = clampedTarget - start;
    const stepMs = 40;
    const totalSteps = Math.max(1, Math.ceil(durationMs / stepMs));
    let index = 0;
    return new Promise((resolve) => {
      gainFadeTimer = window.setInterval(() => {
        index += 1;
        const ratio = Math.min(1, index / totalSteps);
        gainNode.gain.value = start + (delta * ratio);
        if (ratio >= 1) {
          clearGainFadeTimer();
          resolve();
        }
      }, stepMs);
    });
  }

  function resetNormalizationProbe() {
    normalizationProbe = { samples: 0, sumRms: 0, locked: false };
  }

  function updateNormalizationGainFromProbe() {
    if (!state.normalizeVolumeEnabled || normalizationProbe.locked) return;
    if (!analyser || !gainNode || audio.paused) return;

    const bufferLength = analyser.fftSize;
    if (!bufferLength) return;
    const timeData = new Uint8Array(bufferLength);
    analyser.getByteTimeDomainData(timeData);

    let sumSquares = 0;
    for (let i = 0; i < timeData.length; i += 1) {
      const sample = (timeData[i] - 128) / 128;
      sumSquares += sample * sample;
    }
    const rms = Math.sqrt(sumSquares / timeData.length);
    if (!Number.isFinite(rms) || rms <= 0) return;

    normalizationProbe.samples += 1;
    normalizationProbe.sumRms += rms;

    if (normalizationProbe.samples >= 28 || (audio.currentTime || 0) > 12) {
      const avg = normalizationProbe.sumRms / Math.max(1, normalizationProbe.samples);
      const target = Math.max(0.72, Math.min(1.35, 0.12 / avg));
      state.normalizationGain = target;
      normalizationProbe.locked = true;
      const targetGain = state.crossfadeEnabled ? target : target;
      setMasterGain(targetGain, 220).catch(() => {});
      saveState();
    }
  }

  function drawWaveform() {
    if (!waveform) return;
    const ctx = waveform.getContext("2d");
    if (!ctx) return;
    const song = currentSongOrNull();
    const useSyntheticBars = !analyser || (song && isYouTubeSong(song) && state.activeEngine === "youtube");

    const w = waveform.clientWidth || waveform.width;
    const h = waveform.clientHeight || waveform.height;
    if (waveform.width !== w) waveform.width = w;
    if (waveform.height !== h) waveform.height = h;

    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = "rgba(255,255,255,0.08)";
    ctx.fillRect(0, 0, w, h);

    if (useSyntheticBars) {
      drawBars(ctx, w, h, fallbackWaveBars());
      waveformRaf = requestAnimationFrame(drawWaveform);
      return;
    }

    const bufferLength = analyser.frequencyBinCount;
    const dataArray = new Uint8Array(bufferLength);
    analyser.getByteFrequencyData(dataArray);

    const barCount = 48;
    const step = Math.max(1, Math.floor(bufferLength / barCount));
    const bars = [];
    for (let i = 0; i < barCount; i += 1) {
      bars.push((dataArray[i * step] || 0) / 255);
    }
    cachedWaveBars = bars;
    try {
      sessionStorage.setItem(WAVE_STORAGE_KEY, JSON.stringify(bars));
    } catch (_e) {}

    drawBars(ctx, w, h, bars);
    waveformRaf = requestAnimationFrame(drawWaveform);
  }

  function ensureWaveformLoop() {
    if (waveformRaf) return;
    drawWaveform();
  }

  async function applySong(autoplay, options = {}) {
    clearPlayerError();
    hidePlayerContextMenu();
    const song = currentSong();
    if (!song) {
      clearManualPlaybackAssist();
      stopYouTubePlayback();
      audio.removeAttribute("src");
      audio.load();
      state.activeEngine = "audio";
      state.isPlaying = false;
      updateMeta(null);
      saveState();
      clearLyricsUI();
      return;
    }

    if (autoplay && isPlaybackBlocked(true)) {
      clearManualPlaybackAssist();
      state.isPlaying = false;
      updateMeta(song);
      saveState();
      return;
    }

    await ensureSongPlaybackMeta(song);
    const manualStart = !!options.manual || (state.manualStartSongId && String(state.manualStartSongId) === String(song.id));
    if (manualStart) {
      state.manualStartSongId = "";
      if (autoplay) {
        scheduleManualPlaybackAssist(song.id);
      }
    }

    if (!isSongAvailable(song) && !manualStart) {
      clearManualPlaybackAssist();
      state.isPlaying = false;
      updateMeta(song);
      saveState();
      state.unavailableSkipCounter = (state.unavailableSkipCounter || 0) + 1;
      showPlayerError(404);
      showPlaylistToast(i18n.playerUnavailableSkipped || "Song unavailable, automatically skipping to the next one.", "error");
      if (state.queue.length > 1 && state.unavailableSkipCounter <= state.queue.length) {
        window.setTimeout(() => {
          next(false).catch(() => {});
        }, 120);
      } else {
        state.unavailableSkipCounter = 0;
      }
      return;
    }
    state.unavailableSkipCounter = 0;
    if (!isSongAvailable(song) && manualStart) {
      state.manualRecoverySongId = song.id;
    }

    if (isYouTubeSong(song)) {
      stopYouTubePlayback();
      audio.pause();
      audio.removeAttribute("src");
      audio.load();
      state.activeEngine = "youtube";
      state.startedSongId = null;
      updateMeta(song);
      refreshProgressUI(0, 0);

      const player = await ensureYouTubePlayer();
      const videoId = song.youtube_video_id || extractYouTubeVideoId(song.source_url || song.external_url || "");
      if (!player || !videoId) {
        clearManualPlaybackAssist();
        showPlayerError(404);
        state.isPlaying = false;
        updateMeta(song);
        saveState();
        return;
      }
      ytCurrentVideoId = videoId;
      song.youtube_video_id = videoId;

      const resumeAt = Number(song.resume_at || 0);
      try {
        if (autoplay) {
          player.loadVideoById({ videoId, startSeconds: resumeAt > 0 ? resumeAt : 0 });
        } else {
          player.cueVideoById({ videoId, startSeconds: resumeAt > 0 ? resumeAt : 0 });
          state.isPlaying = false;
          updateMeta(song);
        }
        if (typeof player.setPlaybackRate === "function") {
          try {
            player.setPlaybackRate(Number(state.playbackRate) || 1);
          } catch (_e) {}
        }
        startYoutubeTimer();
        saveState();
      } catch (_e) {
        clearManualPlaybackAssist();
        showPlayerError(404);
        state.isPlaying = false;
        updateMeta(song);
        saveState();
      }
      return;
    }

    state.activeEngine = "audio";
    stopYouTubePlayback();

    if (!song.url) {
      clearManualPlaybackAssist();
      audio.removeAttribute("src");
      audio.load();
      state.isPlaying = false;
      updateMeta(song);
      saveState();
      return;
    }

    if (song.__forceReload || audio.src !== song.url) {
      audio.src = song.url;
      audio.load();
      state.startedSongId = null;
      state.normalizationGain = 1;
      resetNormalizationProbe();
    }
    delete song.__forceReload;

    audio.playbackRate = Number(state.playbackRate) || 1;
    if (speedSelect) {
      speedSelect.value = String(audio.playbackRate);
    }

    updateMeta(song);

    const resumeAt = Number(song.resume_at || 0);
    audio.addEventListener("loadedmetadata", () => {
      if (resumeAt > 0 && resumeAt < (audio.duration || 0)) {
        audio.currentTime = resumeAt;
      }
    }, { once: true });

    if (autoplay) {
      initAudioGraph();
      if (audioCtx && audioCtx.state === "suspended") {
        audioCtx.resume().catch(() => {});
      }
      const baseTargetGain = state.normalizeVolumeEnabled ? Number(state.normalizationGain || 1) : 1;
      if (state.crossfadeEnabled) {
        setMasterGain(0, 0).catch(() => {});
      } else {
        setMasterGain(baseTargetGain, 0).catch(() => {});
      }
      audio.play().then(() => {
        clearManualPlaybackAssist();
        clearPlayerError();
        state.isPlaying = true;
        updateMeta(song);
        if (state.crossfadeEnabled) {
          setMasterGain(baseTargetGain, 420).catch(() => {});
        } else {
          setMasterGain(baseTargetGain, 0).catch(() => {});
        }
        if (state.startedSongId !== song.id) {
          sendProgress(song, false, true);
          state.startedSongId = song.id;
        }
        if (state.manualRecoverySongId && String(state.manualRecoverySongId) === String(song.id)) {
          setSongAvailability(song, true, "").catch(() => {});
          state.manualRecoverySongId = "";
        }
        saveState();
      }).catch((error) => {
        const errorName = String((error && error.name) || "");
        if (manualStart && (errorName === "NotAllowedError" || errorName === "AbortError")) {
          state.isPlaying = false;
          updateMeta(song);
          saveState();
          return;
        }
        clearManualPlaybackAssist();
        handleSongStreamError(song);
      });
    } else {
      clearManualPlaybackAssist();
      const targetGain = state.normalizeVolumeEnabled ? Number(state.normalizationGain || 1) : 1;
      setMasterGain(targetGain, 0).catch(() => {});
      state.isPlaying = false;
      updateMeta(song);
      saveState();
    }
  }

  function setQueue(queue, startIndex, context, manualStart = false) {
    if (!Array.isArray(queue) || queue.length === 0) return;
    const rawIndex = Math.max(0, Math.min(startIndex || 0, queue.length - 1));
    const preferredSongId = normalizeSongId(queue[rawIndex] && queue[rawIndex].id);
    state.queue = getUniqueQueue(queue);
    if (!state.queue.length) return;
    let nextIndex = state.queue.findIndex((item) => normalizeSongId(item && item.id) === preferredSongId);
    if (nextIndex < 0) {
      nextIndex = Math.max(0, Math.min(rawIndex, state.queue.length - 1));
    }
    state.index = nextIndex;
    state.time = 0;
    state.shuffleHistory = [];
    state.queueContext = context === "playlist" ? "playlist" : "auto";
    state.manualStartSongId = manualStart && state.queue[state.index] ? String(state.queue[state.index].id || "") : "";
    playerShellAnimateOnNextReveal = Boolean(manualStart && !playerShellVisible);
    applySong(true, { manual: manualStart }).catch(() => {});
    saveState();
  }

  function pickRandomIndex(exceptIndex) {
    if (state.queue.length <= 1) return 0;
    let idx = exceptIndex;
    while (idx === exceptIndex) {
      idx = Math.floor(Math.random() * state.queue.length);
    }
    return idx;
  }

  function pickPageRecommendations(excludeIds, limit = 50) {
    const pool = Array.isArray(window.PAGE_RECOMMENDED_SONGS) ? window.PAGE_RECOMMENDED_SONGS : [];
    return getUniqueQueue(
      pool.filter((item) => !excludeIds.has(normalizeSongId(item && item.id)))
    ).slice(0, Math.max(1, Number(limit) || 50));
  }

  async function fetchRecommendations(currentSongId, excludeIds, limit = 50) {
    const safeLimit = Math.max(1, Math.min(Number(limit) || 50, 50));
    const localItems = pickPageRecommendations(excludeIds, safeLimit);
    const params = new URLSearchParams({
      song_id: String(currentSongId || ""),
      limit: String(safeLimit),
    });
    if (excludeIds && excludeIds.size) {
      params.set("exclude_ids", Array.from(excludeIds).join(","));
    }

    try {
      const res = await fetch(`/songs/recommendations?${params.toString()}`, { credentials: "same-origin" });
      if (!res.ok) {
        return localItems;
      }
      const data = await res.json();
      const remoteItems = Array.isArray(data.items) ? data.items : [];
      return getUniqueQueue(
        [...localItems, ...remoteItems].filter((item) => !excludeIds.has(normalizeSongId(item && item.id)))
      ).slice(0, safeLimit);
    } catch (_e) {
      return localItems;
    }
  }

  function buildPageNavigationPool() {
    const sources = [];
    if (Array.isArray(window.PAGE_SONG_OBJECTS) && window.PAGE_SONG_OBJECTS.length) {
      sources.push(...window.PAGE_SONG_OBJECTS);
    }
    if (Array.isArray(window.PAGE_RECOMMENDED_SONGS) && window.PAGE_RECOMMENDED_SONGS.length) {
      sources.push(...window.PAGE_RECOMMENDED_SONGS);
    }
    return getUniqueQueue(sources);
  }

  function hydrateQueueFromPageIfNeeded() {
    if (state.queue.length > 1) return false;
    const current = currentSong();
    const currentId = normalizeSongId(current && current.id);
    if (!currentId) return false;

    const pool = buildPageNavigationPool();
    if (pool.length <= 1) return false;
    const index = pool.findIndex((item) => String((item && item.id) || "") === currentId);
    if (index < 0) return false;

    state.queue = pool;
    state.index = index;
    state.shuffleHistory = [];
    if (!["playlist", "auto"].includes(state.queueContext)) {
      state.queueContext = "auto";
    }
    return true;
  }

  function stopPlaybackBecauseQueueIsExhausted(message) {
    clearManualPlaybackAssist();
    audio.pause();
    if (isYoutubeEngineActive() && ytPlayer && typeof ytPlayer.pauseVideo === "function") {
      try {
        ytPlayer.pauseVideo();
      } catch (_e) {}
    }
    state.isPlaying = false;
    updateMeta(currentSong());
    showPlayerError(message || i18n.playerNoNewContent || "No new content is available right now. Playback has been stopped.");
    saveState();
  }

  async function rebuildAutoQueue(previousQueue, current) {
    const previousIds = new Set(
      (Array.isArray(previousQueue) ? previousQueue : [])
        .map((item) => normalizeSongId(item && item.id))
        .filter(Boolean)
    );
    if (current && current.id) {
      previousIds.add(normalizeSongId(current.id));
    }

    const localPool = buildPageNavigationPool().filter((item) => !previousIds.has(normalizeSongId(item && item.id)));
    const remotePool = current && current.id ? await fetchRecommendations(current.id, previousIds, 50) : [];
    const nextQueue = getUniqueQueue([...localPool, ...remotePool]).filter(
      (item) => !previousIds.has(normalizeSongId(item && item.id))
    );

    if (!nextQueue.length) {
      return false;
    }

    state.queue = nextQueue;
    state.index = 0;
    state.time = 0;
    state.shuffleHistory = [];
    state.queueContext = "auto";
    state.manualStartSongId = "";
    sanitizeQueueState(nextQueue[0] && nextQueue[0].id ? nextQueue[0].id : "");
    return true;
  }

  async function transitionWithCrossfade(transitionFn) {
    if (typeof transitionFn !== "function") return;
    if (!state.crossfadeEnabled || isYoutubeEngineActive() || audio.paused) {
      await transitionFn();
      return;
    }
    if (state.isTransitioning) return;
    state.isTransitioning = true;
    try {
      await setMasterGain(0, 320);
      await transitionFn();
    } finally {
      state.isTransitioning = false;
    }
  }

  async function navigateToIndex(targetIndex, options = {}) {
    const manual = options.manual !== false;
    const useCrossfade = !!options.useCrossfade;
    if (!state.queue.length) return;
    const bounded = Math.max(0, Math.min(Number(targetIndex) || 0, state.queue.length - 1));
    const transition = () => {
      state.index = bounded;
      state.time = 0;
      return applySong(true, { manual: !!manual });
    };
    if (useCrossfade) {
      await transitionWithCrossfade(transition);
      return;
    }
    await transition();
  }

  async function next(manual) {
    if (state.playlistModalOpen && playlistModal && playlistModal.classList.contains("hidden")) {
      state.playlistModalOpen = false;
    }
    if (state.playlistModalOpen) return;
    if (!state.queue.length) return;
    hydrateQueueFromPageIfNeeded();

    if (state.queueContext === "playlist") {
      if (state.playMode === "repeat_one" && !manual) {
        restartCurrentSongFromStart();
        if (!state.isPlaying) {
          togglePlayPause();
        }
        return;
      }

      let nextIndex = state.index;
      if (state.playMode === "shuffle") {
        state.shuffleHistory.push(state.index);
        nextIndex = pickRandomIndex(state.index);
      } else {
        nextIndex = (state.index + 1) % state.queue.length;
      }
      await navigateToIndex(nextIndex, { manual: !!manual, useCrossfade: !manual });
      return;
    }

    if (state.index < state.queue.length - 1) {
      await navigateToIndex(state.index + 1, { manual: !!manual, useCrossfade: !manual });
      return;
    }

    const current = currentSong();
    const exhaustedQueue = Array.isArray(state.queue) ? state.queue.slice() : [];
    const rebuilt = await rebuildAutoQueue(exhaustedQueue, current);
    if (rebuilt) {
      await navigateToIndex(0, { manual: !!manual, useCrossfade: !manual });
      return;
    }
    stopPlaybackBecauseQueueIsExhausted();
  }

  function resolvePreviousIndex() {
    if (!state.queue.length) return -1;

    if (state.queueContext === "playlist") {
      if (state.playMode === "shuffle" && state.shuffleHistory.length) {
        return state.shuffleHistory[state.shuffleHistory.length - 1];
      }
      if (state.playMode === "shuffle") {
        return pickRandomIndex(state.index);
      }
      return (state.index - 1 + state.queue.length) % state.queue.length;
    }

    if (state.index > 0) {
      return state.index - 1;
    }

    // En contexte "auto", on autorise aussi le bouclage si la file a > 1 élément
    // afin que previous ne paraisse pas bloqué sur le premier élément.
    if (state.queue.length > 1) {
      return state.queue.length - 1;
    }

    return -1;
  }

  async function prev() {
    if (state.playlistModalOpen && playlistModal && playlistModal.classList.contains("hidden")) {
      state.playlistModalOpen = false;
    }
    if (state.playlistModalOpen) return;
    if (!state.queue.length) return;
    hydrateQueueFromPageIfNeeded();

    const prevIndexCandidate = resolvePreviousIndex();
    const hasPreviousTrack = prevIndexCandidate >= 0 && prevIndexCandidate !== state.index;

    if (getPlaybackTimeSeconds() >= 5 || !hasPreviousTrack) {
      restartCurrentSongFromStart();
      return;
    }

    let prevIndex = prevIndexCandidate;
    if (state.queueContext === "playlist" && state.playMode === "shuffle" && state.shuffleHistory.length) {
      // En mode shuffle, on consomme bien l'historique au moment du déplacement.
      prevIndex = state.shuffleHistory.pop();
    }

    await navigateToIndex(prevIndex, { manual: true, useCrossfade: false });
  }

  function invokePrevTrack() {
    const now = Date.now();
    if (now - lastPrevActionAt < 240) {
      return;
    }
    lastPrevActionAt = now;
    prev().catch(() => {});
  }

  function cycleMode() {
    if (state.queueContext !== "playlist") return;
    if (state.playMode === "normal") {
      state.playMode = "shuffle";
      state.shuffleHistory = [];
    } else if (state.playMode === "shuffle") {
      state.playMode = "repeat_one";
    } else {
      state.playMode = "normal";
    }
    updateModeUI();
    saveState();
  }

  async function togglePlayPause() {
    if (isPlaybackBlocked(true)) {
      return;
    }

    const song = currentSong();
    if (!song) {
      if (window.PAGE_SONG_OBJECTS && window.PAGE_SONG_OBJECTS.length) {
        setQueue(window.PAGE_SONG_OBJECTS, 0, "auto", true);
      }
      return;
    }

    if (isYouTubeSong(song)) {
      const player = await ensureYouTubePlayer();
      if (!player) {
        showPlayerError(404);
        return;
      }
      if (state.isPlaying) {
        if (typeof player.pauseVideo === "function") {
          player.pauseVideo();
        }
        return;
      }
      if (isYoutubeEngineActive()) {
        if (typeof player.playVideo === "function") {
          player.playVideo();
        }
        return;
      }
      await applySong(true, { manual: true });
      return;
    }

    if (audio.paused) {
      initAudioGraph();
      if (audioCtx && audioCtx.state === "suspended") {
        audioCtx.resume().catch(() => {});
      }
      audio.play().then(() => {
        clearPlayerError();
        state.isPlaying = true;
        updateMeta(song);
        if (state.startedSongId !== song.id) {
          sendProgress(song, false, true);
          state.startedSongId = song.id;
        }
        saveState();
      }).catch(() => {
        handleSongStreamError(song);
      });
    } else {
      audio.pause();
      state.isPlaying = false;
      updateMeta(song);
      sendProgress(song, false, false);
      saveState();
    }
  }

  function parseSong(raw) {
    try {
      return JSON.parse(raw);
    } catch (_e) {
      return null;
    }
  }

  function sendProgress(song, completed, started) {
    if (!song || !song.id) return;
    const position = getPlaybackTimeSeconds();
    const duration = getPlaybackDurationSeconds();
    const body = {
      position,
      duration,
      completed: !!completed,
      started: !!started,
    };
    fetch(`/songs/${encodeURIComponent(song.id)}/progress`, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      keepalive: true,
    }).catch(() => {});
  }

  function handleGlobalContextMenuDismiss(target) {
    if (!playerContextMenu || playerContextMenu.classList.contains("hidden")) return;
    if (!target || typeof target.closest !== "function") {
      hidePlayerContextMenu();
      return;
    }
    if (target.closest("#player-context-menu") || target.closest("#player-more-btn")) {
      return;
    }
    hidePlayerContextMenu();
  }

  window.addEventListener("pointerdown", (event) => {
    handleGlobalContextMenuDismiss(event.target);
  }, true);

  document.addEventListener("click", (event) => {
    handleGlobalContextMenuDismiss(event.target);

    const playBtn = event.target.closest(".play-one");
    if (playBtn) {
      const raw = playBtn.getAttribute("data-song");
      if (!raw) return;
      const song = parseSong(raw);
      if (!song) return;
      const context = playBtn.getAttribute("data-context") === "playlist" ? "playlist" : "auto";
      const clickedId = String((song || {}).id || "");
      const pageQueue = Array.isArray(window.PAGE_SONG_OBJECTS) ? window.PAGE_SONG_OBJECTS : [];
      const recQueue = Array.isArray(window.PAGE_RECOMMENDED_SONGS) ? window.PAGE_RECOMMENDED_SONGS : [];

      let queue = [];
      let index = -1;

      if (pageQueue.length) {
        index = pageQueue.findIndex((s) => String((s || {}).id || "") === clickedId);
        if (index >= 0) {
          queue = pageQueue;
        }
      }

      if (!queue.length && recQueue.length) {
        index = recQueue.findIndex((s) => String((s || {}).id || "") === clickedId);
        if (index >= 0) {
          queue = recQueue;
        }
      }

      if (!queue.length) {
        queue = [song];
        index = 0;
      }

      setQueue(queue, index >= 0 ? index : 0, context, true);
      return;
    }

    const queueAll = event.target.closest(".queue-all");
    if (queueAll && window.PAGE_SONG_OBJECTS && window.PAGE_SONG_OBJECTS.length) {
      const context = queueAll.getAttribute("data-context") === "playlist" ? "playlist" : "auto";
      setQueue(window.PAGE_SONG_OBJECTS, 0, context, false);
    }
  });

  if (titleLinkEl) {
    titleLinkEl.addEventListener("click", (event) => {
      const song = currentSong();
      if (!song || !song.detail_url) {
        event.preventDefault();
        return;
      }

      const hasModifier = event.metaKey || event.ctrlKey || event.shiftKey || event.altKey;
      if (state.viewMode !== "fullscreen" || hasModifier || event.button !== 0) {
        return;
      }

      event.preventDefault();
      const targetHref = song.detail_url;
      setViewMode("normal", true);
      window.setTimeout(() => {
        window.location.assign(targetHref);
      }, 220);
    });
  }

  playPauseBtn.addEventListener("click", togglePlayPause);

  if (likeBtn) {
    likeBtn.addEventListener("click", () => voteCurrentSong(1));
  }
  if (dislikeBtn) {
    dislikeBtn.addEventListener("click", () => voteCurrentSong(-1));
  }

  if (playerMoreBtn) {
    playerMoreBtn.addEventListener("click", (event) => {
      if (!isAuthenticated) return;
      event.preventDefault();
      const song = currentSongOrNull();
      if (!song) return;
      const rect = playerMoreBtn.getBoundingClientRect();
      showPlayerContextMenu(rect.right - 220, rect.bottom + 8);
    });
  }

  if (playerShareBtn) {
    playerShareBtn.addEventListener("click", () => {
      if (!isAuthenticated) return;
      shareCurrentSongFromPlayer();
    });
  }

  if (playerMenuBlockSong) {
    playerMenuBlockSong.addEventListener("click", () => {
      const song = currentSongOrNull();
      if (!song) return;
      sendRecommendationAction("block_song", song, "", true);
    });
  }

  if (playerMenuBlockArtist) {
    playerMenuBlockArtist.addEventListener("click", () => {
      const song = currentSongOrNull();
      if (!song) return;
      sendRecommendationAction("block_artist", song, song.artist || "", true);
    });
  }

  if (playerActionToastUndo) {
    playerActionToastUndo.addEventListener("click", (event) => {
      event.preventDefault();
      runUndoAction();
    });
  }

  if (playerShell) {
    playerShell.addEventListener("contextmenu", (event) => {
      if (!isAuthenticated || !playerContextMenu) return;
      if (!event.target.closest(".song-meta")) return;
      const song = currentSongOrNull();
      if (!song) return;
      event.preventDefault();
      showPlayerContextMenu(event.clientX, event.clientY);
    });
  }

  if (addToPlaylistBtn) {
    addToPlaylistBtn.addEventListener("click", () => {
      const song = currentSongOrNull();
      if (!song) {
        if (playlistStatus) playlistStatus.textContent = i18n.playerNoSongToAdd || "No song to add.";
        showPlaylistToast(i18n.playerNoSongToAdd || "No song to add.", "error");
        setPlaylistModalOpen(true);
        return;
      }
      setPlaylistModalOpen(true);
      fetchPlaylistSuggestions("");
      if (playlistSearch) setTimeout(() => playlistSearch.focus(), 30);
    });
  }
  if (playlistModalClose) playlistModalClose.addEventListener("click", () => setPlaylistModalOpen(false));
  if (playlistModal) {
    playlistModal.addEventListener("click", (event) => {
      if (event.target === playlistModal) setPlaylistModalOpen(false);
    });
  }
  if (queueEditorBtn) {
    queueEditorBtn.addEventListener("click", () => {
      setQueueEditorOpen(true);
    });
  }
  if (queueEditorClose) {
    queueEditorClose.addEventListener("click", () => {
      setQueueEditorOpen(false);
    });
  }
  if (queueEditorModal) {
    queueEditorModal.addEventListener("click", (event) => {
      if (event.target === queueEditorModal) setQueueEditorOpen(false);
    });
  }
  if (queueList) {
    queueList.addEventListener("click", (event) => {
      const btn = event.target.closest("button[data-action]");
      if (!btn) return;
      const action = btn.getAttribute("data-action") || "";
      const index = Number(btn.getAttribute("data-index") || "-1");
      if (!Number.isInteger(index) || index < 0) return;
      if (action === "play") {
        jumpToQueueIndex(index);
      } else if (action === "up") {
        moveQueueItem(index, index - 1);
      } else if (action === "down") {
        moveQueueItem(index, index + 1);
      } else if (action === "remove") {
        removeQueueItem(index);
      }
    });
  }
  if (queueClearBtn) {
    queueClearBtn.addEventListener("click", () => {
      const song = currentSongOrNull();
      if (!song) return;
      state.queue = [song];
      state.index = 0;
      saveState();
      renderQueueEditor();
    });
  }
  if (queueCrossfadeToggle) {
    queueCrossfadeToggle.addEventListener("change", () => {
      state.crossfadeEnabled = !!queueCrossfadeToggle.checked;
      saveState();
    });
  }
  if (queueNormalizeToggle) {
    queueNormalizeToggle.addEventListener("change", () => {
      state.normalizeVolumeEnabled = !!queueNormalizeToggle.checked;
      if (!state.normalizeVolumeEnabled) {
        state.normalizationGain = 1;
      } else {
        resetNormalizationProbe();
      }
      const targetGain = state.normalizeVolumeEnabled ? Number(state.normalizationGain || 1) : 1;
      setMasterGain(targetGain, 160).catch(() => {});
      saveState();
    });
  }
  if (playlistSearch) {
    let timer = null;
    playlistSearch.addEventListener("input", () => {
      clearTimeout(timer);
      timer = setTimeout(() => fetchPlaylistSuggestions(playlistSearch.value.trim()), 120);
    });
  }

  if (openCreatePlaylistBtn) {
    openCreatePlaylistBtn.addEventListener("click", () => {
      setCreatePlaylistModalOpen(true);
    });
  }

  if (createPlaylistConfirmBtn) {
    createPlaylistConfirmBtn.addEventListener("click", async () => {
      if (creatingPlaylist) return;
      creatingPlaylist = true;
      createPlaylistConfirmBtn.disabled = true;
      if (createPlaylistCancelBtn) createPlaylistCancelBtn.disabled = true;
      const result = await createPlaylistWithCurrentSong(createPlaylistNameInput ? createPlaylistNameInput.value : "");
      creatingPlaylist = false;
      createPlaylistConfirmBtn.disabled = false;
      if (createPlaylistCancelBtn) createPlaylistCancelBtn.disabled = false;
      if (result && result.ok) {
        setCreatePlaylistModalOpen(false);
      }
    });
  }

  if (createPlaylistCancelBtn) {
    createPlaylistCancelBtn.addEventListener("click", () => {
      if (creatingPlaylist) return;
      setCreatePlaylistModalOpen(false);
    });
  }

  if (createPlaylistModal) {
    createPlaylistModal.addEventListener("click", (event) => {
      if (event.target === createPlaylistModal && !creatingPlaylist) {
        setCreatePlaylistModalOpen(false);
      }
    });
  }

  if (createPlaylistNameInput) {
    createPlaylistNameInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        if (createPlaylistConfirmBtn) {
          createPlaylistConfirmBtn.click();
        }
      }
    });
  }
  nextBtn.addEventListener("click", () => next(true).catch(() => {}));
  prevBtn.addEventListener("click", invokePrevTrack);
  if (modeBtn) modeBtn.addEventListener("click", cycleMode);
  if (playerViewBtn) playerViewBtn.addEventListener("click", cycleViewMode);

  if (mobilePlayerMediaQuery) {
    const onPlayerViewportChange = () => syncViewModeToViewport();
    if (typeof mobilePlayerMediaQuery.addEventListener === "function") {
      mobilePlayerMediaQuery.addEventListener("change", onPlayerViewportChange);
    } else if (typeof mobilePlayerMediaQuery.addListener === "function") {
      mobilePlayerMediaQuery.addListener(onPlayerViewportChange);
    }
  } else {
    window.addEventListener("resize", syncViewModeToViewport);
  }

  window.addEventListener("resize", syncPlayerOffset);

  audio.addEventListener("canplay", () => {
    if (isYoutubeEngineActive()) return;
    clearPlayerError();
  });

  audio.addEventListener("error", () => {
    if (isYoutubeEngineActive()) return;
    handleSongStreamError(currentSong());
  });

  audio.addEventListener("stalled", () => {
    if (isYoutubeEngineActive()) return;
    if (!audio.paused) handleSongStreamError(currentSong());
  });

  audio.addEventListener("ended", () => {
    if (isYoutubeEngineActive()) return;
    const song = currentSong();
    if (song) sendProgress(song, true, false);
    next(false).catch(() => {});
  });

  audio.addEventListener("timeupdate", () => {
    if (isYoutubeEngineActive()) return;
    if (audio.duration && Number.isFinite(audio.duration)) {
      seek.value = Math.floor((audio.currentTime / audio.duration) * 1000);
      if (currentTimeEl) currentTimeEl.textContent = formatTime(audio.currentTime);
      if (remainingTimeEl) remainingTimeEl.textContent = `-${formatTime(audio.duration - audio.currentTime)}`;
      renderLyricsAt(getPlaybackTimeSeconds());
      updateNormalizationGainFromProbe();
    } else {
      seek.value = 0;
      if (currentTimeEl) currentTimeEl.textContent = "00:00";
      if (remainingTimeEl) remainingTimeEl.textContent = "-00:00";
    }
  });

  seek.addEventListener("input", () => {
    const ratio = Math.max(0, Math.min(1, Number(seek.value) / 1000));
    if (isYoutubeEngineActive()) {
      const duration = getPlaybackDurationSeconds();
      if (!duration || !Number.isFinite(duration) || !ytPlayer || typeof ytPlayer.seekTo !== "function") return;
      const target = ratio * duration;
      try {
        ytPlayer.seekTo(target, true);
      } catch (_e) {
        return;
      }
      refreshProgressUI(target, duration);
      saveState();
      return;
    }
    if (!audio.duration || !Number.isFinite(audio.duration)) return;
    audio.currentTime = ratio * audio.duration;
    saveState();
  });

  if (speedSelect) {
    speedSelect.addEventListener("change", () => {
      const value = Number(speedSelect.value);
      if (![1, 1.25, 1.5].includes(value)) return;
      state.playbackRate = value;
      if (isYoutubeEngineActive() && ytPlayer && typeof ytPlayer.setPlaybackRate === "function") {
        try {
          ytPlayer.setPlaybackRate(value);
        } catch (_e) {}
      } else {
        audio.playbackRate = value;
      }
      saveState();
    });
  }

  function persistPlaybackSnapshot(sendServerProgress = false) {
    const song = currentSong();
    const currentTime = getPlaybackTimeSeconds();
    state.time = currentTime;
    if (song) {
      song.resume_at = currentTime;
      if (sendServerProgress) {
        sendProgress(song, false, false);
      }
    }
    saveState();
  }

  function isInternalNavigationAnchor(anchor) {
    if (!anchor) return false;
    const href = String(anchor.getAttribute("href") || "").trim();
    if (!href || href.startsWith("#") || href.startsWith("javascript:")) return false;
    try {
      const resolved = new URL(anchor.href, window.location.href);
      return resolved.origin === window.location.origin;
    } catch (_e) {
      return href.startsWith("/");
    }
  }

  window.addEventListener("beforeunload", () => {
    persistPlaybackSnapshot(true);
  });

  window.addEventListener("pagehide", () => {
    persistPlaybackSnapshot(true);
  });

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") {
      persistPlaybackSnapshot(true);
    }
  });

  document.addEventListener(
    "click",
    (event) => {
      const anchor = event.target && event.target.closest ? event.target.closest("a[href]") : null;
      if (!anchor) return;
      if (!isInternalNavigationAnchor(anchor)) return;
      persistPlaybackSnapshot(true);
    },
    true,
  );

  document.addEventListener(
    "submit",
    () => {
      persistPlaybackSnapshot(true);
    },
    true,
  );

  bindMediaSessionHandlers();
  initPlayerTouchGestures();

  window.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      if (createPlaylistModal && !createPlaylistModal.classList.contains("hidden")) {
        if (!creatingPlaylist) setCreatePlaylistModalOpen(false);
        return;
      }
      if (state.queueEditorOpen) {
        setQueueEditorOpen(false);
        return;
      }
      if (state.playlistModalOpen) {
        setPlaylistModalOpen(false);
        return;
      }
      hidePlayerContextMenu();
      hideActionToast();
      return;
    }
    if (event.key === "MediaPlayPause") {
      event.preventDefault();
      togglePlayPause();
    } else if (event.key === "MediaTrackNext") {
      event.preventDefault();
      next(true).catch(() => {});
    } else if (event.key === "MediaTrackPrevious") {
      event.preventDefault();
      invokePrevTrack();
    }
  });

  async function initializePlayerState() {
    loadState();
    sanitizeQueueState();
    ensureWaveformLoop();

    if (state.queue.length) {
      const wasPlayingBeforePageChange = !!state.isPlaying;
      const song = currentSong();
      if (song && Number(state.time || 0) > 0) {
        song.resume_at = Number(state.time || 0);
      }
      await applySong(false);
      audio.playbackRate = Number(state.playbackRate) || 1;
      if (speedSelect) speedSelect.value = String(audio.playbackRate);

      if (wasPlayingBeforePageChange && !isPlaybackBlocked(true)) {
        if (isYoutubeEngineActive()) {
          state.isPlaying = true;
          const player = await ensureYouTubePlayer();
          if (player && typeof player.playVideo === "function") {
            try {
              player.playVideo();
            } catch (_e) {
              state.isPlaying = false;
            }
          } else {
            state.isPlaying = false;
          }
        } else {
          try {
            await audio.play();
            state.isPlaying = true;
          } catch (_e) {
            state.isPlaying = false;
          }
        }
      } else if (wasPlayingBeforePageChange) {
        state.isPlaying = false;
      }
      updateMeta(song);
      saveState();
    } else {
      updateMeta(null);
    }
    updateModeUI();
    updateViewModeUI();
    syncAudioOptionControls();
    renderQueueEditor();
    syncViewModeToViewport();
  }

  initTabGuard();

  initializePlayerState().catch(() => {
    updateMeta(currentSong());
    updateModeUI();
    updateViewModeUI();
    syncAudioOptionControls();
    renderQueueEditor();
    syncViewModeToViewport();
  });
})();
