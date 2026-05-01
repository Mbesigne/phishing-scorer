"""
Phishing Risk Scorer v2 — Serveur Flask avec SQLite
Expose une API REST complète pour le frontend et l'extension Chrome.
"""

import json
import os
import csv
import io
import sqlite3
import logging
from datetime import datetime
from flask import Flask, render_template, request, jsonify, Response
from phishing_analyzer import calculate_phishing_score, hash_analysis

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DATABASE_PATH = os.environ.get("DATABASE_PATH", "phishing_history.db")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)


# ---------------------------------------------------------------------------
# CORS — nécessaire pour l'extension Chrome (localhost:5000)
# ---------------------------------------------------------------------------

@app.after_request
def add_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
    return response


@app.route("/", defaults={"path": ""}, methods=["OPTIONS"])
@app.route("/<path:path>", methods=["OPTIONS"])
def handle_options(path):
    return "", 204


# ---------------------------------------------------------------------------
# SQLite
# ---------------------------------------------------------------------------

def get_db() -> sqlite3.Connection:
    """Ouvre une connexion SQLite avec row_factory pour accès par nom de colonne."""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Crée la base de données et les tables si elles n'existent pas."""
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS analyses (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            url         TEXT    NOT NULL,
            score       INTEGER NOT NULL,
            risk_level  TEXT    NOT NULL,
            timestamp   DATETIME DEFAULT CURRENT_TIMESTAMP,
            hash        TEXT    UNIQUE,
            email_domain TEXT,
            details     TEXT,
            confidence  INTEGER
        )
    """)
    conn.commit()
    conn.close()
    logger.info("Base de données initialisée : %s", DATABASE_PATH)


def save_analysis(result: dict) -> int | None:
    """Enregistre une analyse dans la base. Retourne l'ID inséré."""
    try:
        h = hash_analysis(result.get("url", ""), result.get("score", 0))
        domain = result.get("domain", "")
        conn = get_db()
        cur = conn.execute(
            """INSERT OR IGNORE INTO analyses
               (url, score, risk_level, hash, email_domain, details, confidence)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                result.get("url", ""),
                result.get("score", 0),
                result.get("risk_level", ""),
                h,
                domain,
                json.dumps(result.get("details", []), ensure_ascii=False),
                result.get("confidence", 0),
            ),
        )
        conn.commit()
        row_id = cur.lastrowid
        conn.close()
        return row_id
    except Exception as exc:
        logger.error("Erreur sauvegarde analyse : %s", exc)
        return None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    """Page principale — interface web."""
    return render_template("index.html")


@app.route("/analyze", methods=["POST"])
def analyze():
    """
    Analyse phishing complète.
    Reçoit : JSON { url, email_text, headers }
    Retourne : JSON avec score, risk_level, details, confidence, etc.
    """
    data = request.get_json(force=True, silent=True) or {}

    url        = data.get("url", "").strip()
    email_text = data.get("email_text", "").strip()
    headers    = data.get("headers", "").strip()

    if not url:
        return jsonify({"error": "Le champ 'url' est requis."}), 400

    result = calculate_phishing_score(url, email_text, headers)

    # Persistance en base
    row_id = save_analysis(result)
    result["id"] = row_id

    logger.info("Analyse %s → score=%d %s", url[:60], result["score"], result["risk_level"])
    return jsonify(result)


@app.route("/api/analyze")
def api_analyze_get():
    """
    API simplifiée pour intégration externe.
    GET /api/analyze?url=https://...
    """
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"error": "Paramètre 'url' requis."}), 400

    result = calculate_phishing_score(url)
    save_analysis(result)
    return jsonify(result)


@app.route("/history")
def history():
    """
    Retourne les 50 dernières analyses.
    Filtres optionnels : ?min_score=X&max_score=Y&domain=Z&limit=N
    """
    min_score = int(request.args.get("min_score", 0))
    max_score = int(request.args.get("max_score", 100))
    domain    = request.args.get("domain", "").strip()
    limit     = min(int(request.args.get("limit", 50)), 200)

    conn = get_db()
    query  = "SELECT * FROM analyses WHERE score BETWEEN ? AND ?"
    params = [min_score, max_score]

    if domain:
        query  += " AND email_domain LIKE ?"
        params.append(f"%{domain}%")

    query += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    conn.close()

    result = []
    for row in rows:
        r = dict(row)
        try:
            r["details"] = json.loads(r.get("details") or "[]")
        except Exception:
            r["details"] = []
        result.append(r)

    return jsonify(result)


@app.route("/history/<int:analysis_id>", methods=["DELETE"])
def delete_history(analysis_id: int):
    """Supprime une analyse par son ID."""
    conn = get_db()
    conn.execute("DELETE FROM analyses WHERE id = ?", (analysis_id,))
    conn.commit()
    conn.close()
    return jsonify({"deleted": analysis_id})


@app.route("/stats")
def stats():
    """
    Statistiques globales : total, score moyen, distribution par niveau de risque.
    """
    conn = get_db()

    total = conn.execute("SELECT COUNT(*) FROM analyses").fetchone()[0]
    avg   = conn.execute("SELECT AVG(score) FROM analyses").fetchone()[0]

    dist_rows = conn.execute(
        "SELECT risk_level, COUNT(*) as cnt FROM analyses GROUP BY risk_level"
    ).fetchall()

    today_count = conn.execute(
        "SELECT COUNT(*) FROM analyses WHERE DATE(timestamp) = DATE('now')"
    ).fetchone()[0]

    conn.close()

    distribution = {row["risk_level"]: row["cnt"] for row in dist_rows}

    return jsonify({
        "total":        total,
        "avg_score":    round(avg or 0, 1),
        "today":        today_count,
        "distribution": distribution,
    })


@app.route("/batch-analyze", methods=["POST"])
def batch_analyze():
    """
    Analyse un lot d'URLs.
    Accepte :
      - JSON body  : { "urls": ["url1", "url2", ...] }
      - Fichier TXT : upload multipart avec une URL par ligne
    Limite : 50 URLs par requête.
    """
    urls = []

    if request.files and "file" in request.files:
        f = request.files["file"]
        content = f.read().decode("utf-8", errors="ignore")
        urls = [line.strip() for line in content.splitlines() if line.strip()]
    else:
        data = request.get_json(force=True, silent=True) or {}
        urls = data.get("urls", [])

    if not urls:
        return jsonify({"error": "Aucune URL fournie (JSON ou fichier TXT)."}), 400

    urls = [u for u in urls[:50] if u]  # max 50

    results = []
    for url in urls:
        try:
            r = calculate_phishing_score(url)
            save_analysis(r)
            results.append(r)
        except Exception as exc:
            results.append({"url": url, "error": str(exc), "score": 0})

    return jsonify({"total": len(results), "results": results})


@app.route("/export/<fmt>")
def export_history(fmt: str):
    """
    Exporte l'historique.
    Formats supportés : csv, json
    GET /export/csv   → télécharge phishing_history.csv
    GET /export/json  → télécharge phishing_history.json
    """
    if fmt not in ("csv", "json"):
        return jsonify({"error": "Format non supporté. Utilisez 'csv' ou 'json'."}), 400

    conn = get_db()
    rows = conn.execute(
        "SELECT id, url, score, risk_level, timestamp, email_domain, confidence "
        "FROM analyses ORDER BY timestamp DESC"
    ).fetchall()
    conn.close()

    if fmt == "json":
        data = [dict(row) for row in rows]
        return Response(
            json.dumps(data, ensure_ascii=False, indent=2),
            mimetype="application/json",
            headers={"Content-Disposition": "attachment; filename=phishing_history.json"},
        )

    # CSV
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "URL", "Score", "Risque", "Date", "Domaine", "Confiance %"])
    for row in rows:
        writer.writerow([
            row["id"], row["url"], row["score"], row["risk_level"],
            row["timestamp"], row["email_domain"], row["confidence"],
        ])
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=phishing_history.csv"},
    )


@app.route("/health")
def health():
    """Healthcheck pour déploiement."""
    return jsonify({"status": "ok", "version": "2.0", "timestamp": datetime.now().isoformat()})


# ---------------------------------------------------------------------------
# Démarrage
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5000, host="0.0.0.0")
