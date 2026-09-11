importScripts("media_detection.js");

const NATIVE_HOST_NAME = "com.anyfiledownloader.native_host";
const MAX_TRANSPORT_STREAM_CANDIDATES_PER_TAB = 10;
const MIN_DIRECT_RESOURCE_BYTES = 64 * 1024;
const updateChains = new Map();
const requestContexts = new Map();
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
  const isDuplicate = candidates.some((item) => MediaDetection.stripFragment(item.url) === candidate.url);
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
  console.debug(`[AFD] candidate ${isDuplicate ? "duplicate merged" : "detected"}`, {
    type: candidate.detected_type,
    source: candidate.source,
    host: new URL(candidate.url).hostname,
    hasQuery: Boolean(new URL(candidate.url).search)
  });
}

function queueCandidate(tabId, candidate) {
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
}

chrome.webRequest.onBeforeSendHeaders.addListener(
  captureSafeRequestHeaders,
  { urls: ["<all_urls>"] },
  ["requestHeaders", "extraHeaders"]
);

chrome.webRequest.onHeadersReceived.addListener(
  (details) => {
    const capturedContext = requestContexts.get(details.requestId) || {};
    const candidateTabId = MediaDetection.resolveCandidateTabId(details.tabId, capturedContext.tab_id);
    if (candidateTabId < 0) return;
    const mimeType = responseHeader(details.responseHeaders, "content-type");
    const contentDisposition = responseHeader(details.responseHeaders, "content-disposition");
    const browserFilename = MediaDetection.filenameFromContentDisposition(contentDisposition);
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
      page_url: details.documentUrl || "",
      detected_type: detectedType,
      mime_type: mimeType,
      browser_filename: browserFilename,
      content_length: Number.isFinite(contentLength) ? contentLength : 0,
      evidence_strength: evidenceStrength,
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
  (details) => requestContexts.delete(details.requestId),
  { urls: ["<all_urls>"] }
);
chrome.webRequest.onErrorOccurred.addListener(
  (details) => requestContexts.delete(details.requestId),
  { urls: ["<all_urls>"] }
);

chrome.webNavigation.onCommitted.addListener((details) => {
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

  if (message?.type === "check-native-host") {
    sendNativeRequest({ action: "ping" }, sendResponse);
    return true;
  }

  if (message?.type === "send-download") {
    const candidate = message.candidate || {};
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
