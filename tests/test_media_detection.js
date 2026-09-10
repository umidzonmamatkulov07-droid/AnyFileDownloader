const assert = require("node:assert/strict");
const detection = require("../browser_extension/media_detection.js");

assert.equal(detection.classifyMedia("https://cdn.example/master.m3u8?token=abc"), "HLS");
assert.equal(detection.classifyMedia("https://cdn.example/manifest.mpd"), "DASH");
assert.equal(detection.classifyMedia("https://cdn.example/video", "video/mp4"), "VIDEO");
assert.equal(detection.classifyMedia("https://cdn.example/audio.m4a"), "AUDIO");
assert.equal(detection.classifyMedia("https://cdn.example/app.js", "application/javascript"), null);

const first = {
  url: "https://cdn.example/video.mp4?signature=one#fragment",
  page_url: "https://example.com/watch",
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
candidates = detection.deduplicateCandidates(candidates, differentSignature);
assert.equal(candidates.length, 2);
assert.match(candidates[0].url, /signature=one$/);

console.log("media_detection.js tests passed");
