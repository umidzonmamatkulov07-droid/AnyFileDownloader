importScripts("media_detection.js");

const NATIVE_HOST_NAME = "com.anyfiledownloader.native_host";
const MAX_TRANSPORT_STREAM_CANDIDATES_PER_TAB = 10;
const MIN_DIRECT_RESOURCE_BYTES = 64 * 1024;
const updateChains = new Map();
const requestContexts = new Map();
const redirectChains = new Map();
const downloadItems = new Map();
const candidateAttributions = new Map();
const ATTRIBUTION_MAX_AGE_MS = 10 * 60 * 1000;
const MAX_ATTRIBUTION_URLS = 500;
const SAFE_REQUEST_HEADERS = new Map([
  ["accept", "accept"],
  ["accept-language", "accept_language"],
  ["origin", "origin"],
  ["range", "range"],
  ["referer", "referer"],
  ["sec-fetch-dest", "sec_fetch_dest"],
  ["sec-fetch-mode", "sec_fetch_mode"],
  ["sec-fetch-site", "sec_fetch_site"],
  ["user-agent", "user_agent"]
]);
const INLINE_BUTTON_SETTING = "showInlineButtons";

chrome.runtime.onInstalled.addListener(() => {
  chrome.storage.local.get(INLINE_BUTTON_SETTING).then((stored) => {
    if (typeof stored[INLINE_BUTTON_SETTING] !== "boolean") {
      return chrome.storage.local.set({ [INLINE_BUTTON_SETTING]: true });
    }
    return undefined;
  });
});

function storageKey(tabId) {
  return `mediaCandidates:${tabId}`;
}

function queueTabOperation(tabId, operation) {
  const previous = updateChains.get(tabId) || Promise.resolve();
  const next = previous.catch(() => {}).then(operation);
  updateChains.set(tabId, next);
  next.finally(() => {
    if (updateChains.get(tabId) === next) updateChains.delete(tabId);
  });
  return next;
}

async function addCandidate(tabId, rawCandidate) {
  if (tabId < 0) return;
  let tab;
  try {
    tab = await chrome.tabs.get(tabId);
  } catch (_error) {
    return;
  }

  const candidate = MediaDetection.normalizeCandidate({
    ...rawCandidate,
    tab_id: tabId,
    page_url: tab.url || rawCandidate.page_url || "",
    page_title: tab.title || rawCandidate.page_title || ""
  });
  if (!candidate) return;

  const key = storageKey(tabId);
  const stored = await chrome.storage.session.get(key);
  const candidates = Array.isArray(stored[key]) ? stored[key] : [];
  const isDuplicate = candidates.some((item) => MediaDetection.candidatesMatch(item, candidate));
  const isNewTransportStream =
    MediaDetection.extensionForUrl(candidate.url) === ".ts" &&
    !candidates.some((item) => item.url === candidate.url);
  if (
    isNewTransportStream &&
    candidates.filter((item) => MediaDetection.extensionForUrl(item.url) === ".ts").length >=
      MAX_TRANSPORT_STREAM_CANDIDATES_PER_TAB
  ) {
    return;
  }
  const updated = MediaDetection.deduplicateCandidates(candidates, candidate);
  await chrome.storage.session.set({ [key]: updated });
  chrome.tabs.sendMessage(tabId, {
    type: "inline-candidates-updated",
    candidates: MediaDetection.rankCandidates(updated)
  }).catch(() => {});
  console.debug(`[AFD] candidate ${isDuplicate ? "duplicate merged" : "detected"}`, {
    type: candidate.detected_type,
    source: candidate.source,
    host: new URL(candidate.url).hostname,
    hasQuery: Boolean(new URL(candidate.url).search)
  });
}

function queueCandidate(tabId, candidate) {
  if (tabId >= 0 && candidate.source !== "chrome_download") {
    const now = Date.now();
    for (const url of MediaDetection.candidateIdentityUrls(candidate)) {
      const tabs = candidateAttributions.get(url) || new Map();
      tabs.set(tabId, now);
      candidateAttributions.set(url, tabs);
    }
    while (candidateAttributions.size > MAX_ATTRIBUTION_URLS) {
      candidateAttributions.delete(candidateAttributions.keys().next().value);
    }
  }
  return queueTabOperation(tabId, () => addCandidate(tabId, candidate));
}

function clearCandidates(tabId) {
  if (tabId < 0) return Promise.resolve();
  return queueTabOperation(tabId, () => chrome.storage.session.remove(storageKey(tabId)));
}

function responseHeader(headers, name) {
  const match = (headers || []).find((header) => header.name.toLowerCase() === name.toLowerCase());
  return match?.value || "";
}

function captureSafeRequestHeaders(details) {
  const context = { ...(requestContexts.get(details.requestId) || {}) };
  if (Number.isInteger(details.tabId) && details.tabId >= 0) context.tab_id = details.tabId;
  for (const header of details.requestHeaders || []) {
    const field = SAFE_REQUEST_HEADERS.get(header.name.toLowerCase());
    if (field && typeof header.value === "string") context[field] = header.value;
  }
  requestContexts.set(details.requestId, context);
  if (!redirectChains.has(details.requestId)) {
    redirectChains.set(details.requestId, [MediaDetection.stripFragment(details.url)].filter(Boolean));
  }
}

chrome.webRequest.onBeforeSendHeaders.addListener(
  captureSafeRequestHeaders,
  { urls: ["<all_urls>"] },
  ["requestHeaders", "extraHeaders"]
);

chrome.webRequest.onBeforeRedirect.addListener(
  (details) => {
    const chain = redirectChains.get(details.requestId) || [];
    for (const url of [details.url, details.redirectUrl]) {
      const safeUrl = MediaDetection.stripFragment(url || "");
      if (safeUrl && chain.at(-1) !== safeUrl) chain.push(safeUrl);
    }
    redirectChains.set(details.requestId, chain);
  },
  { urls: ["<all_urls>"] }
);

chrome.webRequest.onHeadersReceived.addListener(
  (details) => {
    if (details.statusCode >= 300 && details.statusCode < 400) return;
    const capturedContext = requestContexts.get(details.requestId) || {};
    const candidateTabId = MediaDetection.resolveCandidateTabId(details.tabId, capturedContext.tab_id);
    if (candidateTabId < 0) return;
    const mimeType = responseHeader(details.responseHeaders, "content-type");
    const contentDisposition = responseHeader(details.responseHeaders, "content-disposition");
    const browserFilename = MediaDetection.filenameFromContentDisposition(contentDisposition);
    const redirectChain = redirectChains.get(details.requestId) || [details.url];
    const finalUrl = MediaDetection.stripFragment(details.url);
    if (finalUrl && redirectChain.at(-1) !== finalUrl) redirectChain.push(finalUrl);
    const detectedType = MediaDetection.classifyDownload(
      details.url, mimeType, contentDisposition, browserFilename
    );
    if (!detectedType) return;

    const contentLength = Number(responseHeader(details.responseHeaders, "content-length"));
    const evidenceStrength = MediaDetection.candidateEvidenceStrength({
      url: details.url,
      detected_type: detectedType,
      mime_type: mimeType,
      content_disposition: contentDisposition,
      browser_filename: browserFilename,
      content_length: Number.isFinite(contentLength) ? contentLength : 0,
      request_method: details.method || "",
      resource_type: details.type || "",
      redirect_chain: redirectChain,
      source: "webRequest"
    });
    if (!evidenceStrength) return;
    const isTinyDirectResource =
      Number.isFinite(contentLength) &&
      contentLength > 0 &&
      contentLength < MIN_DIRECT_RESOURCE_BYTES &&
      (detectedType === "VIDEO" || detectedType === "AUDIO") &&
      details.type !== "media";
    if (isTinyDirectResource) return;

    queueCandidate(candidateTabId, {
      url: details.url,
      original_url: redirectChain[0] || details.url,
      final_url: details.url,
      redirect_chain: redirectChain,
      page_url: details.documentUrl || "",
      detected_type: detectedType,
      mime_type: mimeType,
      browser_filename: browserFilename,
      content_disposition: contentDisposition,
      content_length: Number.isFinite(contentLength) ? contentLength : 0,
      evidence_strength: evidenceStrength,
      request_method: details.method || "",
      resource_type: details.type || "",
      source: "webRequest",
      first_seen: details.timeStamp || Date.now(),
      referer: capturedContext.referer || details.documentUrl || details.initiator || "",
      origin: capturedContext.origin || details.initiator || "",
      user_agent: capturedContext.user_agent || navigator.userAgent,
      accept: capturedContext.accept || "",
      accept_language: capturedContext.accept_language || "",
      range: capturedContext.range || "",
      sec_fetch_dest: capturedContext.sec_fetch_dest || "",
      sec_fetch_mode: capturedContext.sec_fetch_mode || "",
      sec_fetch_site: capturedContext.sec_fetch_site || ""
    });
  },
  { urls: ["<all_urls>"] },
  ["responseHeaders"]
);

chrome.webRequest.onCompleted.addListener(
  (details) => {
    requestContexts.delete(details.requestId);
    redirectChains.delete(details.requestId);
  },
  { urls: ["<all_urls>"] }
);
chrome.webRequest.onErrorOccurred.addListener(
  (details) => {
    requestContexts.delete(details.requestId);
    redirectChains.delete(details.requestId);
  },
  { urls: ["<all_urls>"] }
);

function downloadCandidate(item) {
  return MediaDetection.candidateFromDownloadItem(item);
}

function resolveDownloadTabId(item, candidate) {
  if (Number.isInteger(item.tabId) && item.tabId >= 0) return item.tabId;
  const cutoff = Date.now() - ATTRIBUTION_MAX_AGE_MS;
  const matchingTabs = new Set();
  for (const url of MediaDetection.candidateIdentityUrls(candidate)) {
    const tabs = candidateAttributions.get(url);
    if (!tabs) continue;
    for (const [tabId, seenAt] of tabs) {
      if (seenAt >= cutoff) matchingTabs.add(tabId);
      else tabs.delete(tabId);
    }
    if (!tabs.size) candidateAttributions.delete(url);
  }
  return matchingTabs.size === 1 ? [...matchingTabs][0] : -1;
}

function captureDownload(item) {
  if (!item || !Number.isInteger(item.id)) return;
  downloadItems.set(item.id, item);
  const candidate = downloadCandidate(item);
  if (!candidate) return;
  const tabId = resolveDownloadTabId(item, candidate);
  if (tabId >= 0) queueCandidate(tabId, candidate);
}

chrome.downloads.onCreated.addListener(captureDownload);

chrome.downloads.onChanged.addListener((delta) => {
  const updateItem = (item) => {
    if (!item) return;
    const updated = MediaDetection.applyDownloadDelta(item, delta);
    captureDownload(updated);
    if (["complete", "interrupted"].includes(updated.state)) downloadItems.delete(updated.id);
  };

  const cached = downloadItems.get(delta.id);
  const isTerminal = ["complete", "interrupted"].includes(delta.state?.current);
  if (cached && !isTerminal) {
    updateItem(cached);
    return;
  }
  chrome.downloads.search({ id: delta.id }, (items) => {
    updateItem(Array.isArray(items) ? items[0] : cached);
  });
});

chrome.webNavigation.onBeforeNavigate.addListener((details) => {
  if (details.frameId === 0) clearCandidates(details.tabId);
});

chrome.tabs.onRemoved.addListener((tabId) => clearCandidates(tabId));

function nativeError(message) {
  const lowered = message.toLowerCase();
  const code = lowered.includes("host not found") || lowered.includes("native messaging host")
    ? "native_host_unavailable"
    : "native_messaging_error";
  return { ok: false, error: { code, message } };
}

function sendNativeRequest(request, sendResponse) {
  chrome.runtime.sendNativeMessage(NATIVE_HOST_NAME, request, (response) => {
    if (chrome.runtime.lastError) {
      const message = chrome.runtime.lastError.message || "Unknown native messaging error";
      console.error("[AFD] native host error:", message);
      sendResponse(nativeError(message));
      return;
    }
    sendResponse(response || {
      ok: false,
      error: { code: "empty_response", message: "Native host returned no response" }
    });
  });
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type === "candidate-detected") {
    const tabId = sender.tab?.id;
    if (Number.isInteger(tabId)) queueCandidate(tabId, message.candidate || {});
    return false;
  }

  if (message?.type === "get-candidates") {
    const tabId = message.tabId;
    if (!Number.isInteger(tabId)) {
      sendResponse({ ok: false, error: { code: "invalid_tab", message: "No active tab" } });
      return false;
    }
    chrome.storage.session.get(storageKey(tabId)).then((stored) => {
      const candidates = stored[storageKey(tabId)] || [];
      sendResponse({ ok: true, candidates: MediaDetection.rankCandidates(candidates) });
    }).catch((error) => {
      sendResponse({ ok: false, error: { code: "storage_error", message: error.message } });
    });
    return true;
  }

  if (message?.type === "get-page-candidates") {
    const tabId = sender.tab?.id;
    if (!Number.isInteger(tabId)) {
      sendResponse({ ok: false, candidates: [] });
      return false;
    }
    chrome.storage.session.get(storageKey(tabId)).then((stored) => {
      sendResponse({
        ok: true,
        candidates: MediaDetection.rankCandidates(stored[storageKey(tabId)] || [])
      });
    }).catch(() => sendResponse({ ok: false, candidates: [] }));
    return true;
  }

  if (message?.type === "check-native-host") {
    sendNativeRequest({ action: "ping" }, sendResponse);
    return true;
  }

  if (message?.type === "send-download") {
    const candidate = message.candidate || {};
    if (MediaDetection.isBlobUrl(candidate.url || "") || candidate.is_browser_owned) {
      sendResponse({
        ok: false,
        error: {
          code: "browser_owned_download",
          message: "Blob downloads remain browser-owned and cannot be reconstructed by the native host."
        }
      });
      return false;
    }
    let host = "";
    try {
      host = new URL(candidate.url).hostname;
    } catch (_error) {
      host = "invalid";
    }
    console.info("[AFD] native download requested", {
      type: candidate.detected_type || "DIRECT",
      source: candidate.source || "manual",
      host
    });
    sendNativeRequest({
      action: "download",
      url: candidate.url || "",
      page_url: candidate.page_url || "",
      title: candidate.page_title || candidate.title || "",
      media_title: candidate.media_title || "",
      browser_filename: candidate.browser_filename || "",
      link_text: candidate.link_text || "",
      detected_type: candidate.detected_type || "DIRECT",
      mime_type: candidate.mime_type || "",
      source: candidate.source || "manual",
      referer: candidate.referer || candidate.page_url || "",
      origin: candidate.origin || "",
      user_agent: candidate.user_agent || navigator.userAgent,
      accept: candidate.accept || "",
      accept_language: candidate.accept_language || "",
      range: candidate.range || "",
      sec_fetch_dest: candidate.sec_fetch_dest || "",
      sec_fetch_mode: candidate.sec_fetch_mode || "",
      sec_fetch_site: candidate.sec_fetch_site || ""
    }, sendResponse);
    return true;
  }

  return false;
});
