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
    playerAlbum: "PulseBeat",
  };

  const audio = document.getElementById("global-audio");
  const titleEl = document.getElementById("player-title");
  const titleLinkEl = document.getElementById("player-title-link");
  const artistEl = document.getElementById("player-artist");
  const playPauseBtn = document.getElementById("play-pause-btn");
  const prevBtn = document.getElementById("prev-btn");
  const nextBtn = document.getElementById("next-btn");
  const modeBtn = document.getElementById("play-mode-btn");
  const addToPlaylistBtn = document.getElementById("add-to-playlist-btn");
  const seek = document.getElementById("seek-range");
  const playlistModal = document.getElementById("player-playlist-modal");
  const playlistModalClose = document.getElementById("player-playlist-close");
  const playlistSearch = document.getElementById("player-playlist-search");
  const playlistSuggestions = document.getElementById("player-playlist-suggestions");
  const playlistStatus = document.getElementById("player-playlist-status");
  const playlistToast = document.getElementById("player-playlist-toast");
  const speedSelect = document.getElementById("speed-select");
  const currentTimeEl = document.getElementById("time-current");
  const remainingTimeEl = document.getElementById("time-remaining");
  const waveform = document.getElementById("waveform");

  if (!audio) return;

  let audioCtx = null;
  let analyser = null;
  let sourceNode = null;
  let waveformRaf = 0;
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
  };





  let toastTimer = null;

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

  function setPlaylistModalOpen(opened) {
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
    }
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
    const t = audio.currentTime || 0;
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

  function saveState() {
    state.time = audio.currentTime || 0;
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
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
    } catch (_e) {
      localStorage.removeItem(STORAGE_KEY);
    }
  }

  function currentSong() {
    return state.queue[state.index] || null;
  }

  function updateMeta(song) {
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

    updateModeUI();
    updateMediaSession(song);
    document.title = song ? `${song.title} - ${i18n.playerAlbum || "PulseBeat"}` : DEFAULT_PAGE_TITLE;
  }

  function updateMediaSession(song) {
    if (!("mediaSession" in navigator)) return;

    if (!song) {
      navigator.mediaSession.metadata = null;
      return;
    }

    navigator.mediaSession.metadata = new MediaMetadata({
      title: song.title || i18n.playerUntitled,
      artist: song.artist || i18n.playerUnknown,
      album: i18n.playerAlbum,
    });
  }

  function initAudioGraph() {
    if (!waveform) return;
    if (audioCtx) return;
    try {
      audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      analyser = audioCtx.createAnalyser();
      analyser.fftSize = 256;
      sourceNode = audioCtx.createMediaElementSource(audio);
      sourceNode.connect(analyser);
      analyser.connect(audioCtx.destination);
    } catch (_e) {
      audioCtx = null;
      analyser = null;
      sourceNode = null;
    }
  }

  function drawWaveform() {
    if (!waveform) return;
    const ctx = waveform.getContext("2d");
    if (!ctx) return;

    const w = waveform.clientWidth || waveform.width;
    const h = waveform.clientHeight || waveform.height;
    if (waveform.width !== w) waveform.width = w;
    if (waveform.height !== h) waveform.height = h;

    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = "rgba(255,255,255,0.08)";
    ctx.fillRect(0, 0, w, h);

    if (!analyser) {
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

  function applySong(autoplay) {
    const song = currentSong();
    if (!song || !song.url) {
      audio.removeAttribute("src");
      audio.load();
      state.isPlaying = false;
      updateMeta(null);
      saveState();
      return;
    }

    if (audio.src !== song.url) {
      audio.src = song.url;
      audio.load();
      state.startedSongId = null;
    }

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
      audio.play().then(() => {
        state.isPlaying = true;
        updateMeta(song);
        if (state.startedSongId !== song.id) {
          sendProgress(song, false, true);
          state.startedSongId = song.id;
        }
        saveState();
      }).catch(() => {
        state.isPlaying = false;
        updateMeta(song);
        saveState();
      });
    }
  }

  function setQueue(queue, startIndex, context) {
    if (!Array.isArray(queue) || queue.length === 0) return;
    state.queue = queue;
    state.index = Math.max(0, Math.min(startIndex || 0, queue.length - 1));
    state.time = 0;
    state.shuffleHistory = [];
    state.queueContext = context === "playlist" ? "playlist" : "auto";
    applySong(true);
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

  function pickPageRecommendation(excludeIds) {
    const pool = Array.isArray(window.PAGE_RECOMMENDED_SONGS) ? window.PAGE_RECOMMENDED_SONGS : [];
    return pool.find((item) => !excludeIds.has(item.id)) || null;
  }

  async function fetchRecommendation(currentSongId, excludeIds) {
    const local = pickPageRecommendation(excludeIds);
    if (local) return local;

    const url = `/songs/recommendations?song_id=${encodeURIComponent(currentSongId)}&limit=20`;
    try {
      const res = await fetch(url, { credentials: "same-origin" });
      if (!res.ok) return null;
      const data = await res.json();
      const items = Array.isArray(data.items) ? data.items : [];
      return items.find((item) => !excludeIds.has(item.id)) || null;
    } catch (_e) {
      return null;
    }
  }

  async function next(manual) {
    if (state.playlistModalOpen) return;
    if (!state.queue.length) return;

    if (state.queueContext === "playlist") {
      if (state.playMode === "repeat_one" && !manual) {
        audio.currentTime = 0;
        audio.play().catch(() => {});
        return;
      }

      if (state.playMode === "shuffle") {
        state.shuffleHistory.push(state.index);
        state.index = pickRandomIndex(state.index);
      } else {
        state.index = (state.index + 1) % state.queue.length;
      }

      state.time = 0;
      applySong(true);
      return;
    }

    if (state.index < state.queue.length - 1) {
      state.index += 1;
      state.time = 0;
      applySong(true);
      return;
    }

    const current = currentSong();
    const excludeIds = new Set(state.queue.map((s) => s.id));
    if (current) {
      const rec = await fetchRecommendation(current.id, excludeIds);
      if (rec) {
        state.queue.push(rec);
        state.index = state.queue.length - 1;
        state.time = 0;
        applySong(true);
      }
    }
  }

  function prev() {
    if (state.playlistModalOpen) return;
    if (!state.queue.length) return;

    if (state.queueContext === "playlist") {
      if (state.playMode === "shuffle" && state.shuffleHistory.length) {
        state.index = state.shuffleHistory.pop();
      } else if (state.playMode === "shuffle") {
        state.index = pickRandomIndex(state.index);
      } else {
        state.index = (state.index - 1 + state.queue.length) % state.queue.length;
      }
    } else {
      if (state.index > 0) {
        state.index -= 1;
      } else {
        audio.currentTime = 0;
      }
    }

    state.time = 0;
    applySong(true);
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

  function togglePlayPause() {
    const song = currentSong();
    if (!song) {
      if (window.PAGE_SONG_OBJECTS && window.PAGE_SONG_OBJECTS.length) {
        setQueue(window.PAGE_SONG_OBJECTS, 0, "auto");
      }
      return;
    }

    if (audio.paused) {
      initAudioGraph();
      if (audioCtx && audioCtx.state === "suspended") {
        audioCtx.resume().catch(() => {});
      }
      audio.play().then(() => {
        state.isPlaying = true;
        updateMeta(song);
        if (state.startedSongId !== song.id) {
          sendProgress(song, false, true);
          state.startedSongId = song.id;
        }
        saveState();
      }).catch(() => {
        state.isPlaying = false;
        updateMeta(song);
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
    const body = {
      position: audio.currentTime || 0,
      duration: audio.duration || 0,
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

  document.addEventListener("click", (event) => {
    const playBtn = event.target.closest(".play-one");
    if (playBtn) {
      const raw = playBtn.getAttribute("data-song");
      if (!raw) return;
      const song = parseSong(raw);
      if (!song) return;
      const context = playBtn.getAttribute("data-context") === "playlist" ? "playlist" : "auto";
      const queue = window.PAGE_SONG_OBJECTS && window.PAGE_SONG_OBJECTS.length
        ? window.PAGE_SONG_OBJECTS
        : [song];
      const index = queue.findIndex((s) => s.id === song.id);
      setQueue(queue, index >= 0 ? index : 0, context);
      return;
    }

    const queueAll = event.target.closest(".queue-all");
    if (queueAll && window.PAGE_SONG_OBJECTS && window.PAGE_SONG_OBJECTS.length) {
      const context = queueAll.getAttribute("data-context") === "playlist" ? "playlist" : "auto";
      setQueue(window.PAGE_SONG_OBJECTS, 0, context);
    }
  });

  if (titleLinkEl) {
    titleLinkEl.addEventListener("click", (event) => {
      if (!currentSong() || !currentSong().detail_url) {
        event.preventDefault();
      }
    });
  }

  playPauseBtn.addEventListener("click", togglePlayPause);
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
  if (playlistSearch) {
    let timer = null;
    playlistSearch.addEventListener("input", () => {
      clearTimeout(timer);
      timer = setTimeout(() => fetchPlaylistSuggestions(playlistSearch.value.trim()), 120);
    });
  }
  nextBtn.addEventListener("click", () => next(true));
  prevBtn.addEventListener("click", prev);
  if (modeBtn) modeBtn.addEventListener("click", cycleMode);

  audio.addEventListener("ended", () => {
    const song = currentSong();
    if (song) sendProgress(song, true, false);
    next(false);
  });

  audio.addEventListener("timeupdate", () => {
    if (audio.duration && Number.isFinite(audio.duration)) {
      seek.value = Math.floor((audio.currentTime / audio.duration) * 1000);
      if (currentTimeEl) currentTimeEl.textContent = formatTime(audio.currentTime);
      if (remainingTimeEl) remainingTimeEl.textContent = `-${formatTime(audio.duration - audio.currentTime)}`;
    } else {
      seek.value = 0;
      if (currentTimeEl) currentTimeEl.textContent = "00:00";
      if (remainingTimeEl) remainingTimeEl.textContent = "-00:00";
    }
  });

  seek.addEventListener("input", () => {
    if (!audio.duration || !Number.isFinite(audio.duration)) return;
    audio.currentTime = (Number(seek.value) / 1000) * audio.duration;
    saveState();
  });

  if (speedSelect) {
    speedSelect.addEventListener("change", () => {
      const value = Number(speedSelect.value);
      if (![1, 1.25, 1.5].includes(value)) return;
      state.playbackRate = value;
      audio.playbackRate = value;
      saveState();
    });
  }

  window.addEventListener("beforeunload", () => {
    const song = currentSong();
    if (song) sendProgress(song, false, false);
    saveState();
  });

  if ("mediaSession" in navigator) {
    navigator.mediaSession.setActionHandler("play", () => {
      if (audio.paused) {
        togglePlayPause();
      }
    });
    navigator.mediaSession.setActionHandler("pause", () => {
      if (!audio.paused) {
        togglePlayPause();
      }
    });
    navigator.mediaSession.setActionHandler("previoustrack", prev);
    navigator.mediaSession.setActionHandler("nexttrack", () => next(true));
  }

  window.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && state.playlistModalOpen) {
      setPlaylistModalOpen(false);
      return;
    }
    if (event.key === "MediaPlayPause") {
      event.preventDefault();
      togglePlayPause();
    } else if (event.key === "MediaTrackNext") {
      event.preventDefault();
      next(true);
    } else if (event.key === "MediaTrackPrevious") {
      event.preventDefault();
      prev();
    }
  });

  loadState();
  ensureWaveformLoop();

  if (state.queue.length) {
    const song = currentSong();
    applySong(false);
    if (song) {
      audio.currentTime = state.time || 0;
    }
    audio.playbackRate = Number(state.playbackRate) || 1;
    if (speedSelect) speedSelect.value = String(audio.playbackRate);
    if (state.isPlaying) {
      audio.play().catch(() => {
        state.isPlaying = false;
        updateMeta(song);
      });
    }
    updateMeta(song);
  } else {
    updateMeta(null);
  }
  updateModeUI();
})();
