# Phishing Risk Scorer — Extension Chrome

Extension Chrome Manifest V3 qui injecte un bouton d'analyse dans Gmail, Outlook et Yahoo Mail, et communique avec le backend hébergé sur Render.com.

## Installation rapide

### 1. Générer les icônes (nécessite Pillow)

```bash
cd chrome_extension
pip install Pillow
python create_icons.py
# → icons/icon-16.png, icons/icon-48.png, icons/icon-128.png
```

### 2. Charger dans Chrome

1. Ouvrir `chrome://extensions/`
2. Activer le **Mode développeur** (coin supérieur droit)
3. Cliquer **Charger l'extension non empaquetée**
4. Sélectionner le dossier `chrome_extension/`

L'icône 🛡️ apparaît dans la barre d'outils Chrome.

---

## Utilisation

### Popup (icône dans la barre)

| Bouton | Action |
|--------|--------|
| 📊 Ouvrir le Tableau de Bord | Ouvre `phishing-scorer.onrender.com` dans un nouvel onglet |
| 🧪 Tester l'Extension | Analyse `amaz0n.com/login` — confirme que le serveur répond |

### Dans Gmail / Outlook / Yahoo Mail

1. Ouvrir un email
2. Attendre l'apparition du bouton **🎯 Analyser** (coin inférieur droit)
3. Cliquer → l'extension extrait les URLs du message et les envoie au serveur
4. Une alerte affiche le score (0–100), le niveau de risque et les 2 premiers indicateurs

---

## Architecture

```
popup.html / popup.js
  └── chrome.runtime.sendMessage({action:"analyze", data:{url, email_text, headers}})
          │
          ▼
background.js (service worker)
  └── fetch POST → https://phishing-scorer.onrender.com/analyze
  └── AbortController timeout 5 secondes
  └── Met à jour le badge de l'icône (score + couleur)
          │
          ▼
content.js (injecté dans la page mail)
  └── Détecte Gmail / Outlook / Yahoo via location.hostname
  └── Injecte le bouton 🎯 toutes les 3 secondes (setInterval)
  └── Extrait URLs via querySelectorAll("a[href]") + regex /(https?:\/\/[^\s]+)/g
  └── Affiche le résultat via alert()
```

---

## Serveur Render.com

Le backend tourne sur : **https://phishing-scorer.onrender.com**

> **Note :** Render.com met les services gratuits en veille après 15 minutes d'inactivité.
> La première requête peut prendre 20–30 secondes le temps du démarrage à froid.
> Utilisez **🧪 Tester l'Extension** pour réveiller le serveur avant d'analyser.

---

## Niveaux de risque

| Badge | Score | Couleur |
|-------|-------|---------|
| 🔴 DANGER | ≥ 70 | Rouge |
| 🟠 ÉLEVÉ  | ≥ 50 | Orange |
| 🟡 MOYEN  | ≥ 30 | Jaune |
| 🟢 FAIBLE | < 30 | Vert |

---

## Dépannage

**Le bouton 🎯 n'apparaît pas**
- Vérifier que l'extension est bien chargée dans `chrome://extensions/`
- Ouvrir un email (pas juste la liste) — le bouton n'apparaît qu'avec un email ouvert
- Attendre 3 secondes (le setInterval tente toutes les 3s)
- Recharger la page mail

**"Aucune URL trouvée"**
- L'email ne contient pas de liens HTTP(S) — normal pour certains emails texte
- Les liens internes (mail.google.com, outlook.com) sont exclus intentionnellement

**Timeout / Serveur non disponible**
- Le serveur Render.com est peut-être en veille — attendre 30s et réessayer
- Tester manuellement : ouvrir `https://phishing-scorer.onrender.com/health`

**Badge ne se met pas à jour**
- Recharger l'extension dans `chrome://extensions/` → bouton 🔄
