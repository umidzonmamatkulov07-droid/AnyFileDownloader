const candidateList = document.querySelector("#candidate-list");
const manualButton = document.querySelector("#download-manual");
const manualInput = document.querySelector("#manual-url");
const nativeStatus = document.querySelector("#native-status");
const requestStatus = document.querySelector("#request-status");
const candidateDebug = document.querySelector("#candidate-debug");

let activeTab = null;
let candidates = [];

function readableName(candidate) {
  if (candidate.browser_filename) {
    const filename = String(candidate.browser_filename)
      .replace(/\\/g, "/")
      .split("/")
      .pop()
      .replace(/[\u0000-\u001f]/g, "")
      .trim();
    if (filename) return filename.length > 58 ? `${filename.slice(0, 55)}…` : filename;
  }
  try {
    const parsed = new URL(candidate.url);
    const filename = decodeURIComponent(parsed.pathname.split("/").filter(Boolean).pop() || parsed.hostname);
    return filename.length > 58 ? `${filename.slice(0, 55)}…` : filename;
  } catch (_error) {
    return candidate.url.slice(0, 58);
  }
}

function readableSize(byteCount) {
  if (!Number.isFinite(byteCount) || byteCount <= 0) return "Size unknown";
  const units = ["B", "KB", "MB", "GB"];
  let size = byteCount;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size >= 10 || unit === 0 ? size.toFixed(0) : size.toFixed(1)} ${units[unit]}`;
}

function readableExtension(candidate) {
  const name = candidate.browser_filename || readableName(candidate);
  const dotIndex = name.lastIndexOf(".");
  return dotIndex >= 0 ? name.slice(dotIndex + 1).toUpperCase() : "Unknown extension";
}

function candidateHost(candidate) {
  try {
    return new URL(candidate.url).hostname;
  } catch (_error) {
    return "unknown-host";
  }
}

function renderCandidateDebug(candidate) {
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
    `Filename: ${candidate.browser_filename || readableName(candidate)}`,
    `Approximate size: ${readableSize(candidate.content_length)}`,
    `Download state: ${candidate.download_state || "not started"}`,
    `Redirects: ${Math.max(0, (candidate.redirect_chain || []).length - 1)}`,
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
    const card = document.createElement("article");
    card.className = "candidate-card";
    card.setAttribute("role", "listitem");

    const name = document.createElement("div");
    name.className = "candidate-name";
    name.textContent = readableName(candidate);

    const metadata = document.createElement("div");
    metadata.className = "candidate-meta";
    metadata.textContent = [
      candidate.detected_type || "FILE",
      readableExtension(candidate),
      candidateHost(candidate),
      readableSize(candidate.content_length)
    ].join(" • ");

    const button = document.createElement("button");
    button.type = "button";
    button.className = "candidate-download";
    button.dataset.candidateIndex = String(index);
    button.textContent = candidate.is_browser_owned ? "Browser-owned" : "Download";
    button.disabled = Boolean(candidate.is_browser_owned);
    button.addEventListener("focus", () => renderCandidateDebug(candidate));
    button.addEventListener("click", () => {
      renderCandidateDebug(candidate);
      sendCandidate(candidate);
    });

    card.append(name, metadata, button);
    candidateList.append(card);
  }
  renderCandidateDebug(candidates[0]);
}

function setSendingState(isSending, text) {
  candidateList.querySelectorAll(".candidate-download").forEach((button) => {
    const candidate = candidates[Number(button.dataset.candidateIndex)];
    button.disabled = isSending || Boolean(candidate?.is_browser_owned);
  });
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
    detected_type: MediaDetection.classifyDownload(url) || "DIRECT",
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
