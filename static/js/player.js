(function () {
  const STORAGE_KEY = "music_player_state_v1";
  const i18n = window.I18N || {
    playerNoSong: "Aucune musique",
    playerUnknown: "Inconnu",
    playerUntitled: "Sans titre",
    playerPlay: "Lecture",
    playerPause: "Pause",
    playerModeNormal: "Lecture normale",
    playerModeShuffle: "Lecture aléatoire",
    playerModeRepeatOne: "Répéter 1 chanson",
    playerAlbum: "PulseBeat",
  };

  const audio = document.getElementById("global-audio");
  const titleEl = document.getElementById("player-title");
  const artistEl = document.getElementById("player-artist");
  const playPauseBtn = document.getElementById("play-pause-btn");
  const prevBtn = document.getElementById("prev-btn");
  const nextBtn = document.getElementById("next-btn");
  const modeBtn = document.getElementById("play-mode-btn");
  const seek = document.getElementById("seek-range");

  if (!audio) return;

  let state = {
    queue: [],
    index: 0,
    isPlaying: false,
    time: 0,
    playMode: "normal",
    shuffleHistory: [],
  };

  function modeLabel() {
    if (state.playMode === "shuffle") return i18n.playerModeShuffle;
    if (state.playMode === "repeat_one") return i18n.playerModeRepeatOne;
    return i18n.playerModeNormal;
  }

  function updateModeUI() {
    if (!modeBtn) return;
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
      if (!Array.isArray(state.shuffleHistory)) {
        state.shuffleHistory = [];
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
    updateModeUI();
    updateMediaSession(song);
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
    }

    updateMeta(song);

    if (autoplay) {
      audio.play().then(() => {
        state.isPlaying = true;
        updateMeta(song);
        saveState();
      }).catch(() => {
        state.isPlaying = false;
        updateMeta(song);
        saveState();
      });
    }
  }

  function setQueue(queue, startIndex) {
    if (!Array.isArray(queue) || queue.length === 0) return;
    state.queue = queue;
    state.index = Math.max(0, Math.min(startIndex || 0, queue.length - 1));
    state.time = 0;
    state.shuffleHistory = [];
    applySong(true);
  }

  function pickRandomIndex(exceptIndex) {
    if (state.queue.length <= 1) return 0;
    let idx = exceptIndex;
    while (idx === exceptIndex) {
      idx = Math.floor(Math.random() * state.queue.length);
    }
    return idx;
  }

  function next(manual) {
    if (!state.queue.length) return;

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
  }

  function prev() {
    if (!state.queue.length) return;

    if (state.playMode === "shuffle" && state.shuffleHistory.length) {
      state.index = state.shuffleHistory.pop();
    } else if (state.playMode === "shuffle") {
      state.index = pickRandomIndex(state.index);
    } else {
      state.index = (state.index - 1 + state.queue.length) % state.queue.length;
    }

    state.time = 0;
    applySong(true);
  }

  function cycleMode() {
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
        setQueue(window.PAGE_SONG_OBJECTS, 0);
      }
      return;
    }

    if (audio.paused) {
      audio.play().then(() => {
        state.isPlaying = true;
        updateMeta(song);
        saveState();
      }).catch(() => {
        state.isPlaying = false;
        updateMeta(song);
      });
    } else {
      audio.pause();
      state.isPlaying = false;
      updateMeta(song);
      saveState();
    }
  }

  document.addEventListener("click", (event) => {
    const playBtn = event.target.closest(".play-one");
    if (playBtn) {
      const raw = playBtn.getAttribute("data-song");
      if (!raw) return;
      const song = JSON.parse(raw);
      const queue = window.PAGE_SONG_OBJECTS && window.PAGE_SONG_OBJECTS.length
        ? window.PAGE_SONG_OBJECTS
        : [song];
      const index = queue.findIndex((s) => s.id === song.id);
      setQueue(queue, index >= 0 ? index : 0);
      return;
    }

    const queueAll = event.target.closest(".queue-all");
    if (queueAll && window.PAGE_SONG_OBJECTS && window.PAGE_SONG_OBJECTS.length) {
      setQueue(window.PAGE_SONG_OBJECTS, 0);
    }
  });

  playPauseBtn.addEventListener("click", togglePlayPause);
  nextBtn.addEventListener("click", () => next(true));
  prevBtn.addEventListener("click", prev);
  if (modeBtn) modeBtn.addEventListener("click", cycleMode);

  audio.addEventListener("ended", () => next(false));

  audio.addEventListener("timeupdate", () => {
    if (audio.duration && Number.isFinite(audio.duration)) {
      seek.value = Math.floor((audio.currentTime / audio.duration) * 100);
    }
  });

  seek.addEventListener("input", () => {
    if (!audio.duration || !Number.isFinite(audio.duration)) return;
    audio.currentTime = (seek.value / 100) * audio.duration;
    saveState();
  });

  window.addEventListener("beforeunload", saveState);

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
  if (state.queue.length) {
    const song = currentSong();
    applySong(false);
    if (song) {
      audio.currentTime = state.time || 0;
    }
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
