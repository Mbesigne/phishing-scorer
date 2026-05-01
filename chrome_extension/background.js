const API_URL = "https://phishing-scorer.onrender.com/analyze";

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message.action !== "analyze") return false;

  const { url, email_text = "", headers = "" } = message.data || {};

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 5000);

  fetch(API_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, email_text, headers_text: headers }),
    signal: controller.signal,
  })
    .then((res) => {
      clearTimeout(timeout);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json();
    })
    .then((data) => {
      const score = data.score ?? 0;
      chrome.action.setBadgeText({ text: String(score) });
      chrome.action.setBadgeBackgroundColor({
        color:
          score >= 70 ? "#ef4444" :
          score >= 50 ? "#f97316" :
          score >= 30 ? "#eab308" : "#22c55e",
      });
      sendResponse({ ok: true, ...data });
    })
    .catch((err) => {
      clearTimeout(timeout);
      sendResponse({
        ok: false,
        error: err.name === "AbortError" ? "Timeout (5s) — serveur trop lent" : err.message,
      });
    });

  return true; // keep message channel open for async sendResponse
});

chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (changeInfo.status === "loading") {
    chrome.action.setBadgeText({ text: "", tabId });
  }
});
