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
    "text/rtf", "application/rtf", "text/csv",
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
  const AMBIGUOUS_TEXT_EXTENSIONS = new Set([".txt"]);
  const MIN_AMBIGUOUS_TEXT_BYTES = 8 * 1024;
  const SOURCE_PRIORITY = new Map([
    ["chrome_download", 6],
    ["webRequest", 5],
    ["anchor_download", 4],
    ["anchor_link", 3],
    ["media_element", 2],
    ["performance", 1]
  ]);

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

  function safeBasename(filename) {
    return String(filename || "")
      .replace(/\\/g, "/")
      .split("/")
      .pop()
      .replace(/[\u0000-\u001f\u007f]/g, "")
      .trim();
  }

  function isBlobUrl(url) {
    return /^blob:/i.test(String(url || ""));
  }

  function candidateFromDownloadItem(item) {
    if (!item || !Number.isInteger(item.id)) return null;
    const originalUrl = stripFragment(item.url || "");
    const finalUrl = stripFragment(item.finalUrl || item.url || "");
    const redirectChain = [...new Set([originalUrl, finalUrl].filter(Boolean))];
    const filename = safeBasename(item.filename || "");
    const detectedType = classifyDownload(finalUrl, item.mime || "", "", filename) ||
      (isBlobUrl(finalUrl) ? "FILE" : null);
    if (!detectedType) return null;
    const parsedStartTime = Date.parse(item.startTime || "");
    return {
      url: finalUrl,
      original_url: originalUrl,
      final_url: finalUrl,
      redirect_chain: redirectChain,
      detected_type: detectedType,
      mime_type: item.mime || "",
      browser_filename: filename,
      content_length: Number.isFinite(item.totalBytes) && item.totalBytes > 0
        ? item.totalBytes
        : (Number.isFinite(item.fileSize) && item.fileSize > 0
          ? item.fileSize
          : (Number.isFinite(item.bytesReceived) ? item.bytesReceived : 0)),
      download_id: item.id,
      download_state: item.state || "in_progress",
      download_error: item.error || "",
      evidence_strength: 3,
      source: "chrome_download",
      first_seen: Number.isFinite(parsedStartTime) ? parsedStartTime : Date.now(),
      is_browser_owned: isBlobUrl(finalUrl)
    };
  }

  function applyDownloadDelta(item, delta) {
    if (!item || !delta || item.id !== delta.id) return item;
    const updated = { ...item };
    for (const field of [
      "url", "finalUrl", "filename", "mime", "totalBytes", "fileSize", "startTime", "state", "error"
    ]) {
      if (Object.prototype.hasOwnProperty.call(delta, field)) updated[field] = delta[field]?.current;
    }
    return updated;
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
    if (
      NON_DOWNLOAD_MIMES.has(normalizedMime) ||
      normalizedMime.startsWith("image/") ||
      normalizedMime.startsWith("font/") ||
      normalizedMime === "text/css" ||
      normalizedMime === "text/javascript" ||
      normalizedMime === "application/javascript"
    ) return null;
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

  function candidateEvidenceStrength(candidate) {
    const detectedType = candidate.detected_type || classifyDownload(
      candidate.url || "",
      candidate.mime_type || "",
      candidate.content_disposition || "",
      candidate.browser_filename || ""
    );
    if (!detectedType) return 0;
    if (["HLS", "DASH", "VIDEO", "AUDIO"].includes(detectedType)) return 3;
    if (["ping", "csp_report"].includes(candidate.resource_type || "")) return 0;

    if (candidate.source === "chrome_download") return 3;

    const disposition = candidate.content_disposition || "";
    const dispositionFilename = filenameFromContentDisposition(disposition);
    const browserFilename = candidate.browser_filename || "";
    if (/\battachment\b/i.test(disposition) || dispositionFilename) return 3;

    const normalizedMime = String(candidate.mime_type || "").split(";", 1)[0].trim().toLowerCase();
    if (
      DOCUMENT_MIMES.has(normalizedMime) ||
      ARCHIVE_MIMES.has(normalizedMime) ||
      FILE_MIMES.has(normalizedMime)
    ) return 3;

    if (
      (candidate.source === "anchor_download" || candidate.is_browser_owned) &&
      (browserFilename || isBlobUrl(candidate.url))
    ) return 2;
    if (Array.isArray(candidate.redirect_chain) && candidate.redirect_chain.length > 1) return 2;

    const extension = extensionForName(browserFilename) || extensionForUrl(candidate.url || "");
    if (!AMBIGUOUS_TEXT_EXTENSIONS.has(extension)) {
      if (
        DOCUMENT_EXTENSIONS.has(extension) ||
        ARCHIVE_EXTENSIONS.has(extension) ||
        FILE_EXTENSIONS.has(extension)
      ) return 1;
      return detectedType === "FILE" ? 1 : 0;
    }

    if (candidate.source === "anchor_link") return 2;
    const method = String(candidate.request_method || "GET").toUpperCase();
    const resourceType = candidate.resource_type || "";
    const contentLength = Number(candidate.content_length) || 0;
    if (
      candidate.source === "webRequest" &&
      ["GET", "HEAD"].includes(method) &&
      ["main_frame", "sub_frame"].includes(resourceType) &&
      contentLength >= MIN_AMBIGUOUS_TEXT_BYTES
    ) return 1;
    return 0;
  }

  function shouldIncludeCandidate(candidate) {
    return candidateEvidenceStrength(candidate) > 0;
  }

  const classifyMedia = classifyDownload;

  function normalizeCandidate(candidate) {
    const redirectChain = Array.isArray(candidate.redirect_chain)
      ? [...new Set(candidate.redirect_chain.map(stripFragment).filter(Boolean))]
      : [];
    const finalUrl = stripFragment(candidate.final_url || redirectChain.at(-1) || candidate.url || "");
    const originalUrl = stripFragment(candidate.original_url || redirectChain[0] || candidate.url || "");
    const url = finalUrl || originalUrl;
    const browserFilename = safeBasename(candidate.browser_filename || "");
    const detectedType = candidate.detected_type || classifyDownload(
      url,
      candidate.mime_type || "",
      candidate.content_disposition || "",
      browserFilename
    );
    if (!url || !detectedType) return null;
    return {
      url,
      original_url: originalUrl,
      final_url: finalUrl,
      redirect_chain: redirectChain,
      page_url: stripFragment(candidate.page_url || ""),
      page_title: candidate.page_title || "",
      media_title: candidate.media_title || "",
      browser_filename: browserFilename,
      link_text: candidate.link_text || "",
      tab_id: Number.isInteger(candidate.tab_id) ? candidate.tab_id : -1,
      detected_type: detectedType,
      mime_type: candidate.mime_type || "",
      source: candidate.source || "webRequest",
      first_seen: Number.isFinite(candidate.first_seen) ? candidate.first_seen : Date.now(),
      content_length: Number.isFinite(candidate.content_length) ? candidate.content_length : 0,
      evidence_strength: Number.isFinite(candidate.evidence_strength)
        ? candidate.evidence_strength
        : candidateEvidenceStrength(candidate),
      content_disposition: candidate.content_disposition || "",
      resource_type: candidate.resource_type || "",
      request_method: candidate.request_method || "",
      download_id: Number.isInteger(candidate.download_id) ? candidate.download_id : -1,
      download_state: candidate.download_state || "",
      download_error: candidate.download_error || "",
      is_browser_owned: Boolean(candidate.is_browser_owned || isBlobUrl(url)),
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

  function candidateIdentityUrls(candidate) {
    return new Set([
      candidate.url,
      candidate.original_url,
      candidate.final_url,
      ...(Array.isArray(candidate.redirect_chain) ? candidate.redirect_chain : [])
    ].map(stripFragment).filter(Boolean));
  }

  function candidatesMatch(left, right) {
    if (
      Number.isInteger(left.download_id) && left.download_id >= 0 &&
      Number.isInteger(right.download_id) && right.download_id >= 0 &&
      left.download_id === right.download_id
    ) return true;
    const leftUrls = candidateIdentityUrls(left);
    const rightUrls = candidateIdentityUrls(right);
    const overlaps = [...rightUrls].some((url) => leftUrls.has(url));
    if (!overlaps) return false;
    if (leftUrls.size === 1 || rightUrls.size === 1) return true;
    const leftFinal = stripFragment(left.final_url || left.url || "");
    const rightFinal = stripFragment(right.final_url || right.url || "");
    return Boolean(leftFinal && leftFinal === rightFinal);
  }

  function mergeCandidates(existing, incoming) {
    const existingEvidence = Number(existing.evidence_strength) || 0;
    const incomingEvidence = Number(incoming.evidence_strength) || 0;
    const existingPriority = SOURCE_PRIORITY.get(existing.source) || 0;
    const incomingPriority = SOURCE_PRIORITY.get(incoming.source) || 0;
    const incomingIsPrimary =
      incomingEvidence > existingEvidence ||
      (incomingEvidence === existingEvidence && incomingPriority >= existingPriority);
    const primary = incomingIsPrimary ? incoming : existing;
    const secondary = incomingIsPrimary ? existing : incoming;
    const merged = { ...secondary, ...primary };
    for (const [key, value] of Object.entries(secondary)) {
      if (merged[key] === "" || merged[key] === -1 || merged[key] === undefined) merged[key] = value;
    }
    merged.first_seen = Math.min(existing.first_seen || Infinity, incoming.first_seen || Infinity);
    if (!Number.isFinite(merged.first_seen)) merged.first_seen = Date.now();
    merged.content_length = Math.max(Number(existing.content_length) || 0, Number(incoming.content_length) || 0);
    merged.evidence_strength = Math.max(existingEvidence, incomingEvidence);
    merged.redirect_chain = [...new Set([
      ...(existing.redirect_chain || []),
      ...(incoming.redirect_chain || [])
    ].map(stripFragment).filter(Boolean))];
    merged.original_url = merged.redirect_chain[0] || existing.original_url || incoming.original_url || merged.url;
    merged.final_url = primary.final_url || secondary.final_url || merged.redirect_chain.at(-1) || merged.url;
    if (incoming.download_state) merged.download_state = incoming.download_state;
    if (incoming.download_error) merged.download_error = incoming.download_error;
    merged.url = merged.final_url;
    merged.is_browser_owned = Boolean(existing.is_browser_owned || incoming.is_browser_owned || isBlobUrl(merged.url));
    return merged;
  }

  function deduplicateCandidates(existingCandidates, candidate, maximum = Number.POSITIVE_INFINITY) {
    const normalized = normalizeCandidate(candidate);
    if (!normalized) return existingCandidates.slice();

    const existingIndex = existingCandidates.findIndex((item) => candidatesMatch(item, normalized));
    if (existingIndex >= 0) {
      const updated = existingCandidates.slice();
      updated[existingIndex] = mergeCandidates(existingCandidates[existingIndex], normalized);
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
    const evidenceStrength = Number.isFinite(candidate.evidence_strength)
      ? candidate.evidence_strength
      : candidateEvidenceStrength(candidate);
    if (type === "DOCUMENT") return evidenceStrength >= 3 ? 15 : evidenceStrength === 2 ? 18 : 55;
    if (type === "ARCHIVE") return evidenceStrength >= 3 ? 16 : evidenceStrength === 2 ? 19 : 56;
    if (type === "FILE") return evidenceStrength >= 3 ? 17 : evidenceStrength === 2 ? 20 : 57;
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

  function resolveCandidateTabId(observedTabId, capturedTabId) {
    if (Number.isInteger(observedTabId) && observedTabId >= 0) return observedTabId;
    if (Number.isInteger(capturedTabId) && capturedTabId >= 0) return capturedTabId;
    return -1;
  }

  const api = {
    applyDownloadDelta,
    candidateRank,
    candidateEvidenceStrength,
    candidateFromDownloadItem,
    candidateIdentityUrls,
    candidatesMatch,
    classifyDownload,
    classifyMedia,
    deduplicateCandidates,
    extensionForUrl,
    filenameFromContentDisposition,
    isBlobUrl,
    normalizeCandidate,
    rankCandidates,
    resolveCandidateTabId,
    safeBasename,
    shouldIncludeCandidate,
    stripFragment
  };
  globalObject.MediaDetection = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(globalThis);
