const DASHBOARD_URL = "https://phishing-scorer.onrender.com";
const TEST_URL      = "https://amaz0n.com/login";

function openDashboard() {
  chrome.tabs.create({ url: DASHBOARD_URL });
}

async function testAnalysis() {
  const btn   = document.getElementById("btnTest");
  const spin  = document.getElementById("spin");
  const label = document.getElementById("btnTestLabel");

  btn.disabled = true;
  spin.style.display = "inline-block";
  label.textContent  = "Analyse en cours…";

  chrome.runtime.sendMessage(
    { action: "analyze", data: { url: TEST_URL, email_text: "Urgent ! Votre compte Amazon est suspendu.", headers: "" } },
    (response) => {
      btn.disabled = false;
      spin.style.display = "none";
      label.textContent  = "🧪 Tester l'Extension";

      if (!response || !response.ok) {
        alert(
          "Phishing Scorer — Erreur de connexion :\n" +
          (response?.error || "Serveur non disponible.\nVérifiez que phishing-scorer.onrender.com est actif.")
        );
        return;
      }

      const score   = response.score ?? 0;
      const level   = response.risk_level || "—";
      const details = (response.details || []).slice(0, 2).join("\n• ");

      alert(
        `🛡️ Test — Phishing Risk Scorer\n` +
        `══════════════════════════════\n` +
        `URL testée : ${TEST_URL}\n` +
        `Score      : ${score}/100\n` +
        `Niveau     : ${level}\n` +
        (details ? `\nIndicateurs :\n• ${details}\n` : "") +
        `══════════════════════════════\n` +
        `✅ Extension opérationnelle !`
      );
    }
  );
}

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("btnDashboard").addEventListener("click", openDashboard);
  document.getElementById("btnTest").addEventListener("click", testAnalysis);
});
