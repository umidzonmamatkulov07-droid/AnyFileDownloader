const assert = typeof require === "function"
  ? require("node:assert/strict")
  : globalThis.browserAssert;
const detection = typeof require === "function"
  ? require("../browser_extension/media_detection.js")
  : globalThis.MediaDetection;

assert.equal(detection.classifyMedia("https://cdn.example/master.m3u8?token=abc"), "HLS");
assert.equal(detection.classifyMedia("https://cdn.example/manifest.mpd"), "DASH");
assert.equal(detection.classifyMedia("https://cdn.example/video", "video/mp4"), "VIDEO");
assert.equal(detection.classifyMedia("https://cdn.example/audio.m4a"), "AUDIO");
assert.equal(detection.classifyMedia("https://cdn.example/app.js", "application/javascript"), null);
assert.equal(detection.classifyDownload("https://cdn.example/report.pdf"), "DOCUMENT");
assert.equal(detection.candidateEvidenceStrength({
  url: "https://cdn.example/report.pdf",
  mime_type: "application/pdf",
  source: "webRequest"
}), 3);
assert.equal(detection.classifyDownload("https://cdn.example/report.docx"), "DOCUMENT");
assert.equal(detection.classifyDownload("https://cdn.example/budget.xlsx"), "DOCUMENT");
assert.equal(detection.classifyDownload("https://cdn.example/archive.zip"), "ARCHIVE");
assert.equal(detection.classifyDownload("https://cdn.example/package.apk"), "FILE");
assert.equal(detection.classifyDownload("https://cdn.example/misleading.exe", "application/pdf"), "DOCUMENT");
assert.equal(
  detection.classifyDownload(
    "https://cdn.example/download",
    "application/octet-stream",
    "attachment; filename*=UTF-8''Report%20One.pdf"
  ),
  "DOCUMENT"
);
assert.equal(
  detection.filenameFromContentDisposition("attachment; filename*=UTF-8''Report%20One.pdf"),
  "Report One.pdf"
);
assert.equal(detection.classifyDownload("https://cdn.example/download", "", "attachment"), "FILE");
assert.equal(detection.classifyDownload("https://metrics.example/collect", "text/plain"), null);
assert.equal(detection.classifyDownload("https://metrics.example/tr", "text/plain"), null);
assert.equal(detection.classifyDownload("https://metrics.example/envelope", "application/json"), null);
assert.equal(detection.classifyDownload("https://metrics.example/f.txt", "image/gif"), null);
assert.equal(detection.classifyDownload("https://files.example/viewer/report.pdf", "text/html"), null);
assert.equal(detection.classifyDownload("https://metrics.example/collect", "application/octet-stream"), null);
assert.equal(detection.shouldIncludeCandidate({
  url: "https://metrics.example/f.txt",
  mime_type: "text/plain",
  content_length: 42,
  request_method: "POST",
  resource_type: "xmlhttprequest",
  source: "webRequest"
}), false);
assert.equal(detection.candidateEvidenceStrength({
  url: "https://files.example/report.pdf?signature=abc&expires=123",
  source: "performance"
}), 1);
assert.equal(detection.shouldIncludeCandidate({
  url: "https://metrics.example/collect.pdf",
  mime_type: "application/pdf",
  content_disposition: "attachment; filename=collect.pdf",
  request_method: "POST",
  resource_type: "ping",
  source: "webRequest"
}), false);
assert.equal(detection.shouldIncludeCandidate({
  url: "https://metrics.example/f.txt",
  mime_type: "text/plain",
  content_length: 20_000,
  request_method: "GET",
  resource_type: "xmlhttprequest",
  source: "webRequest"
}), false);
assert.equal(detection.shouldIncludeCandidate({
  url: "https://files.example/readme.txt",
  source: "anchor_link"
}), true);
assert.equal(detection.shouldIncludeCandidate({
  url: "https://files.example/download",
  mime_type: "application/pdf",
  source: "webRequest"
}), true);
assert.equal(detection.shouldIncludeCandidate({
  url: "https://files.example/download",
  mime_type: "application/octet-stream",
  content_disposition: "attachment; filename=report.pdf",
  source: "webRequest"
}), true);
assert.equal(detection.shouldIncludeCandidate({
  url: "https://files.example/download",
  mime_type: "application/octet-stream",
  source: "webRequest"
}), false);
assert.equal(detection.resolveCandidateTabId(12, 7), 12);
assert.equal(detection.resolveCandidateTabId(-1, 7), 7);
assert.equal(detection.resolveCandidateTabId(-1, undefined), -1);

const first = {
  url: "https://cdn.example/video.mp4?signature=one#fragment",
  page_url: "https://example.com/watch",
  media_title: "Episode 4",
  accept: "*/*",
  accept_language: "en-US,en;q=0.9",
  detected_type: "VIDEO",
  source: "performance",
  first_seen: 1
};
const duplicate = { ...first, url: "https://cdn.example/video.mp4?signature=one#other", source: "webRequest" };
const differentSignature = { ...first, url: "https://cdn.example/video.mp4?signature=two" };

let candidates = detection.deduplicateCandidates([], first);
candidates = detection.deduplicateCandidates(candidates, duplicate);
assert.equal(candidates.length, 1);
assert.equal(candidates[0].source, "webRequest");
assert.equal(candidates[0].first_seen, 1);
assert.equal(candidates[0].media_title, "Episode 4");
assert.equal(candidates[0].accept_language, "en-US,en;q=0.9");
candidates = detection.deduplicateCandidates(candidates, differentSignature);
assert.equal(candidates.length, 2);
assert.match(candidates[0].url, /signature=one$/);

const ranked = detection.rankCandidates([
  { url: "https://files.example/unknown", detected_type: "FILE", evidence_strength: 1, first_seen: 1 },
  { url: "https://files.example/report.pdf", detected_type: "DOCUMENT", evidence_strength: 3, first_seen: 1 },
  { url: "https://audio.example/song.mp3", detected_type: "AUDIO", first_seen: 1 },
  { url: "https://video.example/movie.mp4", detected_type: "VIDEO", content_length: 20_000_000, first_seen: 1 },
  { url: "https://hls.example/media.m3u8", detected_type: "HLS", first_seen: 1 },
  { url: "https://dash.example/manifest.mpd", detected_type: "DASH", first_seen: 1 },
  { url: "https://hls.example/master.m3u8", detected_type: "HLS", first_seen: 1 }
]);
assert.deepEqual(
  ranked.map((item) => `${item.detected_type}:${item.url.split("/").at(-1)}`),
  [
    "HLS:master.m3u8", "DOCUMENT:report.pdf", "DASH:manifest.mpd", "VIDEO:movie.mp4",
    "AUDIO:song.mp3", "HLS:media.m3u8", "FILE:unknown"
  ]
);

// Redirect-only evidence is medium confidence and preserves the original and final URLs.
const redirectedPdf = detection.normalizeCandidate({
  url: "https://files.example/final/report.pdf",
  original_url: "https://files.example/download?id=7",
  final_url: "https://files.example/final/report.pdf",
  redirect_chain: [
    "https://files.example/download?id=7",
    "https://files.example/final/report.pdf"
  ],
  source: "webRequest"
});
assert.equal(redirectedPdf.evidence_strength, 2);
assert.equal(redirectedPdf.url, "https://files.example/final/report.pdf");
assert.equal(redirectedPdf.redirect_chain.length, 2);
assert.equal(detection.candidatesMatch(redirectedPdf, {
  url: "https://files.example/final/other.pdf",
  original_url: "https://files.example/download?id=7",
  final_url: "https://files.example/final/other.pdf",
  redirect_chain: [
    "https://files.example/download?id=7",
    "https://files.example/final/other.pdf"
  ]
}), false);

// Content-Disposition supplies a high-confidence filename and type for an extensionless URL.
const dispositionZip = detection.normalizeCandidate({
  url: "https://files.example/export?id=42",
  mime_type: "application/octet-stream",
  content_disposition: "attachment; filename=backup.zip",
  browser_filename: "backup.zip",
  source: "webRequest"
});
assert.equal(dispositionZip.detected_type, "ARCHIVE");
assert.equal(dispositionZip.browser_filename, "backup.zip");
assert.equal(dispositionZip.evidence_strength, 3);

const extensionlessPdf = detection.normalizeCandidate({
  url: "https://files.example/document/42",
  mime_type: "application/pdf",
  source: "webRequest"
});
assert.equal(extensionlessPdf.detected_type, "DOCUMENT");
assert.equal(extensionlessPdf.evidence_strength, 3);

const evidenceRanked = detection.rankCandidates([
  { url: "https://files.example/report.pdf", detected_type: "DOCUMENT", evidence_strength: 1 },
  { url: "https://files.example/final/archive.zip", detected_type: "ARCHIVE", evidence_strength: 2 },
  { url: "https://files.example/document/42", detected_type: "DOCUMENT", evidence_strength: 3 }
]);
assert.deepEqual(evidenceRanked.map((item) => item.evidence_strength), [3, 2, 1]);

// Anchor, redirect, and chrome.downloads observations collapse into one final candidate.
let oneDownload = detection.deduplicateCandidates([], {
  url: "https://files.example/download?id=7",
  browser_filename: "report.pdf",
  source: "anchor_download",
  first_seen: 10
});
oneDownload = detection.deduplicateCandidates(oneDownload, redirectedPdf);
oneDownload = detection.deduplicateCandidates(oneDownload, detection.candidateFromDownloadItem({
  id: 91,
  url: "https://files.example/download?id=7",
  finalUrl: "https://files.example/final/report.pdf",
  filename: "/home/test/Downloads/report.pdf",
  mime: "application/pdf",
  totalBytes: 123456,
  tabId: 5,
  state: "in_progress",
  startTime: "2026-09-12T00:00:00.000Z",
  cookie: "must-not-be-captured",
  authorization: "must-not-be-captured"
}));
assert.equal(oneDownload.length, 1);
assert.equal(oneDownload[0].url, "https://files.example/final/report.pdf");
assert.equal(oneDownload[0].source, "chrome_download");
assert.equal(oneDownload[0].browser_filename, "report.pdf");
assert.equal(oneDownload[0].content_length, 123456);
assert.equal(oneDownload[0].download_id, 91);
assert.equal(oneDownload[0].download_state, "in_progress");
assert.equal(Object.hasOwn(oneDownload[0], "cookie"), false);
assert.equal(Object.hasOwn(oneDownload[0], "authorization"), false);

const completedItem = detection.applyDownloadDelta({
  id: 91,
  url: "https://files.example/download?id=7",
  finalUrl: "https://files.example/final/report.pdf",
  filename: "report.pdf",
  state: "in_progress",
  fileSize: -1
}, {
  id: 91,
  state: { current: "complete", previous: "in_progress" },
  fileSize: { current: 123456, previous: -1 }
});
assert.equal(completedItem.state, "complete");
assert.equal(completedItem.fileSize, 123456);

const failedItem = detection.applyDownloadDelta(completedItem, {
  id: 91,
  state: { current: "interrupted", previous: "in_progress" },
  error: { current: "NETWORK_FAILED" }
});
assert.equal(failedItem.state, "interrupted");
assert.equal(failedItem.error, "NETWORK_FAILED");

// Blob URLs stay opaque: only browser-owned metadata is retained.
const blobCandidate = detection.candidateFromDownloadItem({
  id: 92,
  url: "blob:https://app.example/1234-5678",
  filename: "/home/test/Downloads/generated.pdf",
  totalBytes: 2048,
  tabId: 5,
  state: "complete"
});
assert.equal(blobCandidate.detected_type, "DOCUMENT");
assert.equal(blobCandidate.is_browser_owned, true);
assert.equal(blobCandidate.browser_filename, "generated.pdf");
assert.deepEqual(Object.keys(blobCandidate).filter((key) => /body|content|data/i.test(key)), ["content_length"]);

const anonymousBlob = detection.candidateFromDownloadItem({
  id: 93,
  url: "blob:https://app.example/opaque-id",
  filename: "",
  tabId: 5,
  state: "in_progress"
});
assert.equal(anonymousBlob.detected_type, "FILE");
assert.equal(anonymousBlob.is_browser_owned, true);

console.log("media_detection.js tests passed");
