(async () => {
  const result = document.querySelector("#result");
  const files = [
    "../browser_extension/media_detection.js",
    "../browser_extension/background.js",
    "../browser_extension/content.js",
    "../browser_extension/popup.js"
  ];

  function assert(condition, message) {
    if (!condition) throw new Error(message);
  }

  try {
    for (const file of files) {
      const source = await fetch(file).then((response) => response.text());
      new Function(source);
    }

    assert(MediaDetection.classifyMedia("https://cdn.example/master.m3u8?token=abc") === "HLS", "HLS");
    assert(MediaDetection.classifyMedia("https://cdn.example/manifest.mpd") === "DASH", "DASH");
    assert(MediaDetection.classifyMedia("https://cdn.example/movie.mp4") === "VIDEO", "VIDEO");
    assert(MediaDetection.classifyMedia("https://cdn.example/song.m4a") === "AUDIO", "AUDIO");

    const first = MediaDetection.deduplicateCandidates([], {
      url: "https://cdn.example/movie.mp4?token=one#first",
      detected_type: "VIDEO",
      first_seen: 1
    });
    const duplicate = MediaDetection.deduplicateCandidates(first, {
      url: "https://cdn.example/movie.mp4?token=one#second",
      detected_type: "VIDEO",
      first_seen: 2
    });
    const signedVariant = MediaDetection.deduplicateCandidates(duplicate, {
      url: "https://cdn.example/movie.mp4?token=two",
      detected_type: "VIDEO",
      first_seen: 3
    });
    assert(duplicate.length === 1, "fragment deduplication");
    assert(signedVariant.length === 2, "signed query preservation");
    result.textContent = "PASS";
  } catch (error) {
    result.textContent = `FAIL: ${error.message}`;
  }
})();
