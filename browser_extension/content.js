const reportedCandidates = new Map();

function reportCandidate(url, source, mimeType = "", metadata = {}) {
  const normalizedUrl = MediaDetection.stripFragment(url);
  // The HTML download attribute is useful evidence, but it is not an HTTP
  // Content-Disposition header and must not be scored as one.
  const contentDisposition = "";
  const detectedType = MediaDetection.classifyDownload(
    normalizedUrl,
    mimeType,
    contentDisposition,
    metadata.browser_filename || ""
  ) || (source === "anchor_download" ? "FILE" : null);
  const evidenceStrength = MediaDetection.candidateEvidenceStrength({
    url: normalizedUrl,
    detected_type: detectedType,
    mime_type: mimeType,
    content_disposition: contentDisposition,
    browser_filename: metadata.browser_filename || "",
    source
  });
  if (
    !normalizedUrl ||
    !detectedType ||
    !evidenceStrength
  ) return;
  const reportSignature = [
    source,
    metadata.browser_filename || "",
    mimeType,
    evidenceStrength
  ].join("|");
  if (reportedCandidates.get(normalizedUrl) === reportSignature) return;
  reportedCandidates.set(normalizedUrl, reportSignature);

  chrome.runtime.sendMessage({
    type: "candidate-detected",
    candidate: {
      url: normalizedUrl,
      page_url: location.href,
      page_title: document.title,
      media_title: metadata.media_title || "",
      browser_filename: metadata.browser_filename || "",
      link_text: metadata.link_text || "",
      detected_type: detectedType,
      mime_type: mimeType,
      evidence_strength: evidenceStrength,
      source,
      is_browser_owned: MediaDetection.isBlobUrl(normalizedUrl),
      first_seen: Date.now(),
      referer: location.href,
      origin: location.origin,
      user_agent: navigator.userAgent
    }
  });
}

function inspectMediaElement(element) {
  if (!(element instanceof HTMLMediaElement) && !(element instanceof HTMLSourceElement)) return;
  const url = element.currentSrc || element.src;
  const mediaTitle = element.getAttribute("title") || element.getAttribute("aria-label") || "";
  if (url) reportCandidate(url, "media_element", element.getAttribute("type") || "", { media_title: mediaTitle });
  if (element instanceof HTMLMediaElement) {
    element.querySelectorAll("source[src]").forEach(inspectMediaElement);
  }
}

function inspectAnchor(element) {
  if (!(element instanceof HTMLAnchorElement) || !element.href) return;
  const isDownload = element.hasAttribute("download");
  reportCandidate(element.href, isDownload ? "anchor_download" : "anchor_link", element.getAttribute("type") || "", {
    browser_filename: element.getAttribute("download") || "",
    link_text: (element.textContent || element.getAttribute("title") || element.getAttribute("aria-label") || "").trim()
  });
}

function inspectNode(node) {
  if (!(node instanceof Element)) return;
  if (node.matches("video, audio, source")) inspectMediaElement(node);
  if (node.matches("a[href]")) inspectAnchor(node);
  node.querySelectorAll("video, audio, source").forEach(inspectMediaElement);
  node.querySelectorAll("a[href]").forEach(inspectAnchor);
}

document.querySelectorAll("video, audio, source").forEach(inspectMediaElement);
document.querySelectorAll("a[href]").forEach(inspectAnchor);
performance.getEntriesByType("resource").forEach((entry) => reportCandidate(entry.name, "performance"));

const performanceObserver = new PerformanceObserver((list) => {
  list.getEntries().forEach((entry) => reportCandidate(entry.name, "performance"));
});
performanceObserver.observe({ type: "resource", buffered: true });

const mutationObserver = new MutationObserver((mutations) => {
  for (const mutation of mutations) {
    mutation.addedNodes.forEach(inspectNode);
    if (mutation.type === "attributes") {
      inspectMediaElement(mutation.target);
      inspectAnchor(mutation.target);
    }
  }
});
mutationObserver.observe(document.documentElement, {
  childList: true,
  subtree: true,
  attributes: true,
  attributeFilter: ["src", "href", "download"]
});
