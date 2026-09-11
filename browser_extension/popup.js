const candidateList = document.querySelector("#candidate-list");
const selectedButton = document.querySelector("#download-selected");
const manualButton = document.querySelector("#download-manual");
const manualInput = document.querySelector("#manual-url");
const nativeStatus = document.querySelector("#native-status");
const requestStatus = document.querySelector("#request-status");
const candidateDebug = document.querySelector("#candidate-debug");

let activeTab = null;
let candidates = [];

function readableName(candidate) {
  try {
    const parsed = new URL(candidate.url);
    const filename = decodeURIComponent(parsed.pathname.split("/").filter(Boolean).pop() || parsed.hostname);
    return filename.length > 58 ? `${filename.slice(0, 55)}…` : filename;
  } catch (_error) {
    return candidate.url.slice(0, 58);
  }
}

function candidateHost(candidate) {
  try {
    return new URL(candidate.url).hostname;
  } catch (_error) {
    return "unknown-host";
  }
}

function renderCandidateDebug() {
  const candidate = candidates[Number(candidateList.value)];
  if (!candidate) {
    candidateDebug.textContent = "No candidate selected.";
    return;
  }
  let hasQuery = false;
  try {
    hasQuery = Boolean(new URL(candidate.url).search);
  } catch (_error) {
    hasQuery = false;
  }
  candidateDebug.textContent = [
    `Type: ${candidate.detected_type || "unknown"}`,
    `Source: ${candidate.source || "unknown"}`,
    `Host: ${candidateHost(candidate)}`,
    `MIME: ${candidate.mime_type || "unknown"}`,
    `Query parameters: ${hasQuery ? "yes (values hidden)" : "no"}`,
    `Page/Referer context: ${candidate.referer || candidate.page_url ? "available" : "missing"}`,
    `Captured request headers: ${[
      candidate.accept && "Accept",
      candidate.accept_language && "Accept-Language",
      candidate.referer && "Referer",
      candidate.origin && "Origin",
      candidate.user_agent && "User-Agent",
      candidate.range && "Range",
      candidate.sec_fetch_site && "Sec-Fetch-*"
    ].filter(Boolean).join(", ") || "none"}`
  ].join("\n");
}

function errorMessage(response) {
  const error = response?.error;
  if (typeof error === "string") return error;
  if (error?.code === "native_host_unavailable") return `Native host unavailable: ${error.message}`;
  if (error?.code === "invalid_request") return `Invalid request: ${error.message}`;
  if (error?.code === "launch_failed") return `Downloader launch failed: ${error.message}`;
  return error?.message || "Unknown native messaging error";
}

function renderCandidates() {
  candidateList.replaceChildren();
  for (const [index, candidate] of candidates.entries()) {
    const option = document.createElement("option");
    option.value = String(index);
    option.textContent = `${candidate.detected_type} • ${candidateHost(candidate)} • ${readableName(candidate)}`;
    option.title = `${candidate.detected_type} from ${candidateHost(candidate)}`;
    candidateList.append(option);
  }
  if (candidates.length) candidateList.selectedIndex = 0;
  selectedButton.disabled = candidates.length === 0;
  renderCandidateDebug();
}

function setSendingState(isSending, text) {
  selectedButton.disabled = isSending || candidates.length === 0;
  manualButton.disabled = isSending;
  requestStatus.textContent = text;
}

function sendCandidate(candidate) {
  setSendingState(true, "Sending…");
  chrome.runtime.sendMessage({ type: "send-download", candidate }, (response) => {
    if (chrome.runtime.lastError) {
      setSendingState(false, `Error: ${chrome.runtime.lastError.message}`);
      return;
    }
    setSendingState(false, response?.ok ? "Accepted by desktop bridge." : `Error: ${errorMessage(response)}`);
  });
}

selectedButton.addEventListener("click", () => {
  const selected = candidates[Number(candidateList.value)];
  if (selected) sendCandidate(selected);
});

candidateList.addEventListener("change", renderCandidateDebug);

manualButton.addEventListener("click", () => {
  const url = MediaDetection.stripFragment(manualInput.value.trim());
  if (!/^https?:\/\//i.test(url) && !/^ftp:\/\//i.test(url)) {
    requestStatus.textContent = "Enter a valid HTTP, HTTPS, or FTP URL.";
    return;
  }
  sendCandidate({
    url,
    page_url: activeTab?.url || "",
    page_title: activeTab?.title || "",
    detected_type: MediaDetection.classifyMedia(url) || "DIRECT",
    mime_type: "",
    source: "manual",
    first_seen: Date.now(),
    referer: activeTab?.url || "",
    origin: activeTab?.url ? new URL(activeTab.url).origin : "",
    user_agent: navigator.userAgent
  });
});

chrome.runtime.sendMessage({ type: "check-native-host" }, (response) => {
  if (chrome.runtime.lastError) {
    nativeStatus.textContent = `Native host unavailable: ${chrome.runtime.lastError.message}`;
    return;
  }
  nativeStatus.textContent = response?.ok ? "Native host connected" : errorMessage(response);
  nativeStatus.classList.toggle("connected", Boolean(response?.ok));
});

chrome.tabs.query({ active: true, currentWindow: true }, ([tab]) => {
  activeTab = tab || null;
  if (!Number.isInteger(activeTab?.id)) {
    renderCandidates();
    return;
  }
  chrome.runtime.sendMessage({ type: "get-candidates", tabId: activeTab.id }, (response) => {
    candidates = response?.ok && Array.isArray(response.candidates) ? response.candidates : [];
    renderCandidates();
  });
});
