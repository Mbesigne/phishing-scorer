# Phishing Risk Scorer v2

Outil complet de détection de phishing : backend Python/Flask, interface web multi-onglets et extension Chrome pour Gmail/Outlook.

## Fonctionnalités

| Détecteur | Points | Description |
|-----------|--------|-------------|
| URL raccourcie | +25 | bit.ly, tinyurl, goo.gl, rebrand.ly… |
| Langage d'urgence | +20 | "urgent", "vérifier", "compte suspendu"… |
| Typosquattage | +30 | SequenceMatcher ≥ 70% vs marques connues |
| Adresse IP directe | +35 | 192.168.x.x au lieu d'un domaine |
| Extension suspecte | +15 | .tk, .ml, .ga, .xyz, .work… |
| SSL invalide/absent | +30–40 | HTTP → +30, cert invalide → +40 |
| Headers SMTP | cumulatif | SPF/DKIM/DMARC, From≠Reply-To, IPs privées… |
| VirusTotal | +50 | Optionnel (clé API requise) |
| Contenu page | +60 | Formulaire HTTP, iframes cachées, JS redirects |

## Installation

```bash
# 1. Cloner / télécharger le projet
cd antivirus

# 2. Installer les dépendances
pip install -r requirements.txt

# 3. Configurer l'environnement (optionnel)
cp .env.example .env
# éditez .env pour ajouter votre clé VirusTotal

# 4. Lancer le serveur
python app.py
# → http://localhost:5000
```

## Extension Chrome

```bash
# 1. Générer les icônes (nécessite Pillow)
cd chrome_extension
pip install Pillow
python create_icons.py

# 2. Charger dans Chrome
# → chrome://extensions/
# → Activer le "Mode développeur"
# → "Charger l'extension non empaquetée"
# → Sélectionner le dossier chrome_extension/

# 3. Ouvrir Gmail ou Outlook
# → Un bouton "🛡️ Analyser" apparaît sur chaque email
```

## Structure du projet

```
antivirus/
├── phishing_analyzer.py       # Moteur d'analyse — 10 vecteurs
├── app.py                     # Serveur Flask + SQLite + 9 routes API
├── templates/
│   └── index.html             # Interface 4 onglets (Analyser/Historique/Guide/API)
├── chrome_extension/
│   ├── manifest.json          # Manifest v3
│   ├── background.js          # Service worker + badge
│   ├── content.js             # Injection Gmail/Outlook
│   ├── popup.html             # Interface popup
│   ├── popup.js               # Logique popup
│   ├── create_icons.py        # Génération des icônes PNG
│   └── icons/                 # Icônes générées (16/48/128px)
├── requirements.txt
├── .env.example
└── README.md
```

## API REST

```
POST /analyze           → Analyse complète (url, email_text, headers)
GET  /api/analyze?url=  → Analyse rapide par paramètre
GET  /history           → 50 dernières analyses (filtrable)
DELETE /history/<id>    → Supprime une analyse
GET  /stats             → Statistiques globales
POST /batch-analyze     → Lot jusqu'à 50 URLs
GET  /export/csv        → Export CSV
GET  /export/json       → Export JSON
GET  /health            → Healthcheck {"status":"ok","version":"2.0"}
```

## Niveaux de risque

| Niveau | Score | Action |
|--------|-------|--------|
| 🔴 DANGER | ≥ 70 | Ne pas cliquer — signaler |
| 🟠 ÉLEVÉ | ≥ 50 | Très prudent — vérifier l'expéditeur |
| 🟡 MOYEN | ≥ 30 | Vérifier avant toute action |
| 🟢 FAIBLE | < 30 | Aucun indicateur majeur |

## Déploiement (Render.com — gratuit)

```bash
# 1. Créer un compte sur render.com
# 2. New → Web Service → connecter le repo GitHub
# 3. Build Command : pip install -r requirements.txt
# 4. Start Command : python app.py
# 5. Ajouter les variables d'environnement dans Settings → Environment
```

## Tests manuels

```bash
python phishing_analyzer.py
```

Résultats attendus :
- `amaz0n.com` + headers frauduleux + urgence → score élevé (🔴 DANGER)
- `https://amazon.com` → score 0 (🟢 FAIBLE) + SSL valide
- `http://192.168.1.1/bank` → score 65 (🟠 ÉLEVÉ)
- `paypal-secure.tk` + urgence → score critique (🔴 DANGER)
