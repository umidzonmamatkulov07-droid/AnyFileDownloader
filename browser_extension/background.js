const NATIVE_HOST_NAME = "com.anyfiledownloader.native_host";

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type !== "send-download") {
    return false;
  }

  const request = {
    action: "download",
    url: message.url,
    page_url: message.pageUrl || "",
    title: message.title || ""
  };

  chrome.runtime.sendNativeMessage(NATIVE_HOST_NAME, request, (response) => {
    if (chrome.runtime.lastError) {
      sendResponse({ ok: false, error: chrome.runtime.lastError.message });
      return;
    }
    sendResponse(response || { ok: false, error: "Native host returned no response" });
  });

  return true;
});
