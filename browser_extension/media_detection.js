(function initializeMediaDetection(globalObject) {
  const HLS_MIME_TYPES = new Set([
    "application/vnd.apple.mpegurl",
    "application/x-mpegurl",
    "audio/mpegurl",
    "audio/x-mpegurl"
  ]);
  const DASH_MIME_TYPES = new Set(["application/dash+xml"]);
  const VIDEO_EXTENSIONS = new Set([".mp4", ".webm", ".mkv", ".mov", ".m4v", ".ts"]);
  const AUDIO_EXTENSIONS = new Set([".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wav"]);

  function stripFragment(url) {
    try {
      const parsed = new URL(url);
      parsed.hash = "";
      return parsed.href;
    } catch (_error) {
      return "";
    }
  }

  function extensionForUrl(url) {
    try {
      const pathname = new URL(url).pathname.toLowerCase();
      const filename = pathname.slice(pathname.lastIndexOf("/") + 1);
      const dotIndex = filename.lastIndexOf(".");
      return dotIndex >= 0 ? filename.slice(dotIndex) : "";
    } catch (_error) {
      return "";
    }
  }

  function classifyMedia(url, mimeType = "") {
    const extension = extensionForUrl(url);
    const normalizedMime = mimeType.split(";", 1)[0].trim().toLowerCase();
    if (extension === ".m3u8" || HLS_MIME_TYPES.has(normalizedMime)) return "HLS";
    if (extension === ".mpd" || DASH_MIME_TYPES.has(normalizedMime)) return "DASH";
    if (VIDEO_EXTENSIONS.has(extension) || normalizedMime.startsWith("video/")) return "VIDEO";
    if (AUDIO_EXTENSIONS.has(extension) || normalizedMime.startsWith("audio/")) return "AUDIO";
    return null;
  }

  function normalizeCandidate(candidate) {
    const url = stripFragment(candidate.url || "");
    const detectedType = candidate.detected_type || classifyMedia(url, candidate.mime_type || "");
    if (!url || !detectedType) return null;
    return {
      url,
      page_url: stripFragment(candidate.page_url || ""),
      page_title: candidate.page_title || "",
      tab_id: Number.isInteger(candidate.tab_id) ? candidate.tab_id : -1,
      detected_type: detectedType,
      mime_type: candidate.mime_type || "",
      source: candidate.source || "webRequest",
      first_seen: Number.isFinite(candidate.first_seen) ? candidate.first_seen : Date.now(),
      content_length: Number.isFinite(candidate.content_length) ? candidate.content_length : 0,
      hls_kind: candidate.hls_kind || "",
      referer: candidate.referer || candidate.page_url || "",
      origin: candidate.origin || "",
      user_agent: candidate.user_agent || ""
    };
  }

  function deduplicateCandidates(existingCandidates, candidate, maximum = Number.POSITIVE_INFINITY) {
    const normalized = normalizeCandidate(candidate);
    if (!normalized) return existingCandidates.slice();

    const existingIndex = existingCandidates.findIndex((item) => stripFragment(item.url) === normalized.url);
    if (existingIndex >= 0) {
      const merged = {
        ...existingCandidates[existingIndex],
        ...Object.fromEntries(Object.entries(normalized).filter(([, value]) => value !== "" && value !== -1))
      };
      merged.first_seen = Math.min(existingCandidates[existingIndex].first_seen, normalized.first_seen);
      const updated = existingCandidates.slice();
      updated[existingIndex] = merged;
      return updated;
    }
    const combined = [...existingCandidates, normalized];
    return Number.isFinite(maximum) ? combined.slice(-maximum) : combined;
  }

  function candidateRank(candidate) {
    const type = candidate.detected_type || "";
    const hlsKind = candidate.hls_kind || "";
    const looksLikeMaster = /(?:^|[\/_-])master(?:[._/-]|$)/i.test(candidate.url || "");
    if (type === "HLS" && (hlsKind === "hls_master" || looksLikeMaster)) return 10;
    if (type === "DASH") return 20;
    if (type === "VIDEO") return candidate.content_length >= 10 * 1024 * 1024 ? 25 : 30;
    if (type === "AUDIO") return 40;
    if (type === "HLS") return 50;
    return 60;
  }

  function rankCandidates(candidates) {
    return candidates.slice().sort((left, right) => {
      const rankDifference = candidateRank(left) - candidateRank(right);
      if (rankDifference) return rankDifference;
      return (left.first_seen || 0) - (right.first_seen || 0);
    });
  }

  const api = {
    candidateRank,
    classifyMedia,
    deduplicateCandidates,
    extensionForUrl,
    normalizeCandidate,
    rankCandidates,
    stripFragment
  };
  globalObject.MediaDetection = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(globalThis);
