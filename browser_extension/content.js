const reportedUrls = new Set();

function reportCandidate(url, source, mimeType = "") {
  const normalizedUrl = MediaDetection.stripFragment(url);
  const detectedType = MediaDetection.classifyMedia(normalizedUrl, mimeType);
  if (!normalizedUrl || !detectedType || reportedUrls.has(normalizedUrl)) return;
  reportedUrls.add(normalizedUrl);

  chrome.runtime.sendMessage({
    type: "candidate-detected",
    candidate: {
      url: normalizedUrl,
      page_url: location.href,
      page_title: document.title,
      detected_type: detectedType,
      mime_type: mimeType,
      source,
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
  if (url) reportCandidate(url, "media_element", element.getAttribute("type") || "");
  if (element instanceof HTMLMediaElement) {
    element.querySelectorAll("source[src]").forEach(inspectMediaElement);
  }
}

function inspectNode(node) {
  if (!(node instanceof Element)) return;
  if (node.matches("video, audio, source")) inspectMediaElement(node);
  node.querySelectorAll("video, audio, source").forEach(inspectMediaElement);
}

document.querySelectorAll("video, audio, source").forEach(inspectMediaElement);
performance.getEntriesByType("resource").forEach((entry) => reportCandidate(entry.name, "performance"));

const performanceObserver = new PerformanceObserver((list) => {
  list.getEntries().forEach((entry) => reportCandidate(entry.name, "performance"));
});
performanceObserver.observe({ type: "resource", buffered: true });

const mutationObserver = new MutationObserver((mutations) => {
  for (const mutation of mutations) {
    mutation.addedNodes.forEach(inspectNode);
    if (mutation.type === "attributes") inspectMediaElement(mutation.target);
  }
});
mutationObserver.observe(document.documentElement, {
  childList: true,
  subtree: true,
  attributes: true,
  attributeFilter: ["src"]
});
