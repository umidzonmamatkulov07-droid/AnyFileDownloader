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
  { url: "https://audio.example/song.mp3", detected_type: "AUDIO", first_seen: 1 },
  { url: "https://video.example/movie.mp4", detected_type: "VIDEO", content_length: 20_000_000, first_seen: 1 },
  { url: "https://hls.example/media.m3u8", detected_type: "HLS", first_seen: 1 },
  { url: "https://dash.example/manifest.mpd", detected_type: "DASH", first_seen: 1 },
  { url: "https://hls.example/master.m3u8", detected_type: "HLS", first_seen: 1 }
]);
assert.deepEqual(ranked.map((item) => item.detected_type), ["HLS", "DASH", "VIDEO", "AUDIO", "HLS"]);

console.log("media_detection.js tests passed");
