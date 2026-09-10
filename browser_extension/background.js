importScripts("media_detection.js");

const NATIVE_HOST_NAME = "com.anyfiledownloader.native_host";
const MAX_TRANSPORT_STREAM_CANDIDATES_PER_TAB = 10;
const MIN_DIRECT_RESOURCE_BYTES = 64 * 1024;
const updateChains = new Map();

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

chrome.webRequest.onHeadersReceived.addListener(
  (details) => {
    if (details.tabId < 0) return;
    const mimeType = responseHeader(details.responseHeaders, "content-type");
    const detectedType = MediaDetection.classifyMedia(details.url, mimeType);
    if (!detectedType) return;

    const contentLength = Number(responseHeader(details.responseHeaders, "content-length"));
    const isTinyDirectResource =
      Number.isFinite(contentLength) &&
      contentLength > 0 &&
      contentLength < MIN_DIRECT_RESOURCE_BYTES &&
      (detectedType === "VIDEO" || detectedType === "AUDIO") &&
      details.type !== "media";
    if (isTinyDirectResource) return;

    queueCandidate(details.tabId, {
      url: details.url,
      page_url: details.documentUrl || "",
      detected_type: detectedType,
      mime_type: mimeType,
      content_length: Number.isFinite(contentLength) ? contentLength : 0,
      source: "webRequest",
      first_seen: details.timeStamp || Date.now(),
      referer: details.documentUrl || details.initiator || "",
      origin: details.initiator || "",
      user_agent: navigator.userAgent
    });
  },
  { urls: ["<all_urls>"] },
  ["responseHeaders"]
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
      detected_type: candidate.detected_type || "DIRECT",
      mime_type: candidate.mime_type || "",
      source: candidate.source || "manual",
      referer: candidate.referer || candidate.page_url || "",
      origin: candidate.origin || "",
      user_agent: candidate.user_agent || navigator.userAgent
    }, sendResponse);
    return true;
  }

  return false;
});
