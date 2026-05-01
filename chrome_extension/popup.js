/**
 * Phishing Risk Scorer — Popup Script
 * Analyse la page courante et affiche l'historique récent.
 */

const API_URL = "http://localhost:5000/analyze";

/* ── Utilitaires ── */
const esc = s => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

function scoreClasses(score) {
  if (score >= 70) return { circle: "c-danger",   pill: "pill-danger"   };
  if (score >= 50) return { circle: "c-high",     pill: "pill-high"     };
  if (score >= 30) return { circle: "c-moderate", pill: "pill-moderate" };
  return                  { circle: "c-safe",      pill: "pill-safe"     };
}

/* ── Affichage du résultat ── */
function displayResult(data) {
  const score = data.score ?? 0;
  const { circle, pill } = scoreClasses(score);

  document.getElementById("resultArea").style.display = "block";

  const circ = document.getElementById("scoreCircle");
  circ.className = "score-circle " + circle;
  document.getElementById("scoreNum").textContent = score;

  const badge = document.getElementById("riskBadge");
  badge.className = "risk-badge " + pill;
  badge.textContent = data.risk_level || "—";

  document.getElementById("recoText").textContent =
    (data.recommendation || "").substring(0, 120) + (data.recommendation?.length > 120 ? "…" : "");

  // Top 3 indicateurs
  const dets = (data.details || []).slice(0, 3);
  const list = document.getElementById("detMini");
  list.innerHTML = dets.map(d => {
    const isOk  = d.startsWith("🔒") || d.startsWith("✅");
    const isWarn = d.startsWith("⚠️") || d.startsWith("🔴");
    const cls   = isOk ? "ok" : isWarn ? "warn" : "";
    return `<li class="${cls}">${esc(d.substring(0, 80))}</li>`;
  }).join("");
}

/* ── Historique (depuis chrome.storage via background) ── */
function loadHistory() {
  chrome.runtime.sendMessage({ type: "GET_HISTORY" }, (response) => {
    const history = response?.history || [];
    const container = document.getElementById("historyList");

    if (!history.length) {
      document.getElementById("historyMini").style.display = "none";
      return;
    }

    container.innerHTML = history.slice(0, 5).map(entry => {
      const { circle } = scoreClasses(entry.score || 0);
      const cls = circle.replace("c-", "pill-");
      const shortUrl = (entry.url || "").substring(0, 42);
      return `<div class="h-item">
        <span class="h-score-sm ${cls}">${entry.score}</span>
        <span class="h-url" title="${esc(entry.url || "")}">${esc(shortUrl)}${entry.url?.length > 42 ? "…" : ""}</span>
      </div>`;
    }).join("");
  });
}

/* ── Analyse de la page courante ── */
async function analyzeCurrent(url) {
  const btn   = document.getElementById("analyzeBtn");
  const spin  = document.getElementById("spin");
  const label = document.getElementById("btnLabel");
  const errEl = document.getElementById("errorMsg");

  errEl.style.display = "none";
  btn.disabled = true;
  spin.style.display = "inline-block";
  label.textContent = "Analyse en cours…";

  try {
    const res = await fetch(API_URL, {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({ url }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.error || `Erreur HTTP ${res.status}`);
    }

    const data = await res.json();

    // Notifie le background pour le badge
    chrome.runtime.sendMessage({ type: "ANALYSIS_RESULT", data });

    displayResult(data);
    loadHistory(); // refresh

  } catch (err) {
    errEl.textContent = err.message.includes("Failed to fetch")
      ? "❌ Serveur non disponible. Lancez : python app.py"
      : `❌ ${err.message}`;
    errEl.style.display = "block";
  } finally {
    btn.disabled = false;
    spin.style.display = "none";
    label.textContent = "🔐 Analyser cette page";
  }
}

/* ── Init ── */
document.addEventListener("DOMContentLoaded", async () => {
  // Récupère l'URL de l'onglet actif
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const url = tab?.url || "";
  const urlEl = document.getElementById("currentUrl");
  urlEl.textContent = url.length > 55 ? url.substring(0, 55) + "…" : url;
  urlEl.title = url;

  // Bouton analyser
  document.getElementById("analyzeBtn").addEventListener("click", () => {
    if (url) analyzeCurrent(url);
  });

  // Bouton dashboard
  document.getElementById("openDashboard").addEventListener("click", () => {
    chrome.tabs.create({ url: "http://localhost:5000" });
  });

  // Charge l'historique
  loadHistory();

  // Si l'URL n'est pas HTTP(S), désactive le bouton analyser
  if (!url.startsWith("http")) {
    document.getElementById("analyzeBtn").disabled = true;
    document.getElementById("btnLabel").textContent = "⚠️ URL non analysable";
  }
});
