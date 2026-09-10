const urlInput = document.querySelector("#download-url");
const sendButton = document.querySelector("#send-download");
const statusText = document.querySelector("#status");

let activePage = { url: "", title: "" };

chrome.tabs.query({ active: true, currentWindow: true }, ([tab]) => {
  if (!tab) {
    return;
  }
  activePage = { url: tab.url || "", title: tab.title || "" };
  if (/^https?:\/\//i.test(activePage.url)) {
    urlInput.value = activePage.url;
  }
});

sendButton.addEventListener("click", () => {
  const url = urlInput.value.trim();
  if (!/^https?:\/\//i.test(url) && !/^ftp:\/\//i.test(url)) {
    statusText.textContent = "Enter a valid HTTP, HTTPS, or FTP URL.";
    return;
  }

  sendButton.disabled = true;
  statusText.textContent = "Sending…";
  chrome.runtime.sendMessage(
    {
      type: "send-download",
      url,
      pageUrl: activePage.url,
      title: activePage.title
    },
    (response) => {
      sendButton.disabled = false;
      if (chrome.runtime.lastError) {
        statusText.textContent = chrome.runtime.lastError.message;
        return;
      }
      statusText.textContent = response?.ok
        ? "Download request sent."
        : `Could not send request: ${response?.error || "Unknown error"}`;
    }
  );
});
