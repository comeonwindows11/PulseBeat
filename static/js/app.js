(function () {
  const i18n = window.I18N || {};

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
        return new TextDecoder(encoding === 0 ? "latin1" : "utf-8").decode(body).replace(/\0/g, "").trim();
      }
      if (encoding === 1 || encoding === 2) {
        return new TextDecoder("utf-16").decode(body).replace(/\0/g, "").trim();
      }
    } catch (_e) {
      return "";
    }
    return "";
  }

  async function parseID3(file) {
    const maxRead = Math.min(file.size, 1024 * 512);
    const buffer = await file.slice(0, maxRead).arrayBuffer();
    const bytes = new Uint8Array(buffer);
    if (bytes.length < 10 || bytes[0] !== 0x49 || bytes[1] !== 0x44 || bytes[2] !== 0x33) {
      return {};
    }

    const tagSize = ((bytes[6] & 0x7f) << 21) | ((bytes[7] & 0x7f) << 14) | ((bytes[8] & 0x7f) << 7) | (bytes[9] & 0x7f);
    let offset = 10;
    const limit = Math.min(bytes.length, 10 + tagSize);
    const out = {};

    while (offset + 10 <= limit) {
      const frameId = String.fromCharCode(bytes[offset], bytes[offset + 1], bytes[offset + 2], bytes[offset + 3]);
      const frameSize = (bytes[offset + 4] << 24) | (bytes[offset + 5] << 16) | (bytes[offset + 6] << 8) | bytes[offset + 7];
      if (!frameId.trim() || frameSize <= 0) break;
      const start = offset + 10;
      const end = start + frameSize;
      if (end > limit) break;
      const payload = bytes.slice(start, end);

      if (frameId === "TIT2") out.title = decodeTextFrame(payload);
      if (frameId === "TPE1") out.artist = decodeTextFrame(payload);
      if (frameId === "TCON") out.genre = decodeTextFrame(payload);

      offset = end;
    }

    return out;
  }

  const songFileInput = document.getElementById("song-file-input");
  const songTitleInput = document.getElementById("song-title-input");
  const songArtistInput = document.getElementById("song-artist-input");
  const songGenreInput = document.getElementById("song-genre-input");
  const songSubmit = document.getElementById("add-song-submit");
  const id3Status = document.getElementById("id3-status");

  function setSongFieldsLocked(locked) {
    [songTitleInput, songArtistInput, songGenreInput, songSubmit].forEach((el) => {
      if (el) el.disabled = locked;
    });
  }

  if (songFileInput) {
    songFileInput.addEventListener("change", async () => {
      const file = songFileInput.files && songFileInput.files[0];
      if (!file) {
        setSongFieldsLocked(false);
        if (id3Status) id3Status.textContent = "";
        return;
      }

      setSongFieldsLocked(true);
      if (id3Status) id3Status.textContent = i18n.appLoadingTags || "Reading ID3 tags...";

      try {
        const tags = await parseID3(file);
        if (tags.title) songTitleInput.value = tags.title;
        if (tags.artist) songArtistInput.value = tags.artist;
        if (tags.genre) songGenreInput.value = tags.genre;
        if (id3Status) {
          id3Status.textContent = (tags.title || tags.artist || tags.genre)
            ? (i18n.appTagsDone || "ID3 tags loaded.")
            : (i18n.appTagsFail || "No ID3 tags found.");
        }
      } catch (_e) {
        if (id3Status) id3Status.textContent = i18n.appTagsFail || "ID3 read failed.";
      } finally {
        setSongFieldsLocked(false);
      }
    });
  }

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

  [confirmModal, reportModal, userPickerModal].forEach((modal) => {
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
  });
})();




