(function initializeInlineButtons(globalObject) {
  const MEDIA_TYPES = new Set(["VIDEO", "AUDIO", "HLS", "DASH"]);
  const FILE_TYPES = new Set(["PDF", "DOCUMENT", "ARCHIVE", "FILE", "DIRECT"]);

  function normalizedUrl(url) {
    try {
      const parsed = new URL(url, globalObject.location?.href || undefined);
      parsed.hash = "";
      return parsed.href;
    } catch (_error) {
      return "";
    }
  }

  function candidateKey(candidate) {
    return normalizedUrl(candidate?.final_url || candidate?.url || "");
  }

  function elementUrls(element) {
    const values = [element?.currentSrc, element?.src, element?.href];
    if (element?.querySelectorAll) {
      element.querySelectorAll("source[src]").forEach((source) => values.push(source.src));
    }
    return new Set(values.map(normalizedUrl).filter(Boolean));
  }

  function isEligible(candidate) {
    if (!candidate || !candidateKey(candidate)) return false;
    const type = candidate.detected_type || "";
    if (!MEDIA_TYPES.has(type) && !FILE_TYPES.has(type)) return false;
    if (candidate.is_browser_owned && MEDIA_TYPES.has(type)) return false;
    return Number(candidate.evidence_strength) > 0;
  }

  function matchesAnchor(anchor, candidate) {
    if (!anchor || !FILE_TYPES.has(candidate.detected_type || "")) return false;
    return elementUrls(anchor).has(candidateKey(candidate));
  }

  function matchesMedia(media, candidate, visibleMediaCount = 1) {
    if (!media || !MEDIA_TYPES.has(candidate.detected_type || "")) return false;
    if (elementUrls(media).has(candidateKey(candidate))) return true;
    const strongPlayerRequest =
      Number(candidate.evidence_strength) >= 3 &&
      ["HLS", "DASH"].includes(candidate.detected_type) &&
      candidate.source === "webRequest" &&
      visibleMediaCount === 1;
    return strongPlayerRequest;
  }

  function labelFor(candidate) {
    const filename = String(candidate.browser_filename || candidate.media_title || "").trim();
    return filename || candidate.detected_type || "Download";
  }

  function applyButtonStyle(button, compact = false) {
    Object.assign(button.style, {
      all: "initial",
      boxSizing: "border-box",
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      minWidth: compact ? "26px" : "32px",
      height: compact ? "26px" : "32px",
      padding: compact ? "0 6px" : "0 8px",
      border: "1px solid #00f0ff",
      borderRadius: "6px",
      background: "rgba(2, 4, 8, 0.88)",
      color: "#00f0ff",
      font: "700 14px/1 system-ui, sans-serif",
      cursor: "pointer",
      boxShadow: "0 0 10px rgba(0, 240, 255, 0.35)",
      zIndex: "2147483647"
    });
    button.dataset.afdInlineButton = "true";
  }

  class InlineButtonController {
    constructor(options = {}) {
      this.document = options.document || globalObject.document;
      this.sendCandidate = options.sendCandidate || (() => {});
      this.MutationObserver = options.MutationObserver || globalObject.MutationObserver;
      this.enabled = false;
      this.candidates = [];
      this.records = new Map();
      this.observer = null;
      this.refreshTimer = null;
      this.boundRefresh = () => this.scheduleRefresh();
    }

    start() {
      if (this.observer || !this.MutationObserver || !this.document?.documentElement) return;
      this.observer = new this.MutationObserver(() => this.scheduleRefresh());
      this.observer.observe(this.document.documentElement, { childList: true, subtree: true, attributes: true, attributeFilter: ["src", "href"] });
      globalObject.addEventListener?.("resize", this.boundRefresh, { passive: true });
      globalObject.addEventListener?.("scroll", this.boundRefresh, { passive: true, capture: true });
      this.document.addEventListener?.("fullscreenchange", this.boundRefresh);
      this.refresh();
    }

    stop() {
      this.observer?.disconnect();
      this.observer = null;
      globalObject.removeEventListener?.("resize", this.boundRefresh);
      globalObject.removeEventListener?.("scroll", this.boundRefresh, true);
      this.document.removeEventListener?.("fullscreenchange", this.boundRefresh);
      if (this.refreshTimer) globalObject.clearTimeout(this.refreshTimer);
      this.refreshTimer = null;
      this.removeAll();
    }

    setEnabled(enabled) {
      this.enabled = Boolean(enabled);
      if (!this.enabled) this.removeAll();
      else this.refresh();
    }

    setCandidates(candidates) {
      this.candidates = (Array.isArray(candidates) ? candidates : []).filter(isEligible);
      this.refresh();
    }

    scheduleRefresh() {
      if (this.refreshTimer) return;
      this.refreshTimer = globalObject.setTimeout(() => {
        this.refreshTimer = null;
        this.refresh();
      }, 50);
    }

    removeAll() {
      for (const record of this.records.values()) {
        record.button.remove();
        record.menu?.remove();
      }
      this.records.clear();
    }

    refresh() {
      if (!this.enabled || !this.document?.body) {
        if (!this.enabled) this.removeAll();
        return;
      }
      const mediaElements = [...this.document.querySelectorAll("video, audio")].filter((element) => {
        const rect = element.getBoundingClientRect();
        const viewportWidth = globalObject.innerWidth || this.document.documentElement.clientWidth || Infinity;
        const viewportHeight = globalObject.innerHeight || this.document.documentElement.clientHeight || Infinity;
        const fullscreen = this.document.fullscreenElement;
        const belongsToFullscreen = !fullscreen || fullscreen === element || fullscreen.contains?.(element);
        return belongsToFullscreen && rect.width >= 120 && rect.height >= 60 &&
          rect.bottom > 0 && rect.right > 0 && rect.top < viewportHeight && rect.left < viewportWidth;
      });
      const anchors = [...this.document.querySelectorAll("a[href]")];
      const desired = new Map();

      for (const media of mediaElements) {
        const matches = this.candidates.filter((candidate) => matchesMedia(media, candidate, mediaElements.length));
        if (matches.length) desired.set(media, { kind: "media", candidates: matches });
      }
      for (const anchor of anchors) {
        const matches = this.candidates.filter((candidate) => matchesAnchor(anchor, candidate));
        if (matches.length) desired.set(anchor, { kind: "anchor", candidates: [matches[0]] });
      }

      for (const [element, record] of this.records) {
        if (!desired.has(element) || !element.isConnected) {
          record.button.remove();
          record.menu?.remove();
          this.records.delete(element);
        }
      }
      for (const [element, association] of desired) {
        let record = this.records.get(element);
        if (!record) {
          record = this.createButton(element, association.kind);
          this.records.set(element, record);
        }
        record.candidates = association.candidates;
        record.button.title = association.candidates.length > 1
          ? `AnyFileDownloader: ${association.candidates.length} choices`
          : `Download ${labelFor(association.candidates[0])} with AnyFileDownloader`;
        if (association.kind === "media") this.positionMediaButton(element, record.button);
      }
    }

    createButton(element, kind) {
      const button = this.document.createElement("button");
      button.type = "button";
      button.setAttribute("aria-label", "Download with AnyFileDownloader");
      button.textContent = "⇩";
      applyButtonStyle(button, kind === "anchor");
      if (kind === "media") {
        Object.assign(button.style, { position: "fixed" });
        this.document.body.append(button);
      } else {
        Object.assign(button.style, { marginInlineStart: "6px", verticalAlign: "middle" });
        element.insertAdjacentElement("afterend", button);
      }
      const record = { button, menu: null, candidates: [], kind };
      button.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        if (record.candidates.length > 1) this.toggleMenu(element, record);
        else if (record.candidates[0]) this.dispatch(record.candidates[0], element, button);
      });
      return record;
    }

    positionMediaButton(element, button) {
      const rect = element.getBoundingClientRect();
      button.style.left = `${Math.max(6, rect.right - 42)}px`;
      button.style.top = `${Math.max(6, rect.top + 10)}px`;
    }

    toggleMenu(element, record) {
      if (record.menu?.isConnected) {
        record.menu.remove();
        record.menu = null;
        return;
      }
      const menu = this.document.createElement("div");
      menu.dataset.afdInlineMenu = "true";
      Object.assign(menu.style, {
        position: "fixed", display: "grid", gap: "4px", maxWidth: "220px",
        padding: "6px", border: "1px solid #00f0ff", borderRadius: "6px",
        background: "rgba(2, 4, 8, 0.94)", zIndex: "2147483647"
      });
      const rect = record.button.getBoundingClientRect();
      menu.style.left = `${Math.max(6, rect.right - 220)}px`;
      menu.style.top = `${rect.bottom + 5}px`;
      record.candidates.slice(0, 6).forEach((candidate) => {
        const choice = this.document.createElement("button");
        choice.type = "button";
        choice.textContent = labelFor(candidate);
        applyButtonStyle(choice, true);
        choice.addEventListener("click", (event) => {
          event.preventDefault();
          event.stopPropagation();
          this.dispatch(candidate, element, record.button);
          menu.remove();
          record.menu = null;
        });
        menu.append(choice);
      });
      this.document.body.append(menu);
      record.menu = menu;
    }

    dispatch(candidate, element, button) {
      if (candidate.is_browser_owned && element instanceof globalObject.HTMLAnchorElement) {
        element.click();
        button.textContent = "✓";
        return;
      }
      this.sendCandidate(candidate, (ok) => {
        button.textContent = ok ? "✓" : "!";
        globalObject.setTimeout(() => { button.textContent = "⇩"; }, 1200);
      });
    }
  }

  const api = {
    InlineButtonController,
    candidateKey,
    elementUrls,
    isEligible,
    matchesAnchor,
    matchesMedia,
    normalizedUrl
  };
  globalObject.AFDInlineButtons = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(globalThis);
