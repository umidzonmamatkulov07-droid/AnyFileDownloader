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
  const DOCUMENT_EXTENSIONS = new Set([
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".rtf",
    ".csv", ".odt", ".ods", ".odp", ".epub", ".mobi"
  ]);
  const ARCHIVE_EXTENSIONS = new Set([".zip", ".rar", ".7z", ".tar", ".gz", ".bz2"]);
  const FILE_EXTENSIONS = new Set([".apk", ".exe", ".msi", ".iso", ".dmg", ".deb", ".rpm"]);
  const DOCUMENT_MIMES = new Set([
    "application/pdf", "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "text/plain", "text/rtf", "application/rtf", "text/csv",
    "application/vnd.oasis.opendocument.text",
    "application/vnd.oasis.opendocument.spreadsheet",
    "application/vnd.oasis.opendocument.presentation",
    "application/epub+zip", "application/x-mobipocket-ebook"
  ]);
  const ARCHIVE_MIMES = new Set([
    "application/zip", "application/x-zip-compressed", "application/vnd.rar",
    "application/x-rar-compressed", "application/x-7z-compressed", "application/x-tar",
    "application/gzip", "application/x-gzip", "application/x-bzip2"
  ]);
  const FILE_MIMES = new Set([
    "application/vnd.android.package-archive", "application/x-msdownload", "application/x-msi",
    "application/x-iso9660-image", "application/x-apple-diskimage",
    "application/vnd.debian.binary-package", "application/x-debian-package",
    "application/x-rpm", "application/x-redhat-package-manager"
  ]);
  const NON_DOWNLOAD_MIMES = new Set(["text/html", "application/xhtml+xml", "application/json"]);

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

  function extensionForName(filename) {
    const cleanName = String(filename || "").split(/[?#]/, 1)[0].toLowerCase();
    const dotIndex = cleanName.lastIndexOf(".");
    return dotIndex >= 0 ? cleanName.slice(dotIndex) : "";
  }

  function filenameFromContentDisposition(value) {
    const encoded = /filename\*\s*=\s*(?:UTF-8'')?([^;]+)/i.exec(value || "");
    const regular = /filename\s*=\s*(?:"([^"]+)"|([^;]+))/i.exec(value || "");
    const raw = encoded?.[1] || regular?.[1] || regular?.[2] || "";
    const trimmed = raw.trim().replace(/^['"]|['"]$/g, "");
    try {
      return decodeURIComponent(trimmed);
    } catch (_error) {
      return trimmed;
    }
  }

  function classifyDownload(url, mimeType = "", contentDisposition = "", suggestedFilename = "") {
    const normalizedMime = mimeType.split(";", 1)[0].trim().toLowerCase();
    const headerFilename = filenameFromContentDisposition(contentDisposition);
    const extension = extensionForName(headerFilename || suggestedFilename) || extensionForUrl(url);
    if (HLS_MIME_TYPES.has(normalizedMime)) return "HLS";
    if (DASH_MIME_TYPES.has(normalizedMime)) return "DASH";
    if (normalizedMime.startsWith("video/")) return "VIDEO";
    if (normalizedMime.startsWith("audio/")) return "AUDIO";
    if (DOCUMENT_MIMES.has(normalizedMime)) return "DOCUMENT";
    if (ARCHIVE_MIMES.has(normalizedMime)) return "ARCHIVE";
    if (FILE_MIMES.has(normalizedMime)) return "FILE";
    if (NON_DOWNLOAD_MIMES.has(normalizedMime)) return null;
    if (extension === ".m3u8") return "HLS";
    if (extension === ".mpd") return "DASH";
    if (VIDEO_EXTENSIONS.has(extension)) return "VIDEO";
    if (AUDIO_EXTENSIONS.has(extension)) return "AUDIO";
    if (DOCUMENT_EXTENSIONS.has(extension)) return "DOCUMENT";
    if (ARCHIVE_EXTENSIONS.has(extension)) return "ARCHIVE";
    if (FILE_EXTENSIONS.has(extension)) return "FILE";
    if (/\battachment\b/i.test(contentDisposition || "")) return "FILE";
    return null;
  }

  const classifyMedia = classifyDownload;

  function normalizeCandidate(candidate) {
    const url = stripFragment(candidate.url || "");
    const detectedType = candidate.detected_type || classifyDownload(
      url,
      candidate.mime_type || "",
      candidate.content_disposition || "",
      candidate.browser_filename || ""
    );
    if (!url || !detectedType) return null;
    return {
      url,
      page_url: stripFragment(candidate.page_url || ""),
      page_title: candidate.page_title || "",
      media_title: candidate.media_title || "",
      browser_filename: candidate.browser_filename || "",
      link_text: candidate.link_text || "",
      tab_id: Number.isInteger(candidate.tab_id) ? candidate.tab_id : -1,
      detected_type: detectedType,
      mime_type: candidate.mime_type || "",
      source: candidate.source || "webRequest",
      first_seen: Number.isFinite(candidate.first_seen) ? candidate.first_seen : Date.now(),
      content_length: Number.isFinite(candidate.content_length) ? candidate.content_length : 0,
      hls_kind: candidate.hls_kind || "",
      referer: candidate.referer || candidate.page_url || "",
      origin: candidate.origin || "",
      user_agent: candidate.user_agent || "",
      accept: candidate.accept || "",
      accept_language: candidate.accept_language || "",
      range: candidate.range || "",
      sec_fetch_dest: candidate.sec_fetch_dest || "",
      sec_fetch_mode: candidate.sec_fetch_mode || "",
      sec_fetch_site: candidate.sec_fetch_site || ""
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
    if (type === "DOCUMENT") return 15;
    if (type === "ARCHIVE") return 16;
    if (type === "FILE") return 17;
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
    classifyDownload,
    classifyMedia,
    deduplicateCandidates,
    extensionForUrl,
    filenameFromContentDisposition,
    normalizeCandidate,
    rankCandidates,
    stripFragment
  };
  globalObject.MediaDetection = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(globalThis);
