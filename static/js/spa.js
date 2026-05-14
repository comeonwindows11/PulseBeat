(function () {
  const VIEW_ID = "pulsebeat-view";
  const NAVIGATING_CLASS = "is-spa-navigating";
  const SCRIPT_SELECTOR = "script";
  const FULL_RELOAD_PATH_PREFIXES = ["/admin"];
  const FULL_RELOAD_SELECTORS = [
    "[data-recap-root]",
    ".recap-experience-page",
  ];

  if (window.__PULSEBEAT_SPA__) return;
  window.__PULSEBEAT_SPA__ = true;

  if (!window.fetch || !window.DOMParser || !window.history || !window.history.pushState) {
    return;
  }

  let activeController = null;
  let navigationToken = 0;
  let busyStartedAt = 0;
  let busyReleaseTimer = null;

  function currentView() {
    return document.getElementById(VIEW_ID) || document.querySelector("main.page-container");
  }

  function normalizeUrl(rawUrl) {
    try {
      return new URL(rawUrl, window.location.href);
    } catch (_err) {
      return null;
    }
  }

  function shouldUseFullReload(url) {
    if (!url || url.origin !== window.location.origin) return true;
    if (FULL_RELOAD_PATH_PREFIXES.some((prefix) => url.pathname === prefix || url.pathname.startsWith(`${prefix}/`))) {
      return true;
    }
    return false;
  }

  function isSameDocumentHashNavigation(url) {
    return (
      url
      && url.origin === window.location.origin
      && url.pathname === window.location.pathname
      && url.search === window.location.search
      && url.hash
    );
  }

  function findNavigableAnchor(target) {
    if (!target || typeof target.closest !== "function") return null;
    const anchor = target.closest("a[href]");
    if (!anchor) return null;
    const href = String(anchor.getAttribute("href") || "").trim();
    if (!href || href.startsWith("#") || href.startsWith("javascript:")) return null;
    if (anchor.hasAttribute("download")) return null;
    const targetName = String(anchor.getAttribute("target") || "").trim().toLowerCase();
    if (targetName && targetName !== "_self") return null;
    return anchor;
  }

  function isPlainPrimaryClick(event) {
    return event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey;
  }

  function closeTransientChrome() {
    const nav = document.getElementById("main-nav");
    const menuBtn = document.getElementById("menu-toggle");
    const navBackdrop = document.getElementById("nav-backdrop");
    if (nav) nav.classList.remove("open");
    if (menuBtn) {
      menuBtn.classList.remove("active");
      menuBtn.setAttribute("aria-expanded", "false");
    }
    if (navBackdrop) {
      navBackdrop.classList.add("hidden");
      navBackdrop.setAttribute("aria-hidden", "true");
    }
    document.body.classList.remove("nav-open");
    document.querySelectorAll(".modal:not(.hidden), .player-bottom-sheet:not(.hidden)").forEach((modal) => {
      modal.classList.add("hidden");
      modal.setAttribute("aria-hidden", "true");
    });
  }

  function setBusy(busy) {
    if (busyReleaseTimer) {
      clearTimeout(busyReleaseTimer);
      busyReleaseTimer = null;
    }
    if (busy) {
      busyStartedAt = performance.now();
      document.documentElement.classList.add(NAVIGATING_CLASS);
    } else {
      const elapsed = performance.now() - busyStartedAt;
      const remaining = Math.max(0, 180 - elapsed);
      if (remaining > 0) {
        busyReleaseTimer = setTimeout(() => setBusy(false), remaining);
        return;
      }
      document.documentElement.classList.remove(NAVIGATING_CLASS);
    }
    const view = currentView();
    if (view) view.setAttribute("aria-busy", busy ? "true" : "false");
  }

  function executeScripts(container) {
    Array.from(container.querySelectorAll(SCRIPT_SELECTOR)).forEach((oldScript) => {
      const nextScript = document.createElement("script");
      Array.from(oldScript.attributes).forEach((attr) => {
        nextScript.setAttribute(attr.name, attr.value);
      });
      nextScript.text = oldScript.textContent || "";
      oldScript.replaceWith(nextScript);
    });
  }

  function pageRequiresFullReload(nextDocument) {
    const nextView = nextDocument.getElementById(VIEW_ID) || nextDocument.querySelector("main.page-container");
    if (!nextView) return true;
    const hasCurrentPlayer = !!document.getElementById("global-audio");
    const hasNextPlayer = !!nextDocument.getElementById("global-audio");
    if (hasCurrentPlayer !== hasNextPlayer) return true;
    if (FULL_RELOAD_SELECTORS.some((selector) => nextDocument.querySelector(selector))) return true;
    return false;
  }

  function focusView(url) {
    const view = currentView();
    if (!view) return;
    if (url.hash) {
      const target = document.getElementById(url.hash.slice(1));
      if (target) {
        target.scrollIntoView({ block: "start" });
        return;
      }
    }
    window.scrollTo({ top: 0, left: 0, behavior: "instant" });
    view.setAttribute("tabindex", "-1");
    view.focus({ preventScroll: true });
  }

  function replaceDocumentParts(nextDocument, url) {
    const view = currentView();
    const nextView = nextDocument.getElementById(VIEW_ID) || nextDocument.querySelector("main.page-container");
    if (!view || !nextView) return false;

    window.PAGE_SONG_OBJECTS = [];
    window.PAGE_RECOMMENDED_SONGS = [];

    document.title = nextDocument.title || document.title;
    document.documentElement.lang = nextDocument.documentElement.lang || document.documentElement.lang;
    document.body.className = nextDocument.body.className || "";
    view.innerHTML = nextView.innerHTML;
    executeScripts(view);
    closeTransientChrome();
    focusView(url);
    document.dispatchEvent(new CustomEvent("pulsebeat:navigated", {
      detail: {
        url: url.toString(),
        path: `${url.pathname}${url.search}${url.hash}`,
        view,
      },
    }));
    return true;
  }

  async function loadUrl(rawUrl, options) {
    const url = normalizeUrl(rawUrl);
    if (!url || shouldUseFullReload(url)) {
      window.location.assign(rawUrl);
      return;
    }

    const token = ++navigationToken;
    if (activeController) activeController.abort();
    activeController = new AbortController();
    setBusy(true);

    try {
      const response = await fetch(url.toString(), {
        method: "GET",
        credentials: "same-origin",
        headers: {
          "Accept": "text/html,application/xhtml+xml",
          "X-Requested-With": "PulseBeat-SPA",
        },
        signal: activeController.signal,
      });
      if (!response.ok) throw new Error(`Navigation failed with ${response.status}`);
      const contentType = response.headers.get("content-type") || "";
      if (!contentType.includes("text/html")) throw new Error("Navigation did not return HTML");
      const finalUrl = normalizeUrl(response.url || url.toString()) || url;
      if (shouldUseFullReload(finalUrl)) {
        window.location.assign(finalUrl.toString());
        return;
      }
      const html = await response.text();
      if (token !== navigationToken) return;

      const nextDocument = new DOMParser().parseFromString(html, "text/html");
      if (pageRequiresFullReload(nextDocument)) {
        window.location.assign(url.toString());
        return;
      }
      if (!replaceDocumentParts(nextDocument, finalUrl)) {
        window.location.assign(finalUrl.toString());
        return;
      }
      if (!options || options.history !== "replace") {
        window.history.pushState({ pulsebeatSpa: true }, "", finalUrl.toString());
      } else {
        window.history.replaceState({ pulsebeatSpa: true }, "", finalUrl.toString());
      }
    } catch (err) {
      if (err && err.name === "AbortError") return;
      window.location.assign(url.toString());
    } finally {
      if (token === navigationToken) {
        activeController = null;
        setBusy(false);
      }
    }
  }

  document.addEventListener("click", (event) => {
    const anchor = findNavigableAnchor(event.target);
    if (!anchor || !isPlainPrimaryClick(event)) return;
    const url = normalizeUrl(anchor.href);
    if (!url || shouldUseFullReload(url)) return;
    if (isSameDocumentHashNavigation(url)) return;
    event.preventDefault();
    loadUrl(url.toString()).catch(() => {
      window.location.assign(url.toString());
    });
  }, true);

  document.addEventListener("submit", (event) => {
    const form = event.target;
    if (!form || typeof form.getAttribute !== "function") return;
    const method = String(form.getAttribute("method") || "get").trim().toLowerCase();
    if (method !== "get") return;
    const targetName = String(form.getAttribute("target") || "").trim().toLowerCase();
    if (targetName && targetName !== "_self") return;
    const action = normalizeUrl(form.getAttribute("action") || window.location.href);
    if (!action || shouldUseFullReload(action)) return;
    event.preventDefault();
    const data = new FormData(form);
    const nextUrl = new URL(action.toString());
    nextUrl.search = new URLSearchParams(data).toString();
    loadUrl(nextUrl.toString()).catch(() => {
      window.location.assign(nextUrl.toString());
    });
  }, true);

  window.addEventListener("popstate", () => {
    loadUrl(window.location.href, { history: "replace" }).catch(() => {
      window.location.reload();
    });
  });

  window.history.replaceState({ pulsebeatSpa: true }, "", window.location.href);
})();
