(function () {
  const i18n = window.I18N || {};
  const csrfToken = String(window.CSRF_TOKEN || "").trim();

  if (!window.__PB_FETCH_CSRF_PATCHED__ && typeof window.fetch === "function") {
    const originalFetch = window.fetch.bind(window);
    window.fetch = function patchedFetch(input, init = {}) {
      try {
        const method = String(
          (init && init.method)
            || (input instanceof Request ? input.method : "GET")
            || "GET"
        ).toUpperCase();
        const isSafeMethod = method === "GET" || method === "HEAD" || method === "OPTIONS";
        if (isSafeMethod || !csrfToken) {
          return originalFetch(input, init);
        }

        const urlValue = input instanceof Request ? input.url : String(input);
        const url = new URL(urlValue, window.location.origin);
        if (url.origin !== window.location.origin) {
          return originalFetch(input, init);
        }

        const headers = new Headers(
          (init && init.headers) || (input instanceof Request ? input.headers : undefined)
        );
        headers.set("X-CSRF-Token", csrfToken);

        const nextInit = Object.assign({}, init, { headers });
        if (!nextInit.credentials && !(input instanceof Request)) {
          nextInit.credentials = "same-origin";
        }
        return originalFetch(input, nextInit);
      } catch (_err) {
        return originalFetch(input, init);
      }
    };
    window.__PB_FETCH_CSRF_PATCHED__ = true;
  }

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
  const navBackdrop = document.getElementById("nav-backdrop");

  function setMenuOpen(open) {
    if (!menuBtn || !nav) return;
    const isOpen = !!open;
    nav.classList.toggle("open", isOpen);
    menuBtn.classList.toggle("active", isOpen);
    menuBtn.setAttribute("aria-expanded", isOpen ? "true" : "false");
    if (navBackdrop) {
      navBackdrop.classList.toggle("hidden", !isOpen);
      navBackdrop.setAttribute("aria-hidden", isOpen ? "false" : "true");
    }
    document.body.classList.toggle("nav-open", isOpen);
  }

  if (menuBtn && nav) {
    menuBtn.addEventListener("click", () => {
      setMenuOpen(!nav.classList.contains("open"));
    });
    if (navBackdrop) {
      navBackdrop.addEventListener("click", () => setMenuOpen(false));
    }
    nav.querySelectorAll("a").forEach((link) => {
      link.addEventListener("click", () => setMenuOpen(false));
    });

    let navGesture = null;
    window.addEventListener("pointerdown", (event) => {
      if (window.innerWidth > 768) return;
      if (event.pointerType === "mouse" && event.button !== 0) return;
      const target = event.target;
      if (nav.classList.contains("open")) {
        if (target.closest("#main-nav") || target.closest("#nav-backdrop")) {
          navGesture = { mode: "close", startX: event.clientX, startY: event.clientY };
        }
        return;
      }
      if (event.clientX <= 24) {
        navGesture = { mode: "open", startX: event.clientX, startY: event.clientY };
      }
    }, { passive: true });

    window.addEventListener("pointerup", (event) => {
      if (!navGesture || window.innerWidth > 768) {
        navGesture = null;
        return;
      }
      const dx = event.clientX - navGesture.startX;
      const dy = event.clientY - navGesture.startY;
      if (Math.abs(dx) < 46 || Math.abs(dx) < Math.abs(dy)) {
        navGesture = null;
        return;
      }
      if (navGesture.mode === "open" && dx > 46) {
        setMenuOpen(true);
      } else if (navGesture.mode === "close" && dx < -46) {
        setMenuOpen(false);
      }
      navGesture = null;
    }, { passive: true });
  }

  document.querySelectorAll("[data-password-toggle-target]").forEach((button) => {
    button.addEventListener("click", () => {
      const targetId = button.getAttribute("data-password-toggle-target");
      const input = targetId ? document.getElementById(targetId) : null;
      if (!input) return;
      const reveal = input.type === "password";
      input.type = reveal ? "text" : "password";
      button.classList.toggle("active", reveal);
      button.setAttribute("aria-pressed", reveal ? "true" : "false");
    });
  });

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

  document.querySelectorAll(".playlist-sort-list[data-playlist-sort-url]").forEach((list) => {
    let draggedSongId = "";
    let committedOrder = Array.from(list.querySelectorAll(".playlist-sort-item[data-song-id]")).map((item) => item.dataset.songId);

    function playlistItems() {
      return Array.from(list.querySelectorAll(".playlist-sort-item[data-song-id]"));
    }

    function applyOrder(order) {
      const byId = new Map(playlistItems().map((item) => [item.dataset.songId, item]));
      order.forEach((songId) => {
        const node = byId.get(songId);
        if (node) list.appendChild(node);
      });
    }

    async function persistOrder() {
      const url = String(list.getAttribute("data-playlist-sort-url") || "").trim();
      if (!url) return false;
      const orderedSongIds = playlistItems().map((item) => item.dataset.songId).filter(Boolean);
      if (!orderedSongIds.length) return false;
      list.dataset.busy = "1";
      try {
        const response = await fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({
            ordered_song_ids: orderedSongIds,
            songs_page: Number(list.getAttribute("data-playlist-page") || "1"),
            songs_q: String(list.getAttribute("data-playlist-search") || ""),
          }),
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok || !payload.ok) {
          applyOrder(committedOrder);
          showClientNotice(payload.message || i18n.playlistReorderFailed || "Unable to save the new playlist order.", "warning");
          return false;
        }
        committedOrder = orderedSongIds.slice();
        showClientNotice(payload.message || i18n.playlistReordered || "Playlist order updated.", "success");
        return true;
      } catch (_err) {
        applyOrder(committedOrder);
        showClientNotice(i18n.playlistReorderFailed || "Unable to save the new playlist order.", "warning");
        return false;
      } finally {
        delete list.dataset.busy;
      }
    }

    function bindItem(item) {
      item.addEventListener("dragstart", (event) => {
        if (list.dataset.busy === "1") {
          event.preventDefault();
          return;
        }
        draggedSongId = item.dataset.songId || "";
        item.classList.add("dragging");
        if (event.dataTransfer) {
          event.dataTransfer.effectAllowed = "move";
          event.dataTransfer.setData("text/plain", draggedSongId);
        }
      });

      item.addEventListener("dragend", () => {
        draggedSongId = "";
        item.classList.remove("dragging");
        playlistItems().forEach((row) => row.classList.remove("drop-target"));
      });

      item.addEventListener("dragover", (event) => {
        if (!draggedSongId || draggedSongId === item.dataset.songId || list.dataset.busy === "1") return;
        event.preventDefault();
        const bounds = item.getBoundingClientRect();
        const insertAfter = event.clientY > bounds.top + bounds.height / 2;
        playlistItems().forEach((row) => row.classList.remove("drop-target"));
        item.classList.add("drop-target");
        item.dataset.dropPosition = insertAfter ? "after" : "before";
      });

      item.addEventListener("drop", async (event) => {
        if (!draggedSongId || draggedSongId === item.dataset.songId || list.dataset.busy === "1") return;
        event.preventDefault();
        const dragged = list.querySelector(`.playlist-sort-item[data-song-id="${CSS.escape(draggedSongId)}"]`);
        if (!dragged) return;
        const insertAfter = item.dataset.dropPosition === "after";
        item.classList.remove("drop-target");
        if (insertAfter) list.insertBefore(dragged, item.nextSibling);
        else list.insertBefore(dragged, item);
        await persistOrder();
      });
    }

    playlistItems().forEach(bindItem);
  });

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
  const shareModal = document.getElementById("share-modal");
  const profileSubscribersModal = document.getElementById("profile-subscribers-modal");
  const shareModalTitle = document.getElementById("share-modal-title");
  const shareLinkInput = document.getElementById("share-link-input");
  const shareCopyBtn = document.getElementById("share-copy-btn");
  const shareNativeBtn = document.getElementById("share-native-btn");
  const shareCloseBtn = document.getElementById("share-close-btn");
  const shareDiscordBtn = document.getElementById("share-discord-btn");
  const shareMessengerBtn = document.getElementById("share-messenger-btn");
  const shareFacebookLink = document.getElementById("share-facebook-link");
  const shareXLink = document.getElementById("share-x-link");
  const shareTelegramLink = document.getElementById("share-telegram-link");
  const shareWhatsappLink = document.getElementById("share-whatsapp-link");
  const shareEmailLink = document.getElementById("share-email-link");
  const tempEmailModal = document.getElementById("temp-email-modal");
  const tempEmailProceed = document.getElementById("temp-email-proceed");
  const tempEmailCancel = document.getElementById("temp-email-cancel");
  const reportTitle = document.getElementById("report-modal-title");
  const reportForm = document.getElementById("report-modal-form");
  const reportCancel = document.getElementById("report-modal-cancel");
  const reportReason = document.getElementById("report-modal-reason");
  const notificationsToggle = document.getElementById("notifications-toggle");
  const notificationsPanel = document.getElementById("notifications-panel");
  const notificationsBadge = document.getElementById("notifications-badge");
  const notificationsClose = document.getElementById("notifications-close");
  let sharePayload = { url: "", title: "", text: "" };

  function closeNotificationsPanel() {
    if (!notificationsPanel || !notificationsToggle) return;
    notificationsPanel.classList.add("hidden");
    notificationsPanel.setAttribute("aria-hidden", "true");
    notificationsToggle.setAttribute("aria-expanded", "false");
  }

  function markHeaderNotificationsRead() {
    if (!notificationsToggle || !notificationsPanel) return;
    if (!notificationsBadge || notificationsBadge.classList.contains("hidden")) return;
    const url = notificationsToggle.getAttribute("data-mark-read-url") || "";
    if (!url) return;
    fetch(url, {
      method: "POST",
      credentials: "same-origin"
    }).then((res) => {
      if (!res.ok) return null;
      return res.json();
    }).then((data) => {
      if (!data || !data.ok) return;
      notificationsBadge.textContent = "0";
      notificationsBadge.classList.add("hidden");
      notificationsPanel.querySelectorAll(".notification-item.unread").forEach((item) => {
        item.classList.remove("unread");
      });
    }).catch(() => {});
  }

  if (notificationsToggle && notificationsPanel) {
    notificationsToggle.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const willOpen = notificationsPanel.classList.contains("hidden");
      if (!willOpen) {
        closeNotificationsPanel();
        return;
      }
      notificationsPanel.classList.remove("hidden");
      notificationsPanel.setAttribute("aria-hidden", "false");
      notificationsToggle.setAttribute("aria-expanded", "true");
      markHeaderNotificationsRead();
    });

    notificationsPanel.addEventListener("click", (event) => {
      event.stopPropagation();
    });

    if (notificationsClose) {
      notificationsClose.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        closeNotificationsPanel();
      });
    }

    document.addEventListener("click", (event) => {
      if (!notificationsPanel || notificationsPanel.classList.contains("hidden")) return;
      if (event.target.closest("#notifications-panel") || event.target.closest("#notifications-toggle")) return;
      closeNotificationsPanel();
    });

    let notificationGesture = null;
    notificationsPanel.addEventListener("pointerdown", (event) => {
      if (window.innerWidth > 768) return;
      notificationGesture = { startX: event.clientX, startY: event.clientY };
    }, { passive: true });
    notificationsPanel.addEventListener("pointerup", (event) => {
      if (!notificationGesture || window.innerWidth > 768) {
        notificationGesture = null;
        return;
      }
      const dx = event.clientX - notificationGesture.startX;
      const dy = event.clientY - notificationGesture.startY;
      notificationGesture = null;
      if (Math.abs(dy) > 50 && Math.abs(dy) > Math.abs(dx) && dy > 0) {
        closeNotificationsPanel();
      }
    }, { passive: true });
  }

  document.addEventListener("click", (event) => {
    const openBtn = event.target.closest("[data-open-modal]");
    if (openBtn) {
      event.preventDefault();
      const modalId = openBtn.getAttribute("data-open-modal") || "";
      if (modalId) showModal(document.getElementById(modalId));
      return;
    }
    const closeBtn = event.target.closest("[data-close-modal]");
    if (closeBtn) {
      event.preventDefault();
      const modalId = closeBtn.getAttribute("data-close-modal") || "";
      if (modalId) hideModal(document.getElementById(modalId));
    }
  });

  function updateShareModalLinks(payload) {
    const url = String(payload.url || "").trim();
    const title = String(payload.title || "").trim();
    const text = String(payload.text || "").trim() || title;
    sharePayload = { url, title, text };
    if (!url) return;

    if (shareLinkInput) shareLinkInput.value = url;
    if (shareModalTitle) shareModalTitle.textContent = title || (i18n.shareModalTitle || "Share");

    const encodedUrl = encodeURIComponent(url);
    const encodedText = encodeURIComponent(text);
    const encodedMailSubject = encodeURIComponent(title || i18n.shareOpen || "PulseBeat");
    const encodedMailBody = encodeURIComponent(`${text ? `${text}\n\n` : ""}${url}`);

    if (shareXLink) shareXLink.href = `https://twitter.com/intent/tweet?url=${encodedUrl}&text=${encodedText}`;
    if (shareFacebookLink) shareFacebookLink.href = `https://www.facebook.com/sharer/sharer.php?u=${encodedUrl}`;
    if (shareTelegramLink) shareTelegramLink.href = `https://t.me/share/url?url=${encodedUrl}&text=${encodedText}`;
    if (shareWhatsappLink) shareWhatsappLink.href = `https://api.whatsapp.com/send?text=${encodeURIComponent(`${text ? `${text} ` : ""}${url}`)}`;
    if (shareEmailLink) shareEmailLink.href = `mailto:?subject=${encodedMailSubject}&body=${encodedMailBody}`;
  }

  function openShareModal(payload) {
    if (!shareModal) return false;
    const shareUrl = String((payload && payload.url) || "").trim();
    const shareTitle = String((payload && payload.title) || document.title || "PulseBeat").trim();
    const shareText = String((payload && payload.text) || shareTitle).trim();
    if (!shareUrl) return false;

    updateShareModalLinks({ url: shareUrl, title: shareTitle, text: shareText });
    if (shareNativeBtn) {
      shareNativeBtn.classList.toggle("hidden", !(navigator.share && typeof navigator.share === "function"));
    }
    showModal(shareModal);
    setTimeout(() => {
      if (shareLinkInput) {
        shareLinkInput.focus();
        shareLinkInput.select();
      }
    }, 30);
    return true;
  }

  window.PulseBeatShare = {
    open(payload) {
      return openShareModal(payload);
    }
  };

  async function copyShareLink() {
    const value = String((shareLinkInput && shareLinkInput.value) || sharePayload.url || "").trim();
    if (!value) return false;

    try {
      if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
        await navigator.clipboard.writeText(value);
        return true;
      }
    } catch (_e) {}

    try {
      if (shareLinkInput) {
        shareLinkInput.focus();
        shareLinkInput.select();
      }
      return document.execCommand("copy");
    } catch (_e) {
      return false;
    }
  }

  async function copyAndOpen(targetUrl, successMessage) {
    const copied = await copyShareLink();
    if (copied) {
      showClientNotice(successMessage || i18n.shareCopySuccess || "Copied.", "success");
    } else {
      showClientNotice(i18n.shareCopyError || "Unable to copy link.", "warning");
    }
    window.open(targetUrl, "_blank", "noopener,noreferrer");
  }

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

  document.addEventListener("click", (event) => {
    const btn = event.target.closest(".open-share-modal");
    if (!btn || !shareModal) return;
    const shareUrl = btn.getAttribute("data-share-url") || "";
    const shareTitle = btn.getAttribute("data-share-title") || document.title || "PulseBeat";
    const shareText = btn.getAttribute("data-share-text") || shareTitle;
    if (!shareUrl) return;
    openShareModal({ url: shareUrl, title: shareTitle, text: shareText });
  });

  if (shareCopyBtn) {
    shareCopyBtn.addEventListener("click", async () => {
      const ok = await copyShareLink();
      showClientNotice(ok ? (i18n.shareCopySuccess || "Copied.") : (i18n.shareCopyError || "Unable to copy link."), ok ? "success" : "warning");
    });
  }

  if (shareNativeBtn) {
    shareNativeBtn.addEventListener("click", async () => {
      if (!navigator.share || typeof navigator.share !== "function") return;
      if (!sharePayload.url) return;
      try {
        await navigator.share({
          title: sharePayload.title || "",
          text: sharePayload.text || "",
          url: sharePayload.url,
        });
      } catch (_e) {}
    });
  }

  if (shareDiscordBtn) {
    shareDiscordBtn.addEventListener("click", () => {
      copyAndOpen("https://discord.com/channels/@me", i18n.shareDiscordHint || "Link copied. Paste in Discord.");
    });
  }

  if (shareMessengerBtn) {
    shareMessengerBtn.addEventListener("click", () => {
      copyAndOpen("https://www.messenger.com/new", i18n.shareMessengerHint || "Link copied. Paste in Messenger.");
    });
  }

  if (shareCloseBtn) shareCloseBtn.addEventListener("click", () => hideModal(shareModal));

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
  const addSongForm = document.getElementById("add-song-form");
  const songStorageTargetInput = document.getElementById("song-storage-target");
  const databaseAudioChoiceModal = document.getElementById("database-audio-choice-modal");
  const databaseAudioChoiceServer = document.getElementById("database-audio-choice-server");
  const databaseAudioChoiceDatabase = document.getElementById("database-audio-choice-database");

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

  function titleHintFromFileName(fileName) {
    let base = String(fileName || "").trim();
    if (!base) return "";
    base = base.replace(/\.[^/.]+$/, "");
    base = base.replace(/[_]+/g, " ");
    base = base.replace(/\s+/g, " ").trim();
    base = base.replace(/^\d+\s*[-_.\)]\s*/, "").trim();
    return base;
  }

  async function runLyricsLookupFromForm({ keepLoading = false, requireArtist = true, fallbackTitle = "", forceArtistEmpty = false } = {}) {
    let title = songTitleInput ? songTitleInput.value.trim() : "";
    let artist = songArtistInput ? songArtistInput.value.trim() : "";
    if (!title && fallbackTitle) {
      title = String(fallbackTitle || "").trim();
    }
    if (forceArtistEmpty) {
      artist = "";
    }
    if (!title || (requireArtist && !artist)) {
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
        const hasId3Tags = Boolean(tags.title || tags.artist || tags.genre || tags.lyrics);

        if (!hasId3Tags) {
          const fileHint = titleHintFromFileName(file.name || "");
          if (songTitleInput) {
            songTitleInput.value = fileHint || "";
          }
          if (id3Status) {
            id3Status.textContent = i18n.appTagsFail || "No ID3 tags found.";
          }
          if (lyricsStatus) {
            lyricsStatus.textContent = i18n.appLyricsSearchingOnline || "Searching subtitles online...";
          }
          updateRetryLyricsButtonState();
          showLyricsLoading(i18n.appLyricsLoadingStepOnline || "Searching subtitles online...");
          await runLyricsLookupFromForm({
            keepLoading: true,
            requireArtist: false,
            fallbackTitle: fileHint,
            forceArtistEmpty: true,
          });
          return;
        }
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


  function jsonHeaders() {
    return {
      "X-Requested-With": "XMLHttpRequest",
      Accept: "application/json",
    };
  }

  function setVoteButtonActive(button, active) {
    if (!button) return;
    button.classList.add("btn");
    button.classList.toggle("secondary", !active);
  }

  function applySongVotesState(data) {
    const root = document.getElementById("song-votes-root");
    if (!root || !data) return;
    const likeCount = root.querySelector(".song-like-count");
    const dislikeCount = root.querySelector(".song-dislike-count");
    if (likeCount && Number.isFinite(Number(data.likes))) likeCount.textContent = String(data.likes);
    if (dislikeCount && Number.isFinite(Number(data.dislikes))) dislikeCount.textContent = String(data.dislikes);

    const userVote = Number(data.user_vote || 0);
    const canVote = root.getAttribute("data-can-vote") === "1";
    const likeBtn = root.querySelector('button[data-vote="1"]');
    const dislikeBtn = root.querySelector('button[data-vote="-1"]');
    if (!canVote) {
      if (likeBtn) likeBtn.disabled = true;
      if (dislikeBtn) dislikeBtn.disabled = true;
      return;
    }
    setVoteButtonActive(likeBtn, userVote === 1);
    setVoteButtonActive(dislikeBtn, userVote === -1);
  }

  function applyTotalPlaysState(totalPlays) {
    const node = document.getElementById("song-total-plays");
    if (!node || !Number.isFinite(Number(totalPlays))) return;
    const template = i18n.songTotalPlaysTemplate || "Total plays: {count}";
    node.textContent = template.replace("{count}", String(totalPlays));
  }

  async function refreshSongStats() {
    const root = document.getElementById("song-votes-root");
    if (!root) return false;
    const statsUrl = root.getAttribute("data-song-stats-url");
    if (!statsUrl) return false;

    try {
      const res = await fetch(statsUrl, {
        credentials: "same-origin",
        cache: "no-store",
        headers: jsonHeaders(),
      });
      if (!res.ok) return false;
      const data = await res.json();
      if (!data || !data.ok) return false;
      applySongVotesState(data);
      applyTotalPlaysState(data.total_plays);
      return true;
    } catch (_e) {
      return false;
    }
  }

  function getCommentsRoot() {
    return document.getElementById("song-comments-root");
  }

  function replaceCommentsRoot(html) {
    const current = getCommentsRoot();
    if (!current || !html) return false;
    const parser = new DOMParser();
    const doc = parser.parseFromString(String(html), "text/html");
    const next = doc.getElementById("song-comments-root");
    if (!next) return false;
    current.replaceWith(next);
    return true;
  }

  async function refreshCommentsFragment(commentsPage, silent = false) {
    const root = getCommentsRoot();
    if (!root) return false;
    const fragmentUrl = root.getAttribute("data-comments-fragment-url");
    if (!fragmentUrl) return false;

    const page = String(commentsPage || root.getAttribute("data-comments-page") || "1");
    const url = new URL(fragmentUrl, window.location.origin);
    url.searchParams.set("comments_page", page);

    try {
      const res = await fetch(url.toString(), {
        credentials: "same-origin",
        cache: "no-store",
        headers: jsonHeaders(),
      });
      const data = res.ok ? await res.json() : null;
      if (!res.ok || !data || !data.ok) {
        if (!silent) showClientNotice((data && data.message) || "Unable to refresh comments.", "danger");
        return false;
      }
      return replaceCommentsRoot(data.html);
    } catch (_e) {
      if (!silent) showClientNotice("Unable to refresh comments.", "danger");
      return false;
    }
  }

  function applyCommentVoteState(data) {
    if (!data || !data.comment_id) return;
    const root = getCommentsRoot();
    if (!root) return;
    const rows = Array.from(root.querySelectorAll("[data-comment-id]"));
    const row = rows.find((node) => node.getAttribute("data-comment-id") === String(data.comment_id));
    if (!row) return;

    const likeCount = row.querySelector(".comment-like-count");
    const dislikeCount = row.querySelector(".comment-dislike-count");
    if (likeCount && Number.isFinite(Number(data.likes))) likeCount.textContent = String(data.likes);
    if (dislikeCount && Number.isFinite(Number(data.dislikes))) dislikeCount.textContent = String(data.dislikes);

    const userVote = Number(data.user_vote || 0);
    setVoteButtonActive(row.querySelector('button[data-vote="1"]'), userVote === 1);
    setVoteButtonActive(row.querySelector('button[data-vote="-1"]'), userVote === -1);
  }

  function setFormDisabled(form, disabled) {
    if (!form) return;
    form.querySelectorAll("button, input, select, textarea").forEach((el) => {
      if (el.type === "hidden") return;
      el.disabled = disabled;
    });
  }

  function resetSongStorageChoice() {
    if (songStorageTargetInput) {
      songStorageTargetInput.value = "server";
    }
    if (addSongForm) {
      delete addSongForm.dataset.storageChoiceConfirmed;
    }
  }

  function addSongWantsStorageChoice() {
    if (!addSongForm || !databaseAudioChoiceModal || !songStorageTargetInput) return false;
    if (addSongForm.dataset.dbStorageEnabled !== "1" || addSongForm.dataset.dbStorageAllowed !== "1") return false;
    if (addSongForm.dataset.storageChoiceConfirmed === "1") return false;

    const visibilityField = document.getElementById(addSongForm.dataset.privateVisibility || "visibility-select");
    if (!visibilityField || visibilityField.value !== "public") return false;

    const fileField = document.getElementById(addSongForm.dataset.sourceFile || "song-file-input");
    if (!fileField || !fileField.files || !fileField.files.length) return false;

    return true;
  }

  function submitAddSongWithStorageTarget(target) {
    if (!addSongForm || !songStorageTargetInput) return;
    songStorageTargetInput.value = target === "database" ? "database" : "server";
    addSongForm.dataset.storageChoiceConfirmed = "1";
    hideModal(databaseAudioChoiceModal);
    if (typeof addSongForm.requestSubmit === "function") addSongForm.requestSubmit();
    else addSongForm.submit();
  }

  if (addSongForm) {
    resetSongStorageChoice();

    addSongForm.addEventListener("submit", async (event) => {
      if (event.defaultPrevented) return;
      if (!addSongWantsStorageChoice()) return;
      const ok = await validateForm(addSongForm);
      if (!ok) return;
      event.preventDefault();
      showModal(databaseAudioChoiceModal);
    });

    [songFileInput, songArtistInput, songTitleInput, songGenreInput].forEach((field) => {
      if (!field) return;
      field.addEventListener("change", resetSongStorageChoice);
      field.addEventListener("input", resetSongStorageChoice);
    });

    const visibilityField = document.getElementById(addSongForm.dataset.privateVisibility || "visibility-select");
    if (visibilityField) {
      visibilityField.addEventListener("change", () => {
        resetSongStorageChoice();
      });
    }

    const urlField = document.getElementById(addSongForm.dataset.sourceUrl || "song-url-input");
    if (urlField) {
      urlField.addEventListener("input", resetSongStorageChoice);
      urlField.addEventListener("change", resetSongStorageChoice);
    }
  }

  if (databaseAudioChoiceServer) {
    databaseAudioChoiceServer.addEventListener("click", () => {
      submitAddSongWithStorageTarget("server");
    });
  }

  if (databaseAudioChoiceDatabase) {
    databaseAudioChoiceDatabase.addEventListener("click", () => {
      submitAddSongWithStorageTarget("database");
    });
  }

  document.addEventListener("submit", async (event) => {
    if (event.defaultPrevented) return;

    const songVoteForm = event.target.closest("form[data-song-vote-form]");
    if (songVoteForm) {
      const voteRoot = document.getElementById("song-votes-root");
      if (voteRoot && voteRoot.getAttribute("data-can-vote") !== "1") {
        event.preventDefault();
        showClientNotice(i18n.authRequired || "Login required.", "warning");
        return;
      }
      event.preventDefault();
      setFormDisabled(songVoteForm, true);
      try {
        const res = await fetch(songVoteForm.action, {
          method: "POST",
          credentials: "same-origin",
          headers: jsonHeaders(),
          body: new FormData(songVoteForm),
        });
        const data = res.ok ? await res.json() : null;
        if (!res.ok || !data || !data.ok) {
          showClientNotice((data && data.message) || "Unable to update reaction.", "danger");
          return;
        }
        applySongVotesState(data);
      } catch (_e) {
        showClientNotice("Unable to update reaction.", "danger");
      } finally {
        setFormDisabled(songVoteForm, false);
      }
      return;
    }

    const commentVoteForm = event.target.closest("form[data-comment-vote-form]");
    if (commentVoteForm) {
      event.preventDefault();
      setFormDisabled(commentVoteForm, true);
      try {
        const res = await fetch(commentVoteForm.action, {
          method: "POST",
          credentials: "same-origin",
          headers: jsonHeaders(),
          body: new FormData(commentVoteForm),
        });
        const data = res.ok ? await res.json() : null;
        if (!res.ok || !data || !data.ok) {
          showClientNotice((data && data.message) || "Unable to update reaction.", "danger");
          return;
        }
        applyCommentVoteState(data);
      } catch (_e) {
        showClientNotice("Unable to update reaction.", "danger");
      } finally {
        setFormDisabled(commentVoteForm, false);
      }
      return;
    }

    const commentsForm = event.target.closest("form[data-ajax-comment-form]");
    if (commentsForm) {
      event.preventDefault();
      const root = getCommentsRoot();
      const payload = new FormData(commentsForm);
      if (!payload.get("comments_page") && root) {
        payload.set("comments_page", root.getAttribute("data-comments-page") || "1");
      }
      setFormDisabled(commentsForm, true);
      try {
        const res = await fetch(commentsForm.action, {
          method: "POST",
          credentials: "same-origin",
          headers: jsonHeaders(),
          body: payload,
        });
        const data = res.ok ? await res.json() : null;
        if (!res.ok || !data || !data.ok) {
          showClientNotice((data && data.message) || "Unable to save comment.", "danger");
          return;
        }
        replaceCommentsRoot(data.html);
      } catch (_e) {
        showClientNotice("Unable to save comment.", "danger");
      } finally {
        setFormDisabled(commentsForm, false);
      }
    }
  });

  document.addEventListener("click", (event) => {
    const editOpenBtn = event.target.closest(".comment-edit-toggle");
    if (editOpenBtn) {
      const root = getCommentsRoot();
      const targetId = editOpenBtn.getAttribute("data-edit-target");
      if (!root || !targetId) return;
      root.querySelectorAll(".comment-edit-form").forEach((form) => {
        form.classList.add("hidden");
      });
      const target = document.getElementById(targetId);
      if (target) {
        target.classList.remove("hidden");
        const input = target.querySelector('input[name="content"], textarea[name="content"]');
        if (input && typeof input.focus === "function") input.focus();
      }
      return;
    }

    const editCancelBtn = event.target.closest(".comment-edit-cancel");
    if (editCancelBtn) {
      const targetId = editCancelBtn.getAttribute("data-edit-target");
      const target = targetId ? document.getElementById(targetId) : null;
      if (target) target.classList.add("hidden");
      return;
    }

    const commentPageLink = event.target.closest("#song-comments-root .pagination a");
    if (commentPageLink) {
      event.preventDefault();
      const url = new URL(commentPageLink.href, window.location.origin);
      const page = url.searchParams.get("comments_page") || "1";
      refreshCommentsFragment(page);
    }
  });

  function initSongDetailRealtime() {
    const hasSongVotes = Boolean(document.getElementById("song-votes-root"));
    const hasComments = Boolean(getCommentsRoot());
    if (!hasSongVotes && !hasComments) return;

    if (hasSongVotes) {
      refreshSongStats();
      let statsPending = false;
      setInterval(() => {
        if (statsPending) return;
        statsPending = true;
        refreshSongStats().finally(() => {
          statsPending = false;
        });
      }, 12000);
    }

    if (hasComments) {
      let commentsPending = false;
      setInterval(() => {
        const root = getCommentsRoot();
        if (!root || commentsPending) return;
        if (root.contains(document.activeElement)) return;
        commentsPending = true;
        const page = root.getAttribute("data-comments-page") || "1";
        refreshCommentsFragment(page, true).finally(() => {
          commentsPending = false;
        });
      }, 15000);
    }
  }

  function visibilityLabelForSong(list, visibility) {
    if (visibility === "private") return list.getAttribute("data-vis-private") || "Private";
    if (visibility === "unlisted") return list.getAttribute("data-vis-unlisted") || "Unlisted";
    return list.getAttribute("data-vis-public") || "Public";
  }

  function ensurePageSongQueue(song) {
    if (!Array.isArray(window.PAGE_SONG_OBJECTS)) window.PAGE_SONG_OBJECTS = [];
    const queue = window.PAGE_SONG_OBJECTS;
    const songObj = {
      id: song.id,
      title: song.title || "",
      artist: song.artist || "",
      url: song.url || "",
      detail_url: song.detail_url || "",
      source_type: song.source_type || "",
      source_url: song.source_url || "",
      external_provider: song.external_provider || "",
      youtube_video_id: song.youtube_video_id || "",
      playback_mode: song.playback_mode || "",
      is_available: song.is_available !== false,
      is_audio_playable: song.is_audio_playable !== false,
    };
    const existingIndex = queue.findIndex((row) => String(row.id) === String(songObj.id));
    if (existingIndex >= 0) queue.splice(existingIndex, 1);
    queue.unshift(songObj);
    if (queue.length > 50) queue.length = 50;
  }

  function buildLiveSongItem(song, list) {
    const li = document.createElement("li");
    li.setAttribute("data-song-id", song.id || "");
    li.setAttribute("data-created-ts", String(song.created_ts || 0));
    if (song.is_available === false) li.classList.add("song-unavailable");

    const infoDiv = document.createElement("div");
    const detailsLink = document.createElement("a");
    detailsLink.href = song.detail_url || "#";
    const strong = document.createElement("strong");
    strong.textContent = song.title || "";
    detailsLink.appendChild(strong);
    infoDiv.appendChild(detailsLink);

    const artistLine = document.createElement("p");
    const artist = song.artist || "";
    const genre = song.genre || "";
    artistLine.textContent = genre ? `${artist} - ${genre}` : artist;
    infoDiv.appendChild(artistLine);

    const badge = document.createElement("span");
    badge.className = "badge";
    badge.textContent = visibilityLabelForSong(list, song.visibility || "public");
    infoDiv.appendChild(badge);
    if (song.is_available === false) {
      const unavailable = document.createElement("span");
      unavailable.className = "badge";
      unavailable.textContent = (window.I18N && window.I18N.songUnavailable) || "Unavailable";
      infoDiv.appendChild(unavailable);
    }

    if (song.visibility === "private") {
      const shared = document.createElement("span");
      shared.className = "muted small";
      const template = list.getAttribute("data-shared-template") || "{count}";
      shared.textContent = template.replace("{count}", String(song.shared_count || 0));
      infoDiv.appendChild(shared);
    }

    const actions = document.createElement("div");
    actions.className = "row-actions";

    const playBtn = document.createElement("button");
    playBtn.type = "button";
    playBtn.className = "play-one";
    playBtn.setAttribute("data-context", "auto");
    playBtn.textContent = list.getAttribute("data-play-label") || "Play";
    playBtn.setAttribute(
      "data-song",
      JSON.stringify({
        id: song.id || "",
        title: song.title || "",
        artist: song.artist || "",
        url: song.url || "",
        detail_url: song.detail_url || "",
        source_type: song.source_type || "",
        source_url: song.source_url || "",
        external_provider: song.external_provider || "",
        youtube_video_id: song.youtube_video_id || "",
        playback_mode: song.playback_mode || "",
        is_available: song.is_available !== false,
        is_audio_playable: song.is_audio_playable !== false,
      })
    );
    actions.appendChild(playBtn);

    const detailsBtn = document.createElement("a");
    detailsBtn.className = "btn secondary";
    detailsBtn.href = song.detail_url || "#";
    detailsBtn.textContent = list.getAttribute("data-details-label") || "Details";
    actions.appendChild(detailsBtn);

    if (song.can_delete) {
      const deleteForm = document.createElement("form");
      deleteForm.method = "post";
      deleteForm.action = `/songs/${encodeURIComponent(song.id || "")}/delete`;
      deleteForm.className = "delete-song-form";
      const deleteBtn = document.createElement("button");
      deleteBtn.type = "submit";
      deleteBtn.className = "btn-danger";
      deleteBtn.textContent = list.getAttribute("data-delete-label") || "Delete";
      deleteForm.appendChild(deleteBtn);
      actions.appendChild(deleteForm);
    }

    li.appendChild(infoDiv);
    li.appendChild(actions);
    return li;
  }

  function initHomeLiveSongs() {
    const list = document.getElementById("home-latest-list");
    if (!list) return;
    if (list.getAttribute("data-live-enabled") !== "1") return;
    const liveUrl = list.getAttribute("data-live-url");
    if (!liveUrl) return;

    let since = Number.parseFloat(list.getAttribute("data-live-since") || "0");
    if (!Number.isFinite(since)) since = 0;

    const knownIds = new Set(
      Array.from(list.querySelectorAll("li[data-song-id]"))
        .map((node) => node.getAttribute("data-song-id"))
        .filter((value) => Boolean(value))
    );

    let pending = false;
    const pollLiveSongs = async () => {
      if (pending) return;
      pending = true;
      try {
        const query = list.getAttribute("data-query") || "";
        const sort = list.getAttribute("data-sort") || "date";
        const page = list.getAttribute("data-page") || "1";
        const url = new URL(liveUrl, window.location.origin);
        url.searchParams.set("q", query);
        url.searchParams.set("sort", sort);
        url.searchParams.set("page", page);
        url.searchParams.set("since", String(since));

        const res = await fetch(url.toString(), {
          credentials: "same-origin",
          cache: "no-store",
          headers: jsonHeaders(),
        });
        const data = res.ok ? await res.json() : null;
        if (!res.ok || !data || !data.ok) return;

        const rows = Array.isArray(data.items) ? data.items : [];
        let inserted = 0;
        rows.forEach((song) => {
          const sid = String(song.id || "");
          if (!sid || knownIds.has(sid)) return;
          const li = buildLiveSongItem(song, list);
          list.prepend(li);
          knownIds.add(sid);
          ensurePageSongQueue(song);
          inserted += 1;
        });

        while (list.children.length > 50) {
          const tail = list.lastElementChild;
          if (!tail) break;
          const sid = tail.getAttribute("data-song-id");
          if (sid) knownIds.delete(sid);
          tail.remove();
        }

        if (inserted > 0) {
          const totalNode = document.getElementById("home-total-count");
          if (totalNode) {
            const current = Number.parseInt(totalNode.textContent || "0", 10);
            if (Number.isFinite(current)) totalNode.textContent = String(current + inserted);
          }
        }

        const nextSince = Number.parseFloat(String(data.next_since || since));
        if (Number.isFinite(nextSince)) {
          since = Math.max(since, nextSince);
          list.setAttribute("data-live-since", String(since));
        }
      } catch (_e) {
      } finally {
        pending = false;
      }
    };

    setInterval(pollLiveSongs, 10000);
  }

  initSongDetailRealtime();
  initHomeLiveSongs();
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

    if (!message && field.dataset.blockDisposable === "1" && field.value.trim() && isDisposableEmail(field.value)) {
      message = i18n.validationBackupEmailDisposable || "Temporary email addresses are not allowed here.";
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

  [confirmModal, reportModal, userPickerModal, tempEmailModal, lyricsCandidateModal, shareModal, profileSubscribersModal, databaseAudioChoiceModal].forEach((modal) => {
    if (!modal) return;
    modal.addEventListener("click", (event) => {
      if (event.target === modal) hideModal(modal);
    });
  });

  window.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    setMenuOpen(false);
    hideModal(confirmModal);
    hideModal(reportModal);
    hideModal(userPickerModal);
    hideModal(tempEmailModal);
    hideModal(lyricsCandidateModal);
    hideModal(shareModal);
    hideModal(profileSubscribersModal);
    hideModal(databaseAudioChoiceModal);
    closeNotificationsPanel();
  });

  const recapRoot = document.querySelector("[data-recap-root]");
  if (recapRoot) {
    const recapTrack = recapRoot.querySelector("[data-recap-track]");
    const recapSlides = Array.from(recapRoot.querySelectorAll("[data-recap-slide]"));
    const recapPrev = recapRoot.querySelector("[data-recap-prev]");
    const recapNext = recapRoot.querySelector("[data-recap-next]");
    const recapProgress = Array.from(recapRoot.querySelectorAll("[data-recap-progress] span"));
    const recapClose = recapRoot.querySelector("[data-recap-close]");
    const recapAutoplayToggle = recapRoot.querySelector("[data-recap-toggle-autoplay]");
    const recapAutoplayPlayingLabel = recapAutoplayToggle ? recapAutoplayToggle.querySelector("[data-when-playing]") : null;
    const recapAutoplayPausedLabel = recapAutoplayToggle ? recapAutoplayToggle.querySelector("[data-when-paused]") : null;
    const recapSoundtrack = document.getElementById("recap-soundtrack-audio");
    const recapSoundtrackToggle = recapRoot.querySelector("[data-recap-soundtrack-toggle]");
    const recapSoundtrackMute = recapRoot.querySelector("[data-recap-soundtrack-mute]");
    const recapSoundtrackPlaying = recapSoundtrackToggle ? recapSoundtrackToggle.querySelector("[data-soundtrack-playing]") : null;
    const recapSoundtrackPaused = recapSoundtrackToggle ? recapSoundtrackToggle.querySelector("[data-soundtrack-paused]") : null;
    const recapSoundtrackMuted = recapSoundtrackMute ? recapSoundtrackMute.querySelector("[data-soundtrack-muted]") : null;
    const recapSoundtrackUnmuted = recapSoundtrackMute ? recapSoundtrackMute.querySelector("[data-soundtrack-unmuted]") : null;
    let recapIndex = 0;
    let recapTouch = null;
    let recapAutoplayEnabled = true;
    let recapTimeout = null;
    let recapFrame = null;
    let recapCountFrame = null;
    let recapPauseOnHide = false;
    let recapTimerStartedAt = 0;
    let recapRemainingMs = 0;
    let soundtrackNeedsGesture = false;
    const defaultRecapDuration = Math.max(2200, Number(recapRoot.getAttribute("data-recap-autoplay-ms") || "6800"));
    const recapNumberFormatLocale = document.documentElement.lang || "fr";
    const recapHomeUrl = String(recapRoot.getAttribute("data-recap-home-url") || "/").trim() || "/";
    const recapNextLabel = recapNext ? String(recapNext.getAttribute("data-next-label") || "").trim() : "";
    const recapFinishLabel = recapNext ? String(recapNext.getAttribute("data-finish-label") || recapNextLabel || "").trim() : "";

    function recapExit() {
      const exitUrl = String(recapRoot.getAttribute("data-recap-exit-url") || "/").trim() || "/";
      window.location.assign(exitUrl);
    }

    function recapGoHome() {
      window.location.assign(recapHomeUrl);
    }

    function slideDuration(index) {
      const slide = recapSlides[index];
      const perSlide = Number(slide && slide.getAttribute("data-recap-slide-duration"));
      return Number.isFinite(perSlide) && perSlide > 0 ? perSlide : defaultRecapDuration;
    }

    function clearRecapTimer() {
      if (recapTimeout) {
        clearTimeout(recapTimeout);
        recapTimeout = null;
      }
      if (recapFrame) {
        cancelAnimationFrame(recapFrame);
        recapFrame = null;
      }
    }

    function renderRecapProgress(currentPercent = 0) {
      recapProgress.forEach((dot, index) => {
        let fill = 0;
        if (index < recapIndex) fill = 100;
        else if (index === recapIndex) fill = Math.max(0, Math.min(100, currentPercent));
        dot.style.setProperty("--recap-fill", `${fill}%`);
        dot.classList.toggle("active", index <= recapIndex);
        dot.classList.toggle("current", index === recapIndex);
      });
    }

    function syncAutoplayControl() {
      if (!recapAutoplayToggle) return;
      recapAutoplayToggle.setAttribute("aria-pressed", recapAutoplayEnabled ? "true" : "false");
      if (recapAutoplayPlayingLabel) recapAutoplayPlayingLabel.classList.toggle("hidden", !recapAutoplayEnabled);
      if (recapAutoplayPausedLabel) recapAutoplayPausedLabel.classList.toggle("hidden", recapAutoplayEnabled);
    }

    function updateSoundtrackUi() {
      if (!recapSoundtrack) return;
      recapRoot.classList.toggle("recap-soundtrack-live", !recapSoundtrack.paused);
      recapRoot.classList.toggle("recap-soundtrack-needs-gesture", soundtrackNeedsGesture);
      if (recapSoundtrackToggle) {
        recapSoundtrackToggle.setAttribute("aria-pressed", recapSoundtrack.paused ? "false" : "true");
      }
      if (recapSoundtrackMute) {
        recapSoundtrackMute.setAttribute("aria-pressed", recapSoundtrack.muted ? "true" : "false");
      }
      if (recapSoundtrackPlaying) recapSoundtrackPlaying.classList.toggle("hidden", recapSoundtrack.paused);
      if (recapSoundtrackPaused) recapSoundtrackPaused.classList.toggle("hidden", !recapSoundtrack.paused);
      if (recapSoundtrackMuted) recapSoundtrackMuted.classList.toggle("hidden", !recapSoundtrack.muted);
      if (recapSoundtrackUnmuted) recapSoundtrackUnmuted.classList.toggle("hidden", recapSoundtrack.muted);
    }

    async function attemptSoundtrackPlayback(fromGesture = false) {
      if (!recapSoundtrack) return false;
      if (fromGesture) soundtrackNeedsGesture = false;
      try {
        await recapSoundtrack.play();
        soundtrackNeedsGesture = false;
        updateSoundtrackUi();
        return true;
      } catch (_err) {
        soundtrackNeedsGesture = true;
        updateSoundtrackUi();
        return false;
      }
    }

    function tickRecapProgress() {
      if (!recapAutoplayEnabled) return;
      const duration = slideDuration(recapIndex);
      const elapsed = Math.max(0, performance.now() - recapTimerStartedAt);
      const used = Math.max(0, Math.min(duration, duration - recapRemainingMs + elapsed));
      renderRecapProgress(duration > 0 ? (used / duration) * 100 : 0);
      if (elapsed < recapRemainingMs - 18) {
        recapFrame = requestAnimationFrame(tickRecapProgress);
      }
    }

    function scheduleRecapAutoplay() {
      clearRecapTimer();
      renderRecapProgress(0);
      if (!recapAutoplayEnabled || !recapSlides.length) return;
      if (recapIndex >= recapSlides.length - 1) {
        recapAutoplayEnabled = false;
        syncAutoplayControl();
        renderRecapProgress(100);
        return;
      }
      recapRemainingMs = recapRemainingMs > 0 ? recapRemainingMs : slideDuration(recapIndex);
      recapTimerStartedAt = performance.now();
      recapTimeout = setTimeout(() => {
        recapRemainingMs = slideDuration(recapIndex + 1);
        moveRecap(1, { restartAutoplay: true });
      }, recapRemainingMs);
      recapFrame = requestAnimationFrame(tickRecapProgress);
    }

    function pauseRecapAutoplay() {
      if (!recapAutoplayEnabled) return;
      const elapsed = Math.max(0, performance.now() - recapTimerStartedAt);
      recapRemainingMs = Math.max(220, recapRemainingMs - elapsed);
      recapAutoplayEnabled = false;
      clearRecapTimer();
      syncAutoplayControl();
      renderRecapProgress(((slideDuration(recapIndex) - recapRemainingMs) / slideDuration(recapIndex)) * 100);
    }

    function resumeRecapAutoplay() {
      if (recapAutoplayEnabled) return;
      recapAutoplayEnabled = true;
      if (!recapRemainingMs || recapRemainingMs <= 0) recapRemainingMs = slideDuration(recapIndex);
      syncAutoplayControl();
      scheduleRecapAutoplay();
    }

    function renderRecap() {
      if (!recapTrack || !recapSlides.length) return;
      recapTrack.style.transform = `translateX(-${recapIndex * 100}%)`;
      recapSlides.forEach((slide, index) => {
        slide.classList.toggle("active", index === recapIndex);
        if (index !== recapIndex) {
          const content = slide.querySelector(".recap-slide__content");
          if (content) content.scrollTop = 0;
        }
      });
      if (recapPrev) recapPrev.disabled = recapIndex <= 0;
      if (recapNext) {
        const isLastSlide = recapIndex >= recapSlides.length - 1;
        recapNext.disabled = false;
        recapNext.textContent = isLastSlide ? (recapFinishLabel || recapNext.textContent) : (recapNextLabel || recapNext.textContent);
        recapNext.setAttribute("aria-label", recapNext.textContent);
      }
      recapRoot.style.setProperty("--recap-index", String(recapIndex));
      renderRecapProgress(0);
      animateRecapCounters(recapSlides[recapIndex]);
    }

    function animateRecapCounters(slide) {
      if (!slide) return;
      if (recapCountFrame) {
        cancelAnimationFrame(recapCountFrame);
        recapCountFrame = null;
      }
      const counters = Array.from(slide.querySelectorAll("[data-recap-count]"));
      if (!counters.length) return;
      const formatterCache = new Map();
      const makeFormatter = (decimals) => {
        const key = String(decimals || 0);
        if (!formatterCache.has(key)) {
          formatterCache.set(key, new Intl.NumberFormat(recapNumberFormatLocale, {
            minimumFractionDigits: decimals,
            maximumFractionDigits: decimals,
          }));
        }
        return formatterCache.get(key);
      };
      const items = counters.map((node) => ({
        node,
        target: Number(node.getAttribute("data-recap-count") || "0"),
        decimals: Math.max(0, Number(node.getAttribute("data-recap-decimals") || "0")),
        suffix: String(node.getAttribute("data-recap-suffix") || ""),
      }));
      const startedAt = performance.now();
      const duration = 920;

      const tick = (now) => {
        const progress = Math.min(1, (now - startedAt) / duration);
        const eased = 1 - Math.pow(1 - progress, 3);
        items.forEach((item) => {
          const currentValue = item.target * eased;
          const rounded = item.decimals > 0 ? currentValue.toFixed(item.decimals) : String(Math.round(currentValue));
          const numeric = Number(rounded);
          item.node.textContent = `${makeFormatter(item.decimals).format(Number.isFinite(numeric) ? numeric : 0)}${item.suffix}`;
        });
        if (progress < 1) {
          recapCountFrame = requestAnimationFrame(tick);
        }
      };
      recapCountFrame = requestAnimationFrame(tick);
    }

    function moveRecap(delta, options = {}) {
      const nextIndex = Math.max(0, Math.min(recapSlides.length - 1, recapIndex + delta));
      if (nextIndex === recapIndex) return;
      recapIndex = nextIndex;
      recapRemainingMs = slideDuration(recapIndex);
      renderRecap();
      if (options.restartAutoplay !== false && recapAutoplayEnabled) {
        scheduleRecapAutoplay();
      }
    }

    if (recapPrev) recapPrev.addEventListener("click", () => moveRecap(-1, { restartAutoplay: true }));
    if (recapNext) {
      recapNext.addEventListener("click", () => {
        if (recapIndex >= recapSlides.length - 1) {
          recapGoHome();
          return;
        }
        moveRecap(1, { restartAutoplay: true });
      });
    }
    if (recapClose) recapClose.addEventListener("click", recapExit);
    if (recapAutoplayToggle) {
      recapAutoplayToggle.addEventListener("click", () => {
        if (recapAutoplayEnabled) pauseRecapAutoplay();
        else resumeRecapAutoplay();
      });
    }
    if (recapSoundtrackToggle && recapSoundtrack) {
      recapSoundtrackToggle.addEventListener("click", async () => {
        if (recapSoundtrack.paused) {
          await attemptSoundtrackPlayback(true);
        } else {
          recapSoundtrack.pause();
          updateSoundtrackUi();
        }
      });
    }
    if (recapSoundtrackMute && recapSoundtrack) {
      recapSoundtrackMute.addEventListener("click", () => {
        recapSoundtrack.muted = !recapSoundtrack.muted;
        updateSoundtrackUi();
      });
    }
    if (recapSoundtrack) {
      recapSoundtrack.volume = 0.34;
      recapSoundtrack.addEventListener("play", updateSoundtrackUi);
      recapSoundtrack.addEventListener("pause", updateSoundtrackUi);
      recapSoundtrack.addEventListener("volumechange", updateSoundtrackUi);
      window.setTimeout(() => {
        attemptSoundtrackPlayback(false).catch(() => {});
      }, 260);
      const soundtrackGestureStart = () => {
        if (!soundtrackNeedsGesture || !recapSoundtrack.paused) return;
        attemptSoundtrackPlayback(true).catch(() => {});
      };
      window.addEventListener("pointerdown", soundtrackGestureStart, { passive: true });
      window.addEventListener("keydown", soundtrackGestureStart);
      updateSoundtrackUi();
    }

    recapRoot.addEventListener("pointerdown", (event) => {
      if (event.pointerType === "mouse" && event.button !== 0) return;
      recapTouch = { startX: event.clientX, startY: event.clientY };
    }, { passive: true });

    recapRoot.addEventListener("pointermove", (event) => {
      const rect = recapRoot.getBoundingClientRect();
      const x = Math.max(0, Math.min(100, ((event.clientX - rect.left) / Math.max(rect.width, 1)) * 100));
      const y = Math.max(0, Math.min(100, ((event.clientY - rect.top) / Math.max(rect.height, 1)) * 100));
      recapRoot.style.setProperty("--recap-pointer-x", `${x}%`);
      recapRoot.style.setProperty("--recap-pointer-y", `${y}%`);
    }, { passive: true });

    recapRoot.addEventListener("pointerup", (event) => {
      if (!recapTouch) return;
      const dx = event.clientX - recapTouch.startX;
      const dy = event.clientY - recapTouch.startY;
      recapTouch = null;
      if (Math.abs(dy) > 100 && Math.abs(dy) > Math.abs(dx) && dy > 0 && event.clientY < 180) {
        recapExit();
        return;
      }
      if (Math.abs(dx) < 50 || Math.abs(dx) < Math.abs(dy)) return;
      moveRecap(dx < 0 ? 1 : -1, { restartAutoplay: true });
    }, { passive: true });

    window.addEventListener("keydown", (event) => {
      if (!document.body.contains(recapRoot)) return;
      if (event.key === "ArrowRight") moveRecap(1, { restartAutoplay: true });
      if (event.key === "ArrowLeft") moveRecap(-1, { restartAutoplay: true });
      if (event.key === "Escape") recapExit();
      if (event.key === " ") {
        event.preventDefault();
        if (recapAutoplayEnabled) pauseRecapAutoplay();
        else resumeRecapAutoplay();
      }
    });

    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "hidden" && recapAutoplayEnabled) {
        recapPauseOnHide = true;
        pauseRecapAutoplay();
      } else if (document.visibilityState === "visible" && recapPauseOnHide) {
        recapPauseOnHide = false;
        resumeRecapAutoplay();
      }
    });

    recapRemainingMs = slideDuration(0);
    syncAutoplayControl();
    renderRecap();
    scheduleRecapAutoplay();
  }
})();








