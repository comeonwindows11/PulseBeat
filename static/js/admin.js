(function () {
  const cards = Array.from(document.querySelectorAll(".admin-alert-card[data-admin-alert-key]"));
  const toast = document.getElementById("admin-alert-toast");
  const toastText = document.getElementById("admin-alert-toast-text");
  const undoBtn = document.getElementById("admin-alert-toast-undo");

  if (!cards.length || !toast || !toastText || !undoBtn) return;

  const i18n = window.ADMIN_I18N || {};
  const csrfToken = String(window.CSRF_TOKEN || "").trim();
  const dismissUrl = String(toast.getAttribute("data-dismiss-url") || "").trim();
  const restoreUrl = String(toast.getAttribute("data-restore-url") || "").trim();

  let hideTimer = null;
  let pendingUndo = null;

  function clearHideTimer() {
    if (!hideTimer) return;
    window.clearTimeout(hideTimer);
    hideTimer = null;
  }

  function hideToast() {
    clearHideTimer();
    toast.classList.add("hidden");
    toast.classList.remove("error");
    undoBtn.classList.remove("hidden");
    undoBtn.disabled = false;
    pendingUndo = null;
  }

  function showToast(message, options = {}) {
    const { error = false, withUndo = false, durationMs = 3000 } = options;
    toastText.textContent = message || "";
    toast.classList.toggle("error", Boolean(error));
    undoBtn.classList.toggle("hidden", !withUndo);
    undoBtn.disabled = false;
    toast.classList.remove("hidden");
    clearHideTimer();
    if (durationMs > 0) {
      hideTimer = window.setTimeout(() => {
        hideToast();
      }, durationMs);
    }
  }

  async function postJson(url, payload) {
    const headers = { "Content-Type": "application/json" };
    if (csrfToken) headers["X-CSRF-Token"] = csrfToken;
    return fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers,
      body: JSON.stringify(payload || {}),
    });
  }

  async function dismissAlert(card) {
    const alertKey = String(card.getAttribute("data-admin-alert-key") || "").trim();
    if (!alertKey || !dismissUrl) return;
    if (card.dataset.busy === "1") return;
    card.dataset.busy = "1";

    try {
      const response = await postJson(dismissUrl, { alert_key: alertKey });
      if (!response.ok) throw new Error("dismiss_failed");

      card.classList.add("hidden");
      pendingUndo = { card, alertKey };
      showToast(i18n.alertDismissed || "Alerte masquée.", { withUndo: true, durationMs: 10000 });
    } catch (_err) {
      showToast(i18n.alertDismissFailed || "Impossible de masquer l'alerte.", { error: true, durationMs: 3500 });
    } finally {
      card.dataset.busy = "0";
    }
  }

  undoBtn.addEventListener("click", async () => {
    if (!pendingUndo || !restoreUrl) return;
    const { card, alertKey } = pendingUndo;
    undoBtn.disabled = true;
    clearHideTimer();

    try {
      const response = await postJson(restoreUrl, { alert_key: alertKey });
      if (!response.ok) throw new Error("restore_failed");
      card.classList.remove("hidden");
      showToast(i18n.alertRestored || "Alerte restaurée.", { durationMs: 3000 });
    } catch (_err) {
      showToast(i18n.alertRestoreFailed || "Impossible de restaurer l'alerte.", { error: true, durationMs: 3500 });
    }
  });

  cards.forEach((card) => {
    const closeBtn = card.querySelector(".admin-alert-dismiss-btn");
    if (!closeBtn) return;
    closeBtn.addEventListener("click", () => dismissAlert(card));
  });
})();

(function () {
  const flow = document.getElementById("platform-reset-flow");
  if (!flow) return;

  const executeUrl = String(flow.getAttribute("data-execute-url") || "").trim();
  const confirmBtn = document.getElementById("platform-reset-confirm-btn");
  const errorText = document.getElementById("platform-reset-error-text");
  const csrfToken = String(window.CSRF_TOKEN || "").trim();
  if (!confirmBtn || !executeUrl) return;

  const steps = {
    confirm: flow.querySelector('[data-step="confirm"]'),
    progress: flow.querySelector('[data-step="progress"]'),
    complete: flow.querySelector('[data-step="complete"]'),
    error: flow.querySelector('[data-step="error"]'),
  };

  function showStep(stepName) {
    Object.entries(steps).forEach(([name, node]) => {
      if (!node) return;
      node.classList.toggle("hidden", name !== stepName);
    });
  }

  confirmBtn.addEventListener("click", async () => {
    confirmBtn.disabled = true;
    showStep("progress");

    try {
      const headers = {
        "Content-Type": "application/json",
        "X-Requested-With": "XMLHttpRequest",
      };
      if (csrfToken) headers["X-CSRF-Token"] = csrfToken;

      const response = await fetch(executeUrl, {
        method: "POST",
        credentials: "same-origin",
        headers,
        body: JSON.stringify({ confirmed: true }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok || !payload.ok) {
        throw new Error(String(payload.message || "reset_failed"));
      }
      showStep("complete");
    } catch (error) {
      if (errorText) {
        errorText.textContent = error && error.message ? error.message : "Reset failed.";
      }
      showStep("error");
      confirmBtn.disabled = false;
    }
  });
})();

(function () {
  const openBtn = document.getElementById("open-db-audio-user-picker");
  const modal = document.getElementById("admin-user-picker-modal");
  const searchInput = document.getElementById("admin-user-picker-search");
  const suggestions = document.getElementById("admin-user-picker-suggestions");
  const selectedWrap = document.getElementById("admin-user-picker-selected");
  const applyBtn = document.getElementById("admin-user-picker-apply");
  const cancelBtn = document.getElementById("admin-user-picker-cancel");
  const targetInputs = document.getElementById("db-audio-allowed-users-inputs");
  const targetList = document.getElementById("db-audio-allowed-users-list");

  if (!openBtn || !modal || !searchInput || !suggestions || !selectedWrap || !applyBtn || !cancelBtn || !targetInputs || !targetList) {
    return;
  }

  const i18n = window.ADMIN_I18N || {};
  const allUsers = Array.isArray(window.ADMIN_USER_CHOICES) ? window.ADMIN_USER_CHOICES : [];
  let selected = new Map();
  let filtered = [];
  let activeIndex = -1;

  function showModal() {
    modal.classList.remove("hidden");
    modal.setAttribute("aria-hidden", "false");
  }

  function hideModal() {
    modal.classList.add("hidden");
    modal.setAttribute("aria-hidden", "true");
  }

  function renderSelected() {
    selectedWrap.innerHTML = "";
    if (!selected.size) return;
    selected.forEach((item) => {
      const pill = document.createElement("button");
      pill.type = "button";
      pill.className = "selected-user-pill";
      pill.textContent = `${item.username} (${item.email}) ×`;
      pill.addEventListener("click", () => {
        selected.delete(item.id);
        renderSelected();
        renderSuggestions();
      });
      selectedWrap.appendChild(pill);
    });
  }

  function renderSuggestions() {
    suggestions.innerHTML = "";
    if (!filtered.length) {
      const empty = document.createElement("div");
      empty.className = "autocomplete-item disabled";
      empty.textContent = i18n.userPickerNoResults || "No results.";
      suggestions.appendChild(empty);
      return;
    }
    filtered.forEach((item, index) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = `autocomplete-item${index === activeIndex ? " active" : ""}`;
      btn.textContent = `${item.username} (${item.email})`;
      btn.disabled = selected.has(item.id);
      btn.addEventListener("click", () => {
        if (btn.disabled) return;
        selected.set(item.id, item);
        searchInput.value = "";
        activeIndex = -1;
        updateFilter();
      });
      suggestions.appendChild(btn);
    });
  }

  function updateFilter() {
    const q = String(searchInput.value || "").trim().toLowerCase();
    filtered = allUsers.filter((item) => {
      const haystack = `${item.username || ""} ${item.email || ""}`.toLowerCase();
      return !q || haystack.includes(q);
    });
    activeIndex = filtered.length ? 0 : -1;
    renderSelected();
    renderSuggestions();
  }

  function loadSelectedFromForm() {
    selected = new Map();
    const ids = Array.from(targetInputs.querySelectorAll('input[name="database_audio_storage_allowed_user_ids"]')).map((input) => String(input.value || "").trim()).filter(Boolean);
    const pills = Array.from(targetList.querySelectorAll(".selected-user-pill"));
    ids.forEach((id, index) => {
      const existing = allUsers.find((row) => String(row.id) === id);
      if (existing) {
        selected.set(id, existing);
        return;
      }
      const label = pills[index] ? pills[index].textContent || id : id;
      const match = /^(.*)\s\((.*)\)/.exec(label);
      selected.set(id, {
        id,
        username: match ? match[1] : label,
        email: match ? match[2] : "",
      });
    });
  }

  function persistSelection() {
    targetInputs.innerHTML = "";
    targetList.innerHTML = "";
    selected.forEach((item) => {
      const hidden = document.createElement("input");
      hidden.type = "hidden";
      hidden.name = "database_audio_storage_allowed_user_ids";
      hidden.value = item.id;
      targetInputs.appendChild(hidden);

      const pill = document.createElement("span");
      pill.className = "selected-user-pill";
      pill.textContent = `${item.username} (${item.email})`;
      targetList.appendChild(pill);
    });
  }

  openBtn.addEventListener("click", () => {
    loadSelectedFromForm();
    searchInput.value = "";
    updateFilter();
    showModal();
    window.setTimeout(() => {
      searchInput.focus();
    }, 30);
  });

  cancelBtn.addEventListener("click", () => {
    hideModal();
  });

  applyBtn.addEventListener("click", () => {
    persistSelection();
    hideModal();
  });

  searchInput.addEventListener("input", updateFilter);
  searchInput.addEventListener("keydown", (event) => {
    if (!filtered.length) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      activeIndex = Math.min(activeIndex + 1, filtered.length - 1);
      renderSuggestions();
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      activeIndex = Math.max(activeIndex - 1, 0);
      renderSuggestions();
    } else if (event.key === "Enter") {
      event.preventDefault();
      const item = filtered[activeIndex];
      if (!item || selected.has(item.id)) return;
      selected.set(item.id, item);
      searchInput.value = "";
      updateFilter();
    } else if (event.key === "Escape") {
      hideModal();
    }
  });

  modal.addEventListener("click", (event) => {
    if (event.target === modal) hideModal();
  });
})();
