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
