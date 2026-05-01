/**
 * Phishing Risk Scorer — Content Script
 * Injecte un bouton "🛡️ Analyser" dans Gmail et Outlook.
 * Extrait URLs, texte et headers visibles, envoie au backend local.
 */

(function () {
  "use strict";

  const API_URL = "http://localhost:5000/analyze";

  /* ── Sélecteurs par client mail ── */
  const CLIENT = (() => {
    const host = location.hostname;
    if (host.includes("mail.google.com")) return "gmail";
    if (host.includes("outlook"))          return "outlook";
    return "unknown";
  })();

  const SELECTORS = {
    gmail: {
      emailContainers: '[data-message-id]',
      emailBody:       '.a3s',
      toolbar:         '.ade',
      subject:         'h2.hP',
    },
    outlook: {
      emailContainers: '[aria-label="Message body"], .ReadingPaneContent',
      emailBody:       '[aria-label="Message body"]',
      toolbar:         '[class*="ms-CommandBar"]',
      subject:         '[class*="subject"]',
    },
  };

  /* ── Style du bouton injecté ── */
  const BTN_STYLE = `
    display: inline-flex; align-items: center; gap: 5px;
    padding: 5px 12px; margin-left: 8px;
    background: linear-gradient(135deg, #7c3aed, #a855f7);
    color: #fff; font-size: 12px; font-weight: 700;
    border: none; border-radius: 6px; cursor: pointer;
    box-shadow: 0 2px 8px rgba(124,58,237,.4);
    transition: opacity .2s; z-index: 9999;
    font-family: 'Segoe UI', sans-serif;
    white-space: nowrap;
  `;

  /* ── Toast notification ── */
  function showToast(msg, color = "#7c3aed", duration = 3000) {
    const existing = document.getElementById("prs-toast");
    if (existing) existing.remove();

    const toast = document.createElement("div");
    toast.id = "prs-toast";
    toast.textContent = msg;
    toast.style.cssText = `
      position: fixed; bottom: 20px; right: 20px;
      background: ${color}; color: #fff; padding: 10px 18px;
      border-radius: 8px; font-size: 13px; font-weight: 600;
      box-shadow: 0 4px 16px rgba(0,0,0,.3); z-index: 99999;
      transition: opacity .3s; font-family: 'Segoe UI', sans-serif;
    `;
    document.body.appendChild(toast);
    setTimeout(() => { toast.style.opacity = "0"; setTimeout(() => toast.remove(), 300); }, duration);
  }

  /* ── Résultat overlay ── */
  function showResultOverlay(data) {
    const existing = document.getElementById("prs-overlay");
    if (existing) existing.remove();

    const score = data.score || 0;
    const color =
      score >= 70 ? "#f5576c" :
      score >= 50 ? "#fa709a" :
      score >= 30 ? "#fee140" : "#a8edea";

    const details = (data.details || []).slice(0, 5)
      .map(d => `<li style="margin-bottom:4px;font-size:12px;color:#e2e8f0">${d.substring(0,90)}</li>`)
      .join("");

    const overlay = document.createElement("div");
    overlay.id = "prs-overlay";
    overlay.style.cssText = `
      position: fixed; top: 60px; right: 20px;
      background: #16213e; border: 1px solid rgba(168,85,247,.3);
      border-radius: 12px; padding: 16px 20px; z-index: 99998;
      box-shadow: 0 8px 32px rgba(0,0,0,.5); min-width: 280px; max-width: 360px;
      font-family: 'Segoe UI', sans-serif;
    `;
    overlay.innerHTML = `
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px">
        <strong style="color:#a855f7;font-size:13px">🛡️ Phishing Risk Scorer</strong>
        <button id="prs-close" style="background:none;border:none;color:#94a3b8;cursor:pointer;font-size:16px">×</button>
      </div>
      <div style="display:flex;align-items:center;gap:12px;margin-bottom:10px">
        <div style="
          width:56px;height:56px;border-radius:50%;flex-shrink:0;
          display:flex;flex-direction:column;align-items:center;justify-content:center;
          background:${color}22;border:2px solid ${color};
        ">
          <span style="font-size:1.3rem;font-weight:800;color:${color}">${score}</span>
          <span style="font-size:9px;color:#94a3b8">/100</span>
        </div>
        <div>
          <div style="font-size:14px;font-weight:700;color:${color};margin-bottom:4px">${data.risk_level || "—"}</div>
          <div style="font-size:11px;color:#94a3b8">${data.domain || ""}</div>
        </div>
      </div>
      ${details ? `<ul style="list-style:none;padding:0;margin:0 0 10px 0">${details}</ul>` : ""}
      <div style="display:flex;gap:8px;flex-wrap:wrap">
        <button id="prs-open-dashboard" style="
          background:linear-gradient(135deg,#7c3aed,#a855f7);color:#fff;
          border:none;border-radius:6px;padding:5px 12px;font-size:11px;
          font-weight:700;cursor:pointer;
        ">📊 Rapport complet</button>
        <button id="prs-report-phishing" style="
          background:rgba(245,87,108,.15);color:#f5576c;
          border:1px solid rgba(245,87,108,.3);border-radius:6px;
          padding:5px 12px;font-size:11px;font-weight:700;cursor:pointer;
        ">🚨 Signaler</button>
      </div>
    `;

    document.body.appendChild(overlay);

    overlay.querySelector("#prs-close").addEventListener("click", () => overlay.remove());
    overlay.querySelector("#prs-open-dashboard").addEventListener("click", () => {
      window.open("http://localhost:5000", "_blank");
    });
    overlay.querySelector("#prs-report-phishing").addEventListener("click", () => {
      window.open("https://signal-spam.fr", "_blank");
      overlay.remove();
    });
  }

  /* ── Extraction du contenu de l'email ── */
  function extractEmailContent(container) {
    const bodyEl = CLIENT === "gmail"
      ? container.querySelector(".a3s") || container
      : container.querySelector('[aria-label="Message body"]') || container;

    const text = bodyEl ? bodyEl.innerText || bodyEl.textContent || "" : "";

    const links = Array.from((bodyEl || container).querySelectorAll("a[href]"))
      .map(a => a.href)
      .filter(href => href.startsWith("http") && !href.includes("mail.google.com") && !href.includes("outlook."))
      .slice(0, 20);

    return { text, links };
  }

  /* ── Envoi vers le backend ── */
  async function analyzeEmail(container, button) {
    const { text, links } = extractEmailContent(container);

    const primaryUrl = links[0] || window.location.href;

    button.disabled = true;
    button.textContent = "⏳ Analyse…";
    showToast("🔍 Analyse en cours…", "#7c3aed", 4000);

    try {
      const response = await fetch(API_URL, {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({
          url:        primaryUrl,
          email_text: text.slice(0, 2000),
          headers:    "",
        }),
      });

      if (!response.ok) throw new Error(`HTTP ${response.status}`);

      const data = await response.json();

      // Notifie le service worker (badge)
      chrome.runtime.sendMessage({ type: "ANALYSIS_RESULT", data });

      showToast(
        `${data.risk_level}  ${data.score}/100`,
        data.score >= 70 ? "#f5576c" : data.score >= 50 ? "#fa709a" : "#a8edea",
        5000
      );
      showResultOverlay(data);

    } catch (err) {
      showToast("❌ Serveur non disponible. Lancez python app.py", "#ef4444", 5000);
    } finally {
      button.disabled  = false;
      button.innerHTML = "🛡️ Analyser";
    }
  }

  /* ── Injection du bouton ── */
  function injectButton(emailContainer) {
    if (emailContainer.querySelector(".prs-btn")) return; // déjà injecté

    const button = document.createElement("button");
    button.className  = "prs-btn";
    button.innerHTML  = "🛡️ Analyser";
    button.style.cssText = BTN_STYLE;

    button.addEventListener("click", (e) => {
      e.stopPropagation();
      analyzeEmail(emailContainer, button);
    });

    // Point d'insertion : barre d'outils ou juste après le sujet
    const sel   = SELECTORS[CLIENT] || SELECTORS.gmail;
    const toolbar = emailContainer.querySelector(sel.toolbar)
      || emailContainer.closest("[role='main']")?.querySelector(sel.toolbar);

    if (toolbar) {
      toolbar.appendChild(button);
    } else {
      // Fallback : insère en haut de l'email
      emailContainer.insertAdjacentElement("afterbegin", button);
    }
  }

  /* ── MutationObserver : surveille l'ouverture de nouveaux emails ── */
  const observer = new MutationObserver(() => {
    const sel = SELECTORS[CLIENT] || SELECTORS.gmail;

    // Gmail : chaque email a un attribut data-message-id
    if (CLIENT === "gmail") {
      document.querySelectorAll("[data-message-id]").forEach(el => {
        if (el.querySelector(".a3s") && !el.querySelector(".prs-btn")) {
          injectButton(el);
        }
      });
    }

    // Outlook : panneau de lecture
    if (CLIENT === "outlook") {
      const readPane = document.querySelector('[aria-label="Message body"]')
        ?.closest('[class*="ReadingPane"]');
      if (readPane && !readPane.querySelector(".prs-btn")) {
        injectButton(readPane);
      }
    }
  });

  // Lance l'observation dès que le DOM est prêt
  observer.observe(document.body, { childList: true, subtree: true });

  // Passe initiale pour les emails déjà ouverts
  setTimeout(() => {
    if (CLIENT === "gmail") {
      document.querySelectorAll("[data-message-id]").forEach(el => {
        if (el.querySelector(".a3s")) injectButton(el);
      });
    }
  }, 2000);

})();
