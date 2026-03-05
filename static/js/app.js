(function () {
  const i18n = window.I18N || {};

  const DISPOSABLE_EMAIL_DOMAINS = new Set([
    "10minutemail.com", "10minutemail.net", "guerrillamail.com", "mailinator.com",
    "temp-mail.org", "tempmail.dev", "tempmailo.com", "yopmail.com",
    "dispostable.com", "sharklasers.com", "getnada.com", "trashmail.com"
  ]);
  const KNOWN_EMAIL_PROVIDER_DOMAINS = new Set([
    "gmail.com", "googlemail.com",
    "outlook.com", "hotmail.com", "live.com", "msn.com",
    "icloud.com", "me.com", "mac.com",
    "yahoo.com", "yahoo.ca", "yahoo.fr", "ymail.com",
    "aol.com",
    "proton.me", "protonmail.com",
    "mail.com", "gmx.com", "gmx.net",
    "zoho.com", "yandex.com", "yandex.ru",
    "qq.com"
  ]);

  function isDisposableEmail(email) {
    const value = (email || "").trim().toLowerCase();
    const at = value.lastIndexOf("@");
    if (at <= 0 || at === value.length - 1) return true;
    const domain = value.slice(at + 1);
    if (!domain || !domain.includes(".")) return true;

    if (DISPOSABLE_EMAIL_DOMAINS.has(domain)) return true;
    for (const d of DISPOSABLE_EMAIL_DOMAINS) {
      if (domain.endsWith(`.${d}`)) return true;
    }

    if (KNOWN_EMAIL_PROVIDER_DOMAINS.has(domain)) return false;

    const disposableMarkers = ["temp", "trash", "10min", "minute", "mailinator", "guerrilla", "disposable", "throwaway"];
    if (disposableMarkers.some((m) => domain.includes(m))) return true;

    return true;
  }

  const menuBtn = document.getElementById("menu-toggle");
  const nav = document.getElementById("main-nav");

  if (menuBtn && nav) {
    menuBtn.addEventListener("click", () => {
      const isOpen = nav.classList.toggle("open");
      menuBtn.setAttribute("aria-expanded", isOpen ? "true" : "false");
    });
  }

  const visibilitySelect = document.getElementById("visibility-select");
  const sharedWrap = document.getElementById("shared-with-wrap");
  if (visibilitySelect && sharedWrap) {
    const updateShared = () => {
      const isPrivate = visibilitySelect.value === "private";
      sharedWrap.classList.toggle("hidden", !isPrivate);
    };
    visibilitySelect.addEventListener("change", updateShared);
    updateShared();
  }

  const confirmModal = document.getElementById("confirm-modal");
  const confirmYes = document.getElementById("modal-confirm");
  const confirmNo = document.getElementById("modal-cancel");
  let pendingForm = null;

  function hideModal(modal) {
    if (!modal) return;
    modal.classList.add("hidden");
    modal.setAttribute("aria-hidden", "true");
  }

  function showModal(modal) {
    if (!modal) return;
    modal.classList.remove("hidden");
    modal.setAttribute("aria-hidden", "false");
  }


  function showClientNotice(message, category = "info") {
    if (!message) return;
    let host = document.querySelector(".flash-list");
    if (!host) {
      const main = document.querySelector("main.page-container") || document.body;
      host = document.createElement("div");
      host.className = "flash-list";
      main.prepend(host);
    }
    const node = document.createElement("div");
    node.className = `flash ${category}`;
    node.textContent = message;
    host.appendChild(node);
    window.setTimeout(() => {
      node.remove();
      if (host && !host.children.length && !host.classList.contains("server-flash-list")) {
        host.remove();
      }
    }, 5000);
  }

  document.addEventListener("submit", (event) => {
    const form = event.target.closest(".delete-song-form");
    if (!form || !confirmModal) return;
    event.preventDefault();
    pendingForm = form;
    showModal(confirmModal);
  });

  if (confirmYes) {
    confirmYes.addEventListener("click", () => {
      if (pendingForm) {
        const form = pendingForm;
        pendingForm = null;
        hideModal(confirmModal);
        form.submit();
      }
    });
  }
  if (confirmNo) confirmNo.addEventListener("click", () => hideModal(confirmModal));

  const reportModal = document.getElementById("report-modal");
  const tempEmailModal = document.getElementById("temp-email-modal");
  const tempEmailProceed = document.getElementById("temp-email-proceed");
  const tempEmailCancel = document.getElementById("temp-email-cancel");
  const reportTitle = document.getElementById("report-modal-title");
  const reportForm = document.getElementById("report-modal-form");
  const reportCancel = document.getElementById("report-modal-cancel");
  const reportReason = document.getElementById("report-modal-reason");

  document.addEventListener("click", (event) => {
    const btn = event.target.closest(".open-report-modal");
    if (!btn || !reportModal || !reportForm) return;
    reportForm.action = btn.getAttribute("data-report-action") || "#";
    reportTitle.textContent = btn.getAttribute("data-report-title") || "Report";
    reportReason.value = "";
    showModal(reportModal);
    setTimeout(() => reportReason.focus(), 30);
  });
  if (reportCancel) reportCancel.addEventListener("click", () => hideModal(reportModal));

  const userPickerModal = document.getElementById("user-picker-modal");
  const userPickerTitle = document.getElementById("user-picker-title");
  const userSearchInput = document.getElementById("user-picker-search");
  const userSuggestions = document.getElementById("user-picker-suggestions");
  const userSelected = document.getElementById("user-picker-selected");
  const userPickerApply = document.getElementById("user-picker-apply");
  const userPickerCancel = document.getElementById("user-picker-cancel");

  let pickerTargetInputsId = "";
  let pickerTargetListId = "";
  let pickerInputName = "";
  let pickerSelected = new Map();
  let pickerItems = [];
  let pickerIndex = -1;
  let pickerDebounce = null;

  function renderPickerSelected() {
    if (!userSelected) return;
    userSelected.innerHTML = "";
    pickerSelected.forEach((item) => {
      const pill = document.createElement("button");
      pill.type = "button";
      pill.className = "selected-user-pill";
      pill.textContent = `${item.username} (${item.email}) x`;
      pill.addEventListener("click", () => {
        pickerSelected.delete(item.id);
        renderPickerSelected();
      });
      userSelected.appendChild(pill);
    });
  }

  function commitPickerToTarget() {
    const inputWrap = document.getElementById(pickerTargetInputsId);
    const listWrap = document.getElementById(pickerTargetListId);
    if (!inputWrap) return;
    inputWrap.innerHTML = "";
    if (listWrap) listWrap.innerHTML = "";
    pickerSelected.forEach((item) => {
      const hidden = document.createElement("input");
      hidden.type = "hidden";
      hidden.name = pickerInputName;
      hidden.value = item.id;
      inputWrap.appendChild(hidden);

      if (listWrap) {
        const pill = document.createElement("span");
        pill.className = "selected-user-pill";
        pill.textContent = `${item.username} (${item.email})`;
        listWrap.appendChild(pill);
      }
    });
  }

  function loadPickerFromTarget() {
    pickerSelected = new Map();
    const inputWrap = document.getElementById(pickerTargetInputsId);
    const listWrap = document.getElementById(pickerTargetListId);
    if (inputWrap) {
      const ids = Array.from(inputWrap.querySelectorAll(`input[name="${pickerInputName}"]`)).map((el) => el.value);
      const listPills = listWrap ? Array.from(listWrap.querySelectorAll(".selected-user-pill")) : [];
      ids.forEach((id, index) => {
        const label = listPills[index] ? listPills[index].textContent : id;
        const match = /^(.*)\s\((.*)\)$/.exec(label || "");
        const username = match ? match[1] : label;
        const email = match ? match[2] : "";
        pickerSelected.set(id, { id, username, email });
      });
    }
    renderPickerSelected();
  }

  function renderPickerSuggestions() {
    if (!userSuggestions) return;
    userSuggestions.innerHTML = "";
    pickerItems.forEach((item, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `autocomplete-item${index === pickerIndex ? " active" : ""}`;
      button.textContent = `${item.username} (${item.email})`;
      button.addEventListener("click", () => {
        pickerSelected.set(item.id, item);
        renderPickerSelected();
        userSearchInput.value = "";
        pickerItems = [];
        pickerIndex = -1;
        renderPickerSuggestions();
        userSearchInput.focus();
      });
      userSuggestions.appendChild(button);
    });
  }

  function fetchUsersSuggest() {
    const q = userSearchInput.value.trim();
    if (!q) {
      pickerItems = [];
      pickerIndex = -1;
      renderPickerSuggestions();
      return;
    }
    const url = `${userSearchInput.getAttribute("data-autocomplete-url")}?q=${encodeURIComponent(q)}`;
    fetch(url, { credentials: "same-origin" })
      .then((res) => (res.ok ? res.json() : { items: [] }))
      .then((data) => {
        const rows = Array.isArray(data.items) ? data.items : [];
        pickerItems = rows.filter((r) => !pickerSelected.has(r.id));
        pickerIndex = pickerItems.length ? 0 : -1;
        renderPickerSuggestions();
      })
      .catch(() => {
        pickerItems = [];
        pickerIndex = -1;
        renderPickerSuggestions();
      });
  }

  document.addEventListener("click", (event) => {
    const btn = event.target.closest(".open-user-picker");
    if (!btn || !userPickerModal) return;
    pickerTargetInputsId = btn.getAttribute("data-target-inputs") || "";
    pickerTargetListId = btn.getAttribute("data-target-list") || "";
    pickerInputName = btn.getAttribute("data-input-name") || "shared_with";
    userPickerTitle.textContent = btn.getAttribute("data-picker-title") || "Users";
    if (userSearchInput) userSearchInput.value = "";
    pickerItems = [];
    pickerIndex = -1;
    loadPickerFromTarget();
    renderPickerSuggestions();
    showModal(userPickerModal);
    setTimeout(() => userSearchInput && userSearchInput.focus(), 30);
  });

  if (userSearchInput) {
    userSearchInput.addEventListener("input", () => {
      clearTimeout(pickerDebounce);
      pickerDebounce = setTimeout(fetchUsersSuggest, 120);
    });

    userSearchInput.addEventListener("keydown", (event) => {
      if (!pickerItems.length) return;
      if (event.key === "ArrowDown") {
        event.preventDefault();
        pickerIndex = Math.min(pickerIndex + 1, pickerItems.length - 1);
        renderPickerSuggestions();
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        pickerIndex = Math.max(pickerIndex - 1, 0);
        renderPickerSuggestions();
      } else if (event.key === "Enter") {
        event.preventDefault();
        if (pickerIndex >= 0 && pickerItems[pickerIndex]) {
          const item = pickerItems[pickerIndex];
          pickerSelected.set(item.id, item);
          renderPickerSelected();
          userSearchInput.value = "";
          pickerItems = [];
          pickerIndex = -1;
          renderPickerSuggestions();
        }
      }
    });
  }

  if (userPickerApply) {
    userPickerApply.addEventListener("click", () => {
      commitPickerToTarget();
      hideModal(userPickerModal);
    });
  }
  if (userPickerCancel) userPickerCancel.addEventListener("click", () => hideModal(userPickerModal));

  function decodeTextFrame(frameBytes) {
    if (!frameBytes || !frameBytes.length) return "";
    const encoding = frameBytes[0];
    const body = frameBytes.slice(1);
    try {
      if (encoding === 0 || encoding === 3) {
        return new TextDecoder(encoding === 0 ? "latin1" : "utf-8").decode(body).replace(/\u0000/g, "").trim();
      }
      if (encoding === 1 || encoding === 2) {
        return new TextDecoder("utf-16").decode(body).replace(/\u0000/g, "").trim();
      }
    } catch (_e) {
      return "";
    }
    return "";
  }

  function decodeUsltFrame(payload) {
    if (!payload || payload.length < 5) return "";
    const enc = payload[0];
    let idx = 4;

    if (enc === 0 || enc === 3) {
      while (idx < payload.length && payload[idx] !== 0) idx += 1;
      idx += 1;
      const body = payload.slice(idx);
      try {
        return new TextDecoder(enc === 0 ? "latin1" : "utf-8").decode(body).replace(/\u0000/g, "").trim();
      } catch (_e) {
        return "";
      }
    }

    while (idx + 1 < payload.length) {
      if (payload[idx] === 0 && payload[idx + 1] === 0) {
        idx += 2;
        break;
      }
      idx += 2;
    }
    try {
      return new TextDecoder("utf-16").decode(payload.slice(idx)).replace(/\u0000/g, "").trim();
    } catch (_e) {
      return "";
    }
  }

  function readSynchsafeInt(b1, b2, b3, b4) {
    return ((b1 & 0x7f) << 21) | ((b2 & 0x7f) << 14) | ((b3 & 0x7f) << 7) | (b4 & 0x7f);
  }

  function readFrameSize(versionMajor, bytes, offset) {
    if (versionMajor === 4) {
      return readSynchsafeInt(bytes[offset], bytes[offset + 1], bytes[offset + 2], bytes[offset + 3]);
    }
    return (bytes[offset] << 24) | (bytes[offset + 1] << 16) | (bytes[offset + 2] << 8) | bytes[offset + 3];
  }

  async function parseID3(file) {
    const maxRead = Math.min(file.size, 1024 * 1024);
    const buffer = await file.slice(0, maxRead).arrayBuffer();
    const bytes = new Uint8Array(buffer);
    if (bytes.length < 10 || bytes[0] !== 0x49 || bytes[1] !== 0x44 || bytes[2] !== 0x33) {
      return {};
    }

    const versionMajor = bytes[3];
    const flags = bytes[5];
    const tagSize = readSynchsafeInt(bytes[6], bytes[7], bytes[8], bytes[9]);
    let offset = 10;

    if (flags & 0x40) {
      if (versionMajor === 4 && offset + 4 <= bytes.length) {
        const extSize = readSynchsafeInt(bytes[offset], bytes[offset + 1], bytes[offset + 2], bytes[offset + 3]);
        offset += extSize;
      } else if (offset + 4 <= bytes.length) {
        const extSize = (bytes[offset] << 24) | (bytes[offset + 1] << 16) | (bytes[offset + 2] << 8) | bytes[offset + 3];
        offset += extSize + 4;
      }
    }

    const limit = Math.min(bytes.length, 10 + tagSize);
    const out = {};

    while (offset + 10 <= limit) {
      const frameId = String.fromCharCode(bytes[offset], bytes[offset + 1], bytes[offset + 2], bytes[offset + 3]);
      if (!/^[A-Z0-9]{4}$/.test(frameId)) break;

      const frameSize = readFrameSize(versionMajor, bytes, offset + 4);
      if (frameSize <= 0) break;

      const start = offset + 10;
      const end = start + frameSize;
      if (end > limit) break;
      const payload = bytes.slice(start, end);

      if (frameId === "TIT2") out.title = decodeTextFrame(payload);
      if (frameId === "TPE1" || frameId === "TPE2") {
        const artist = decodeTextFrame(payload);
        if (artist && !out.artist) out.artist = artist;
      }
      if (frameId === "TCON") out.genre = decodeTextFrame(payload);
      if ((frameId === "USLT" || frameId === "SYLT") && !out.lyrics) out.lyrics = decodeUsltFrame(payload);

      offset = end;
    }

    return out;
  }

  const songFileInput = document.getElementById("song-file-input");
  const songTitleInput = document.getElementById("song-title-input");
  const songArtistInput = document.getElementById("song-artist-input");
  const songGenreInput = document.getElementById("song-genre-input");
  const songSubmit = document.getElementById("add-song-submit");
  const retryLyricsBtn = document.getElementById("retry-lyrics-btn");
  const id3Status = document.getElementById("id3-status");
  const lyricsStatus = document.getElementById("lyrics-status");
  const lyricsTextInput = document.getElementById("song-lyrics-text-input");
  const lyricsSourceInput = document.getElementById("song-lyrics-source-input");
  const lyricsFileWrap = document.getElementById("lyrics-file-wrap");
  const lyricsFileInput = document.getElementById("lyrics-file-input");
  const lyricsCandidateModal = document.getElementById("lyrics-candidate-modal");
  const lyricsCandidateMeta = document.getElementById("lyrics-candidate-meta");
  const lyricsCandidatePreview = document.getElementById("lyrics-candidate-preview");
  const lyricsCandidateAccept = document.getElementById("lyrics-candidate-accept");
  const lyricsCandidateReject = document.getElementById("lyrics-candidate-reject");
  const lyricsLoadingModal = document.getElementById("lyrics-loading-modal");
  const lyricsLoadingStep = document.getElementById("lyrics-loading-step");

  let pendingLyricsCandidate = null;

  function setSongFieldsLocked(locked) {
    [songTitleInput, songArtistInput, songGenreInput, songSubmit].forEach((el) => {
      if (el) el.disabled = locked;
    });
    if (lyricsFileInput) lyricsFileInput.disabled = locked;
  }

  function clearLyricsCandidate() {
    pendingLyricsCandidate = null;
    if (lyricsCandidateMeta) lyricsCandidateMeta.textContent = "";
    if (lyricsCandidatePreview) lyricsCandidatePreview.textContent = "";
  }

  function setLyricsFileWrapVisible(visible) {
    if (!lyricsFileWrap) return;
    lyricsFileWrap.classList.toggle("hidden", !visible);
  }

  function setLyricsFromDetected(textValue, sourceValue) {
    if (lyricsTextInput) lyricsTextInput.value = textValue || "";
    if (lyricsSourceInput) lyricsSourceInput.value = sourceValue || "";
  }

  function showLyricsLoading(stepText) {
    if (lyricsLoadingStep) lyricsLoadingStep.textContent = stepText || (i18n.appLyricsLoadingStepMetadata || "Loading...");
    showModal(lyricsLoadingModal);
  }

  function hideLyricsLoading() {
    hideModal(lyricsLoadingModal);
  }

  async function enrichMetadataFromTitle(title) {
    const qTitle = (title || "").trim();
    if (!qTitle) return null;
    const params = new URLSearchParams({ title: qTitle });
    const res = await fetch(`/songs/metadata-enrich?${params.toString()}`, { credentials: "same-origin" });
    if (!res.ok) return null;
    const data = await res.json();
    if (!data || !data.ok || !data.item) return null;
    return data.item;
  }

  function updateRetryLyricsButtonState() {
    if (!retryLyricsBtn) return;
    const hasArtist = Boolean((songArtistInput && songArtistInput.value || "").trim());
    const hasTitle = Boolean((songTitleInput && songTitleInput.value || "").trim());
    retryLyricsBtn.disabled = !(hasArtist && hasTitle);
  }

  async function runLyricsLookupFromForm({ keepLoading = false } = {}) {
    const title = songTitleInput ? songTitleInput.value.trim() : "";
    const artist = songArtistInput ? songArtistInput.value.trim() : "";
    if (!title || !artist) {
      updateRetryLyricsButtonState();
      return false;
    }

    if (!keepLoading) showLyricsLoading(i18n.appLyricsLoadingStepOnline || "Searching subtitles online...");
    if (lyricsStatus) lyricsStatus.textContent = i18n.appLyricsSearchingOnline || "Searching subtitles online...";

    try {
      const candidate = await searchLyricsOnline(title, artist);
      if (candidate && candidate.lyrics_text) {
        pendingLyricsCandidate = candidate;
        if (lyricsCandidateMeta) {
          lyricsCandidateMeta.textContent = `${candidate.title || title} - ${candidate.artist || artist}`;
        }
        if (lyricsCandidatePreview) {
          const preview = String(candidate.lyrics_text || "").split(/\r?\n/).slice(0, 18).join("\n");
          lyricsCandidatePreview.textContent = preview;
        }
        hideLyricsLoading();
        showModal(lyricsCandidateModal);
        if (lyricsStatus) lyricsStatus.textContent = i18n.appLyricsCandidateTitle || "Subtitles found online.";
        showClientNotice(i18n.appLyricsAutoSuccess || "Subtitles detected automatically.", "success");
        return true;
      }

      setLyricsFileWrapVisible(true);
      if (lyricsStatus) lyricsStatus.textContent = i18n.appLyricsSearchNone || "No subtitles found online.";
      showClientNotice(i18n.appLyricsAutoFail || "No automatic subtitles found.", "warning");
      return false;
    } catch (_e) {
      setLyricsFileWrapVisible(true);
      if (lyricsStatus) lyricsStatus.textContent = i18n.appLyricsSearchNone || "No subtitles found online.";
      showClientNotice(i18n.appLyricsAutoFail || "No automatic subtitles found.", "danger");
      return false;
    } finally {
      if (!keepLoading) hideLyricsLoading();
    }
  }

  async function searchLyricsOnline(title, artist) {
    const qTitle = (title || "").trim();
    if (!qTitle) return null;
    const params = new URLSearchParams({ title: qTitle, artist: (artist || "").trim() });
    const res = await fetch(`/songs/lyrics-search?${params.toString()}`, { credentials: "same-origin" });
    if (!res.ok) return null;
    const data = await res.json();
    if (!data || !data.ok || !data.item || !data.item.lyrics_text) return null;
    return data.item;
  }

  function hasLrcTimestamps(textValue) {
    return /\[(\d{1,2}):(\d{2})(?:[.:](\d{1,3}))?\]/.test(textValue || "");
  }

  if (lyricsFileInput) {
    lyricsFileInput.addEventListener("change", async () => {
      const file = lyricsFileInput.files && lyricsFileInput.files[0];
      if (!file) return;

      setSongFieldsLocked(true);
      showLyricsLoading(i18n.appLyricsLoadingStepFile || "Processing subtitle file...");
      try {
        const rawText = await file.text();
        const lower = (file.name || "").toLowerCase();
        const isLrc = lower.endsWith(".lrc");
        const hasSync = isLrc && hasLrcTimestamps(rawText);

        if (!String(rawText || "").trim()) {
          setLyricsFromDetected("", "");
          if (lyricsStatus) lyricsStatus.textContent = i18n.appLyricsLrcSyncFail || "Invalid subtitle file.";
          showClientNotice(i18n.appLyricsLrcSyncFail || "Invalid subtitle file.", "danger");
          return;
        }

        setLyricsFromDetected(rawText, isLrc ? "upload_lrc" : "upload_txt");
        setLyricsFileWrapVisible(true);

        const syncMessage = hasSync
          ? (i18n.appLyricsSyncStateSynced || "Subtitles processed with sync enabled.")
          : (i18n.appLyricsSyncStateUnsynced || "Subtitles processed without synchronization.");
        if (lyricsStatus) lyricsStatus.textContent = syncMessage;
        showClientNotice(syncMessage, hasSync ? "success" : "warning");
      } catch (_e) {
        if (lyricsStatus) lyricsStatus.textContent = i18n.appLyricsLrcSyncFail || "Invalid subtitle file.";
        showClientNotice(i18n.appLyricsLrcSyncFail || "Invalid subtitle file.", "danger");
      } finally {
        hideLyricsLoading();
        setSongFieldsLocked(false);
      }
    });
  }

  if (lyricsCandidateAccept) {
    lyricsCandidateAccept.addEventListener("click", () => {
      if (pendingLyricsCandidate && pendingLyricsCandidate.lyrics_text) {
        setLyricsFromDetected(pendingLyricsCandidate.lyrics_text, "online_auto");
        if (lyricsStatus) lyricsStatus.textContent = i18n.appTagsDone || "Subtitles loaded.";
        setLyricsFileWrapVisible(false);
      }
      clearLyricsCandidate();
      hideModal(lyricsCandidateModal);
    });
  }

  if (lyricsCandidateReject) {
    lyricsCandidateReject.addEventListener("click", () => {
      setLyricsFromDetected("", "");
      setLyricsFileWrapVisible(true);
      if (lyricsStatus) lyricsStatus.textContent = i18n.appLyricsSearchNone || "No subtitles found online.";
      clearLyricsCandidate();
      hideModal(lyricsCandidateModal);
    });
  }

  if (songFileInput) {
    songFileInput.addEventListener("change", async () => {
      const file = songFileInput.files && songFileInput.files[0];
      clearLyricsCandidate();
      setLyricsFromDetected("", "");
      setLyricsFileWrapVisible(false);

      if (!file) {
        setSongFieldsLocked(false);
        if (id3Status) id3Status.textContent = "";
        if (lyricsStatus) lyricsStatus.textContent = "";
        updateRetryLyricsButtonState();
        return;
      }

      setSongFieldsLocked(true);
      showLyricsLoading(i18n.appLyricsLoadingStepMetadata || "Checking audio metadata...");
      if (id3Status) id3Status.textContent = i18n.appLoadingTags || "Reading ID3 tags...";
      if (lyricsStatus) lyricsStatus.textContent = i18n.appLyricsDetecting || "Detecting subtitles from metadata...";

      try {
        const tags = await parseID3(file);
        if (tags.title && songTitleInput) songTitleInput.value = tags.title;
        if (tags.artist && songArtistInput) songArtistInput.value = tags.artist;
        if (tags.genre && songGenreInput) songGenreInput.value = tags.genre;

        if (id3Status) {
          id3Status.textContent = (tags.title || tags.artist || tags.genre)
            ? (i18n.appTagsDone || "ID3 tags loaded.")
            : (i18n.appTagsFail || "No ID3 tags found.");
        }

        const titleNow = songTitleInput ? songTitleInput.value.trim() : "";
        const artistNow = songArtistInput ? songArtistInput.value.trim() : "";
        const genreNow = songGenreInput ? songGenreInput.value.trim() : "";

        if (titleNow && (!artistNow || !genreNow)) {
          showLyricsLoading(i18n.appMetadataEnriching || "Searching artist and genre online...");
          try {
            const enriched = await enrichMetadataFromTitle(titleNow);
            if (enriched) {
              if (songArtistInput && !songArtistInput.value.trim() && enriched.artist) songArtistInput.value = enriched.artist;
              if (songGenreInput && !songGenreInput.value.trim() && enriched.genre) songGenreInput.value = enriched.genre;
            }
          } catch (_e) {
          }
        }

        updateRetryLyricsButtonState();

        if (tags.lyrics) {
          setLyricsFromDetected(tags.lyrics, "metadata");
          if (lyricsStatus) lyricsStatus.textContent = i18n.appLyricsFoundMetadata || "Subtitles detected in metadata.";
          setLyricsFileWrapVisible(false);
        } else {
          showLyricsLoading(i18n.appLyricsLoadingStepOnline || "Searching subtitles online...");
          await runLyricsLookupFromForm({ keepLoading: true });
        }
      } catch (_e) {
        if (id3Status) id3Status.textContent = i18n.appTagsFail || "ID3 read failed.";
        setLyricsFileWrapVisible(true);
        if (lyricsStatus) lyricsStatus.textContent = i18n.appLyricsSearchNone || "No subtitles found online.";
      } finally {
        hideLyricsLoading();
        setSongFieldsLocked(false);
        updateRetryLyricsButtonState();
      }
    });
  }

  if (songTitleInput) songTitleInput.addEventListener("input", updateRetryLyricsButtonState);
  if (songArtistInput) songArtistInput.addEventListener("input", updateRetryLyricsButtonState);

  if (retryLyricsBtn) {
    retryLyricsBtn.addEventListener("click", async () => {
      if (retryLyricsBtn.disabled) return;
      await runLyricsLookupFromForm({ keepLoading: false });
      updateRetryLyricsButtonState();
    });
    updateRetryLyricsButtonState();
  }

  document.querySelectorAll(".edit-lyrics-file-input").forEach((input) => {
    input.addEventListener("change", async () => {
      const file = input.files && input.files[0];
      if (!file) return;
      const form = input.closest("form");
      if (!form) return;

      const hiddenText = form.querySelector(".edit-lyrics-text");
      const hiddenSource = form.querySelector(".edit-lyrics-source");
      let status = form.querySelector(".edit-lyrics-status");
      if (!status) {
        status = document.createElement("p");
        status.className = "muted small edit-lyrics-status";
        input.insertAdjacentElement("afterend", status);
      }

      showLyricsLoading(i18n.appLyricsLoadingStepFile || "Processing subtitle file...");
      try {
        const rawText = await file.text();
        const lower = (file.name || "").toLowerCase();
        const isLrc = lower.endsWith(".lrc");
        const hasSync = isLrc && hasLrcTimestamps(rawText);

        if (!String(rawText || "").trim()) {
          if (hiddenText) hiddenText.value = "";
          if (hiddenSource) hiddenSource.value = "";
          if (status) status.textContent = i18n.appLyricsLrcSyncFail || "Invalid subtitle file.";
          showClientNotice(i18n.appLyricsLrcSyncFail || "Invalid subtitle file.", "danger");
          return;
        }

        if (hiddenText) hiddenText.value = rawText;
        if (hiddenSource) hiddenSource.value = isLrc ? "upload_lrc_edit" : "upload_txt_edit";

        const syncMessage = hasSync
          ? (i18n.appLyricsSyncStateSynced || "Subtitles processed with sync enabled.")
          : (i18n.appLyricsSyncStateUnsynced || "Subtitles processed without synchronization.");
        if (status) status.textContent = syncMessage;
        showClientNotice(syncMessage, hasSync ? "success" : "warning");
      } catch (_e) {
        if (status) status.textContent = i18n.appLyricsLrcSyncFail || "Invalid subtitle file.";
        showClientNotice(i18n.appLyricsLrcSyncFail || "Invalid subtitle file.", "danger");
      } finally {
        hideLyricsLoading();
      }
    });
  });

  document.querySelectorAll(".detect-lyrics-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const form = btn.closest("form");
      if (!form) return;
      const songId = btn.getAttribute("data-song-id") || "";
      const titleInput = form.querySelector('input[name="title"]');
      const artistInput = form.querySelector('input[name="artist"]');
      const hiddenText = form.querySelector(".edit-lyrics-text");
      const hiddenSource = form.querySelector(".edit-lyrics-source");
      const fileWrap = form.querySelector(".edit-lyrics-file-wrap");

      let status = form.querySelector(".edit-lyrics-status");
      if (!status) {
        status = document.createElement("p");
        status.className = "muted small edit-lyrics-status";
        btn.insertAdjacentElement("afterend", status);
      }

      const setStatus = (msg) => {
        if (status) status.textContent = msg || "";
      };

      btn.disabled = true;
      try {
        showLyricsLoading(i18n.appLyricsLoadingStepMetadata || "Checking audio metadata...");
        let found = null;
        if (songId) {
          const res = await fetch(`/songs/${encodeURIComponent(songId)}/lyrics-detect-metadata`, { credentials: "same-origin" });
          const data = res.ok ? await res.json() : null;
          if (data && data.ok && data.found && data.item && data.item.lyrics_text) {
            found = { source: "metadata_edit", text: data.item.lyrics_text };
          }
        }

        if (!found) {
          showLyricsLoading(i18n.appLyricsLoadingStepOnline || "Searching subtitles online...");
          const title = titleInput ? titleInput.value : (btn.getAttribute("data-song-title") || "");
          const artist = artistInput ? artistInput.value : (btn.getAttribute("data-song-artist") || "");
          const candidate = await searchLyricsOnline(title, artist);
          if (candidate && candidate.lyrics_text) {
            found = { source: "online_auto_edit", text: candidate.lyrics_text };
          }
        }

        if (found) {
          if (hiddenText) hiddenText.value = found.text;
          if (hiddenSource) hiddenSource.value = found.source;
          if (fileWrap) fileWrap.classList.add("hidden");
          setStatus(i18n.appTagsDone || "Subtitles found.");
        } else {
          if (hiddenText) hiddenText.value = "";
          if (hiddenSource) hiddenSource.value = "";
          if (fileWrap) fileWrap.classList.remove("hidden");
          setStatus(i18n.appLyricsSearchNone || "No subtitles found online.");
        }
      } catch (_e) {
        if (fileWrap) fileWrap.classList.remove("hidden");
        setStatus(i18n.appLyricsSearchNone || "No subtitles found online.");
      } finally {
        hideLyricsLoading();
        btn.disabled = false;
      }
    });
  });

  function attachAutocomplete(input) {
    const url = input.getAttribute("data-autocomplete-url");
    if (!url) return;

    const box = document.createElement("div");
    box.className = "autocomplete-box";
    input.insertAdjacentElement("afterend", box);

    let items = [];
    let index = -1;
    let timer = null;

    function render() {
      box.innerHTML = "";
      items.forEach((item, i) => {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = `autocomplete-item${i === index ? " active" : ""}`;
        btn.textContent = item.value || item.title || "";
        btn.addEventListener("click", () => {
          input.value = item.value || item.title || "";
          const targetHiddenId = input.getAttribute("data-target-hidden");
          if (targetHiddenId) {
            const hidden = document.getElementById(targetHiddenId);
            if (hidden) hidden.value = item.song_id || "";
          }
          box.innerHTML = "";
          items = [];
          index = -1;

          if (input.getAttribute("data-submit-on-select") === "1") {
            const form = input.closest("form");
            if (form && typeof form.requestSubmit === "function") form.requestSubmit();
            else if (form) form.submit();
          }
        });
        box.appendChild(btn);
      });
    }

    function search() {
      const q = input.value.trim();
      if (!q) {
        items = [];
        index = -1;
        render();
        return;
      }
      fetch(`${url}?q=${encodeURIComponent(q)}`, { credentials: "same-origin" })
        .then((res) => (res.ok ? res.json() : { items: [] }))
        .then((data) => {
          items = Array.isArray(data.items) ? data.items : [];
          index = items.length ? 0 : -1;
          render();
        })
        .catch(() => {
          items = [];
          index = -1;
          render();
        });
    }

    input.addEventListener("input", () => {
      const targetHiddenId = input.getAttribute("data-target-hidden");
      if (targetHiddenId) {
        const hidden = document.getElementById(targetHiddenId);
        if (hidden) hidden.value = "";
      }
      clearTimeout(timer);
      timer = setTimeout(search, 120);
    });

    input.addEventListener("keydown", (event) => {
      if (!items.length) return;
      if (event.key === "ArrowDown") {
        event.preventDefault();
        index = Math.min(index + 1, items.length - 1);
        render();
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        index = Math.max(index - 1, 0);
        render();
      } else if (event.key === "Enter") {
        event.preventDefault();
        if (items[index]) {
          input.value = items[index].value || items[index].title || "";
          const targetHiddenId = input.getAttribute("data-target-hidden");
          if (targetHiddenId) {
            const hidden = document.getElementById(targetHiddenId);
            if (hidden) hidden.value = items[index].song_id || "";
          }
          items = [];
          index = -1;
          render();

          if (input.getAttribute("data-submit-on-select") === "1") {
            const form = input.closest("form");
            if (form && typeof form.requestSubmit === "function") form.requestSubmit();
            else if (form) form.submit();
          }
        }
      }
    });

    document.addEventListener("click", (event) => {
      if (event.target === input || box.contains(event.target)) return;
      items = [];
      index = -1;
      render();
    });
  }
  document.querySelectorAll("input[data-autocomplete-url]").forEach((input) => {
    if (input.id === "user-picker-search") return;
    attachAutocomplete(input);
  });

  const passwordPolicyRe = /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^A-Za-z0-9]).{6,}$/;

  function fieldFeedbackNode(field) {
    const host = field && (field.closest("label") || field.parentElement);
    if (!host) return null;
    let node = host.querySelector(".field-feedback");
    if (!node) {
      node = document.createElement("div");
      node.className = "field-feedback";
      host.appendChild(node);
    }
    return node;
  }

  function setFieldState(field, message) {
    const node = fieldFeedbackNode(field);
    if (field) field.classList.toggle("is-invalid", Boolean(message));
    if (node) node.textContent = message || "";
    return !message;
  }

  async function remoteAvailabilityCheck(field) {
    const url = field.getAttribute("data-remote-url");
    const fieldName = field.getAttribute("data-remote-check");
    const value = field.value.trim();
    if (!url || !fieldName || !value) return "";
    const seq = String(Number(field.dataset.remoteSeq || "0") + 1);
    field.dataset.remoteSeq = seq;
    try {
      const res = await fetch(`${url}?field=${encodeURIComponent(fieldName)}&value=${encodeURIComponent(value)}`, { credentials: "same-origin" });
      const data = res.ok ? await res.json() : { available: false, message: i18n.validationRequired || "Invalid value." };
      if (field.dataset.remoteSeq !== seq) return "";
      return data.available ? "" : (data.message || i18n.validationRequired || "Invalid value.");
    } catch (_e) {
      return "";
    }
  }

  async function validateField(field, form) {
    if (!field || field.disabled || field.type === "hidden") return true;
    field.setCustomValidity("");
    let message = "";

    if (!field.checkValidity()) {
      if (field.validity.valueMissing) message = i18n.validationRequired || field.validationMessage;
      else if (field.validity.typeMismatch && field.type === "email") message = i18n.validationEmail || field.validationMessage;
      else if (field.validity.tooShort) message = i18n.validationTooShort || field.validationMessage;
      else if (field.validity.patternMismatch && field.getAttribute("data-remote-check") === "username") message = i18n.validationUsernameInvalid || field.validationMessage;
      else message = field.validationMessage;
    }

    if (!message && field.dataset.passwordPolicy === "1" && field.value && !passwordPolicyRe.test(field.value)) {
      message = i18n.validationPasswordPolicy || "Invalid password.";
    }

    if (!message && field.dataset.matchTarget) {
      const other = document.getElementById(field.dataset.matchTarget);
      if (other && field.value !== other.value) {
        message = i18n.validationPasswordMatch || "Values do not match.";
      }
    }

    if (!message && field.dataset.requireSelectionTarget) {
      const target = document.getElementById(field.dataset.requireSelectionTarget);
      if (field.value.trim() && target && !target.value.trim()) {
        message = i18n.validationSelectionRequired || "Select a valid suggestion.";
      }
    }

    if (!message && field.dataset.remoteCheck && field.value.trim()) {
      message = await remoteAvailabilityCheck(field);
    }

    if (!message && form && form.dataset.requireSource === "1") {
      const urlField = document.getElementById(form.dataset.sourceUrl || "");
      const fileField = document.getElementById(form.dataset.sourceFile || "");
      if (field === urlField || field === fileField) {
        const hasUrl = Boolean(urlField && urlField.value.trim());
        const hasFile = Boolean(fileField && fileField.files && fileField.files.length);
        if (!hasUrl && !hasFile) message = i18n.validationSourceRequired || "Provide a source.";
      }
    }

    if (!message && form && form.dataset.privateVisibility && form.dataset.privateTarget) {
      const visibility = document.getElementById(form.dataset.privateVisibility);
      const targetWrap = document.getElementById(form.dataset.privateTarget);
      if (field === visibility && visibility && visibility.value === "private") {
        const selected = targetWrap ? targetWrap.querySelectorAll('input[name="shared_with"]').length : 0;
        if (!selected) message = i18n.validationPrivateUsersRequired || "Select at least one user.";
      }
    }

    return setFieldState(field, message);
  }

  async function validateForm(form) {
    const fields = Array.from(form.querySelectorAll("input, textarea, select"));
    let ok = true;
    for (const field of fields) {
      ok = (await validateField(field, form)) && ok;
    }
    if (form.dataset.privateVisibility) {
      const visibility = document.getElementById(form.dataset.privateVisibility);
      if (visibility) ok = (await validateField(visibility, form)) && ok;
    }
    if (form.dataset.requireSource === "1") {
      const urlField = document.getElementById(form.dataset.sourceUrl || "");
      if (urlField) ok = (await validateField(urlField, form)) && ok;
    }
    return ok;
  }

  const registerForm = document.getElementById("register-form");
  const registerEmail = document.getElementById("register-email");
  const registerTempAck = document.getElementById("register-temp-email-ack");

  function resetTempEmailAck() {
    if (registerTempAck) registerTempAck.value = "0";
    if (registerForm) delete registerForm.dataset.tempEmailConfirmed;
  }

  if (registerEmail) {
    registerEmail.addEventListener("input", () => {
      resetTempEmailAck();
    });
  }

  if (registerForm) {
    registerForm.addEventListener("submit", (event) => {
      if (!registerEmail) return;
      const alreadyConfirmed = registerForm.dataset.tempEmailConfirmed === "1";
      if (alreadyConfirmed) return;
      if (!isDisposableEmail(registerEmail.value)) {
        resetTempEmailAck();
        return;
      }
      event.preventDefault();
      if (registerTempAck) registerTempAck.value = "0";
      showModal(tempEmailModal);
    });
  }

  if (tempEmailProceed) {
    tempEmailProceed.addEventListener("click", () => {
      if (!registerForm) return;
      registerForm.dataset.tempEmailConfirmed = "1";
      if (registerTempAck) registerTempAck.value = "1";
      hideModal(tempEmailModal);
      if (typeof registerForm.requestSubmit === "function") registerForm.requestSubmit();
      else registerForm.submit();
    });
  }

  if (tempEmailCancel) {
    tempEmailCancel.addEventListener("click", () => {
      resetTempEmailAck();
      hideModal(tempEmailModal);
      if (registerEmail && typeof registerEmail.focus === "function") registerEmail.focus();
    });
  }

  document.querySelectorAll("form").forEach((form) => {
    if (form.classList.contains("delete-song-form") || form.classList.contains("lang-form")) return;
    const visibleFields = Array.from(form.querySelectorAll("input, textarea, select")).filter((field) => field.type !== "hidden");
    if (!visibleFields.length) return;
    form.setAttribute("novalidate", "novalidate");

    visibleFields.forEach((field) => {
      const handler = () => validateField(field, form).catch(() => {});
      field.addEventListener("input", handler);
      field.addEventListener("change", handler);
      field.addEventListener("blur", handler);
      if (field.dataset.matchTarget) {
        const other = document.getElementById(field.dataset.matchTarget);
        if (other) other.addEventListener("input", () => validateField(field, form).catch(() => {}));
      }
    });

    form.addEventListener("submit", async (event) => {
      const ok = await validateForm(form);
      if (!ok) {
        event.preventDefault();
        const firstInvalid = form.querySelector(".is-invalid");
        if (firstInvalid && typeof firstInvalid.focus === "function") firstInvalid.focus();
      }
    });
  });

  [confirmModal, reportModal, userPickerModal, tempEmailModal, lyricsCandidateModal].forEach((modal) => {
    if (!modal) return;
    modal.addEventListener("click", (event) => {
      if (event.target === modal) hideModal(modal);
    });
  });

  window.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    hideModal(confirmModal);
    hideModal(reportModal);
    hideModal(userPickerModal);
    hideModal(tempEmailModal);
    hideModal(lyricsCandidateModal);
  });
})();





