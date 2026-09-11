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
    assert(MediaDetection.classifyDownload("https://cdn.example/report.pdf") === "DOCUMENT", "PDF");
    assert(MediaDetection.classifyDownload("https://cdn.example/archive.zip") === "ARCHIVE", "ZIP");
    assert(
      MediaDetection.classifyDownload("https://cdn.example/wrong.exe", "application/pdf") === "DOCUMENT",
      "MIME precedence"
    );

    const first = MediaDetection.deduplicateCandidates([], {
      url: "https://cdn.example/movie.mp4?token=one#first",
      detected_type: "VIDEO",
      media_title: "Episode 4",
      accept: "*/*",
      accept_language: "en-US,en;q=0.9",
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
    assert(duplicate[0].media_title === "Episode 4", "media title preservation");
    assert(duplicate[0].accept_language === "en-US,en;q=0.9", "Accept-Language preservation");
    assert(signedVariant.length === 2, "signed query preservation");
    const ranked = MediaDetection.rankCandidates([
      { url: "https://files.example/report.pdf", detected_type: "DOCUMENT" },
      { url: "https://audio.example/song.mp3", detected_type: "AUDIO" },
      { url: "https://video.example/movie.mp4", detected_type: "VIDEO", content_length: 20_000_000 },
      { url: "https://hls.example/media.m3u8", detected_type: "HLS" },
      { url: "https://dash.example/manifest.mpd", detected_type: "DASH" },
      { url: "https://hls.example/master.m3u8", detected_type: "HLS" }
    ]);
    assert(ranked.map((item) => item.detected_type).join(",") === "HLS,DOCUMENT,DASH,VIDEO,AUDIO,HLS", "ranking");
    result.textContent = "PASS";
  } catch (error) {
    result.textContent = `FAIL: ${error.message}`;
  }
})();
