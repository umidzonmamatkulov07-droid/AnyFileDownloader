const assert = require("node:assert/strict");
const detection = require("../browser_extension/media_detection.js");

assert.equal(detection.classifyMedia("https://cdn.example/master.m3u8?token=abc"), "HLS");
assert.equal(detection.classifyMedia("https://cdn.example/manifest.mpd"), "DASH");
assert.equal(detection.classifyMedia("https://cdn.example/video", "video/mp4"), "VIDEO");
assert.equal(detection.classifyMedia("https://cdn.example/audio.m4a"), "AUDIO");
assert.equal(detection.classifyMedia("https://cdn.example/app.js", "application/javascript"), null);
assert.equal(detection.classifyDownload("https://cdn.example/report.pdf"), "DOCUMENT");
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
assert.equal(detection.classifyDownload("https://metrics.example/collect", "application/octet-stream"), null);
assert.equal(detection.shouldIncludeCandidate({
  url: "https://metrics.example/f.txt",
  mime_type: "text/plain",
  content_length: 42,
  request_method: "POST",
  resource_type: "xmlhttprequest",
  source: "webRequest"
}), false);
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
  { url: "https://files.example/report.pdf", detected_type: "DOCUMENT", first_seen: 1 },
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

console.log("media_detection.js tests passed");
