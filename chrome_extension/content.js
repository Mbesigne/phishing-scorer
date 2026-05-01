(function () {
  "use strict";

  /* ── Détection du client mail ── */
  const CLIENT = (() => {
    const h = location.hostname;
    if (h.includes("mail.google.com")) return "gmail";
    if (h.includes("outlook"))          return "outlook";
    if (h.includes("mail.yahoo.com"))   return "yahoo";
    return "unknown";
  })();

  if (CLIENT === "unknown") return;

  const BTN_ID = "prs-analyze-btn";

  /* ── Extrait toutes les URLs du corps de l'email ── */
  function extractUrls(container) {
    const text = container.innerText || container.textContent || "";
    const fromText = (text.match(/(https?:\/\/[^\s]+)/g) || []);
    const fromLinks = Array.from(container.querySelectorAll("a[href]"))
      .map((a) => a.href)
      .filter((h) => h.startsWith("http"));
    const all = [...new Set([...fromLinks, ...fromText])].filter(
      (u) => !u.includes("mail.google.com") && !u.includes("outlook.") && !u.includes("mail.yahoo.com")
    );
    return all;
  }

  /* ── Trouve le conteneur de l'email ouvert ── */
  function getEmailContainer() {
    if (CLIENT === "gmail") {
      return (
        document.querySelector("[data-message-id] .a3s") ||
        document.querySelector(".a3s")
      );
    }
    if (CLIENT === "outlook") {
      return document.querySelector('[aria-label="Message body"]');
    }
    if (CLIENT === "yahoo") {
      return (
        document.querySelector('[data-test-id="message-view-body-content"]') ||
        document.querySelector(".msg-body") ||
        document.querySelector("[data-test-id='rte']")
      );
    }
    return null;
  }

  /* ── Injecte le bouton dans la page ── */
  function injectButton() {
    if (document.getElementById(BTN_ID)) return; // déjà présent

    const container = getEmailContainer();
    if (!container) return;

    const btn = document.createElement("button");
    btn.id = BTN_ID;
    btn.textContent = "🎯 Analyser";
    btn.style.cssText = `
      position: fixed; bottom: 24px; right: 24px; z-index: 999999;
      padding: 10px 20px; border: none; border-radius: 999px; cursor: pointer;
      background: linear-gradient(135deg, #667eea, #764ba2);
      color: #fff; font-size: 13px; font-weight: 700;
      box-shadow: 0 4px 16px rgba(102,126,234,.5);
      font-family: 'Segoe UI', sans-serif;
      transition: opacity .2s;
    `;

    btn.addEventListener("click", () => analyzeEmail(btn));
    document.body.appendChild(btn);
  }

  /* ── Analyse l'email courant ── */
  function analyzeEmail(btn) {
    const container = getEmailContainer();
    if (!container) {
      alert("Phishing Scorer — Aucun email ouvert détecté.");
      return;
    }

    const urls = extractUrls(container);
    if (urls.length === 0) {
      alert("Phishing Scorer — Aucune URL trouvée dans cet email.");
      return;
    }

    const primaryUrl = urls[0];
    const emailText = (container.innerText || "").slice(0, 2000);

    btn.disabled = true;
    btn.textContent = "⏳ Analyse…";

    chrome.runtime.sendMessage(
      { action: "analyze", data: { url: primaryUrl, email_text: emailText, headers: "" } },
      (response) => {
        btn.disabled = false;
        btn.textContent = "🎯 Analyser";

        if (!response || !response.ok) {
          alert(
            "Phishing Scorer — Erreur :\n" + (response?.error || "Serveur non disponible.")
          );
          return;
        }

        const score = response.score ?? 0;
        const level = response.risk_level || "—";
        const details = (response.details || []).slice(0, 2).join("\n• ");

        alert(
          `🛡️ Phishing Risk Scorer\n` +
          `─────────────────────\n` +
          `Score : ${score}/100\n` +
          `Niveau : ${level}\n` +
          (details ? `\nIndicateurs :\n• ${details}` : "") +
          `\n─────────────────────\n` +
          `URL analysée : ${primaryUrl.slice(0, 80)}`
        );
      }
    );
  }

  /* ── Injecte le bouton toutes les 3 secondes ── */
  setInterval(injectButton, 3000);

  /* ── Passe initiale après chargement du DOM ── */
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", injectButton);
  } else {
    setTimeout(injectButton, 1500);
  }
})();
