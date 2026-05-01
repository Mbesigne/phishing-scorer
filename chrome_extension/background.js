/**
 * Phishing Risk Scorer — Service Worker (background.js)
 * Gère les messages, met à jour le badge et stocke l'historique Chrome.
 */

const API_BASE = "http://localhost:5000";

/* ── Réception des résultats d'analyse depuis content.js ── */
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === "ANALYSIS_RESULT") {
    const data  = message.data || {};
    const score = data.score ?? 0;

    // Couleur du badge selon le niveau de risque
    const badgeColor =
      score >= 70 ? "#f5576c" :
      score >= 50 ? "#fa709a" :
      score >= 30 ? "#fee140" : "#a8edea";

    // Met à jour le badge de l'icône pour cet onglet
    if (sender.tab?.id) {
      chrome.action.setBadgeText({ text: String(score), tabId: sender.tab.id });
      chrome.action.setBadgeBackgroundColor({ color: badgeColor, tabId: sender.tab.id });
    }

    // Sauvegarde dans chrome.storage.local (max 20 entrées)
    chrome.storage.local.get(["analysisHistory"], (result) => {
      const history = result.analysisHistory || [];
      history.unshift({
        url:        data.url || "",
        score:      score,
        risk_level: data.risk_level || "",
        timestamp:  data.analysis_timestamp || new Date().toISOString(),
        domain:     data.domain || "",
      });
      chrome.storage.local.set({ analysisHistory: history.slice(0, 20) });
    });

    sendResponse({ ok: true });
  }

  // Requête du popup pour obtenir l'historique
  if (message.type === "GET_HISTORY") {
    chrome.storage.local.get(["analysisHistory"], (result) => {
      sendResponse({ history: result.analysisHistory || [] });
    });
    return true; // async
  }

  // Efface le badge quand l'onglet change
  if (message.type === "CLEAR_BADGE" && sender.tab?.id) {
    chrome.action.setBadgeText({ text: "", tabId: sender.tab.id });
  }

  return true;
});

/* ── Efface le badge quand on navigue vers une nouvelle page ── */
chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (changeInfo.status === "loading") {
    chrome.action.setBadgeText({ text: "", tabId });
  }
});
