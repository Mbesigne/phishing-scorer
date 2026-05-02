"""
Phishing Risk Scorer v2 — Moteur d'analyse avancé
Détecte 10 vecteurs d'attaque dans les URLs, textes email et headers SMTP.
"""

import re
import ssl
import socket
import hashlib
import json
import os
import base64
from urllib.parse import urlparse
from difflib import SequenceMatcher
from datetime import datetime

# Imports optionnels (dégradation gracieuse si absents)
try:
    import requests
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

try:
    import whois as whois_lib
    WHOIS_AVAILABLE = True
except ImportError:
    WHOIS_AVAILABLE = False

try:
    from Levenshtein import distance as levenshtein_distance
except ImportError:
    def levenshtein_distance(s1, s2):
        if len(s1) < len(s2):
            return levenshtein_distance(s2, s1)
        if len(s2) == 0:
            return len(s1)
        prev = list(range(len(s2) + 1))
        for i, c1 in enumerate(s1):
            curr = [i + 1]
            for j, c2 in enumerate(s2):
                curr.append(min(prev[j + 1] + 1, curr[j] + 1, prev[j] + (c1 != c2)))
            prev = curr
        return prev[len(s2)]


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

URL_SHORTENERS = {
    "bit.ly", "tinyurl.com", "goo.gl", "ow.ly", "short.link", "rebrand.ly",
    "buff.ly", "adf.ly", "t.co", "is.gd", "cli.gs", "tiny.cc", "rb.gy",
    "cutt.ly", "shorturl.at", "s.id", "lnkd.in", "tr.im", "snipurl.com",
    "su.pr", "twurl.nl", "ff.im", "budurl.com", "ping.fm", "post.ly",
}

SUSPICIOUS_TLDS = {
    ".tk", ".ml", ".ga", ".cf", ".top", ".xyz", ".work", ".online",
    ".site", ".download", ".gq", ".pw", ".click", ".link", ".rest", ".icu",
}

URGENCY_WORDS = [
    "urgent", "urgente", "urgentement", "immédiat", "immédiate",
    "vérifier", "verifier", "vérification", "confirmer", "confirmation",
    "action requise", "compte suspendu", "compte bloqué", "expiration",
    "cliquez ici", "cliquez maintenant", "valider", "validation",
    "urgence", "problème détecté", "mise à jour requise", "alerté",
    "anormal", "activité suspecte", "dernière chance",
    "immediately", "verify", "confirm", "suspended", "unusual activity",
    "click here", "act now", "expires", "validate", "limited time",
    "update your", "your account has been",
]

# Patterns regex pour détecter les variantes obfusquées (leet-speak, mixte…)
# Format : (regex, label lisible)
_URGENCY_OBFUSCATED = [
    (r"c[1l!][i1!]ck",                  "click (obfusqué)"),
    (r"v[3e]r[i1!]f[y1!]",             "verify (obfusqué)"),
    (r"c[o0]nf[i1!]rm",                "confirm (obfusqué)"),
    (r"(?:u[Rr][Gg]|U[rR][gG])[eE][nN][tT]", "urgent (mixte)"),
    (r"susp[e3]nd",                     "suspended (obfusqué)"),
    (r"acc[o0]unt",                     "account (obfusqué)"),
    (r"l[o0]g[i1!]n",                  "login (obfusqué)"),
    (r"p[a@]ssw[o0]rd",                "password (obfusqué)"),
    (r"upd[a@][t7]e",                   "update (obfusqué)"),
    (r"[s$]ecur[i1!]t[y1!]",           "security (obfusqué)"),
]

# Domaines de référence pour la détection de typosquattage
KNOWN_BRAND_DOMAINS = [
    "amazon.com", "gmail.com", "paypal.com", "apple.com", "microsoft.com",
    "google.com", "facebook.com", "bank.fr", "orange.fr", "apple.fr",
    "bnpparibas.fr", "laposte.fr", "netflix.com", "instagram.com",
    "twitter.com", "linkedin.com", "dropbox.com", "ebay.com",
]

_PRIVATE_IP_RE = re.compile(
    r"(^127\.)|(^10\.)|(^172\.1[6-9]\.)|(^172\.2[0-9]\.)|(^172\.3[01]\.)"
    r"|(^192\.168\.)|(^::1$)|(^0\.0\.0\.0)"
)


# ---------------------------------------------------------------------------
# 1. extract_domain
# ---------------------------------------------------------------------------

def extract_domain(url: str) -> str:
    """Parse l'URL, enlève www., retourne le domaine en minuscules."""
    url = (url or "").strip()
    if not url.startswith(("http://", "https://", "ftp://")):
        url = "http://" + url
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        domain = re.sub(r"^www\.", "", domain)
        domain = re.sub(r":\d+$", "", domain)
        return domain
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# 2. detect_shortened_url  (+25 pts)
# ---------------------------------------------------------------------------

def detect_shortened_url(url: str) -> bool:
    """Détecte les services de raccourcissement d'URL. Retourne True si trouvé."""
    domain = extract_domain(url)
    return domain in URL_SHORTENERS


# ---------------------------------------------------------------------------
# 3. detect_urgency_words  (+20 pts)
# ---------------------------------------------------------------------------

def detect_urgency_words(text: str) -> list:
    """
    Retourne la liste des mots/patterns d'urgence trouvés dans le texte.
    Détecte aussi les variantes obfusquées (leet-speak, majuscules alternées).
    """
    if not text:
        return []
    text_lower = text.lower()

    # Mots exacts
    found = [w for w in URGENCY_WORDS if w in text_lower]

    # Variantes obfusquées via regex
    for pattern, label in _URGENCY_OBFUSCATED:
        if re.search(pattern, text, re.IGNORECASE):
            found.append(label)

    return list(dict.fromkeys(found))  # dédupliqué, ordre préservé


# ---------------------------------------------------------------------------
# 4. check_domain_similarity  (+30 pts)
# ---------------------------------------------------------------------------

def check_domain_similarity(domain: str) -> dict:
    """
    Compare le domaine aux marques connues via SequenceMatcher.
    Détecte le typosquattage si 70% < similitude < 100%.
    """
    if not domain:
        return {"is_similar": False, "similarity_score": 0, "similar_to": ""}

    for brand in KNOWN_BRAND_DOMAINS:
        ratio = SequenceMatcher(None, domain.lower(), brand.lower()).ratio()
        if 0.70 < ratio < 1.0:
            return {
                "is_similar": True,
                "similarity_score": int(ratio * 100),
                "similar_to": brand,
            }
    return {"is_similar": False, "similarity_score": 0, "similar_to": ""}


# ---------------------------------------------------------------------------
# 5. is_ip_address  (+35 pts)
# ---------------------------------------------------------------------------

def is_ip_address(domain: str) -> bool:
    """Retourne True si le domaine est une adresse IPv4."""
    if not domain:
        return False
    return bool(re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", domain))


# ---------------------------------------------------------------------------
# 6. check_suspicious_tlds  (+15 pts)
# ---------------------------------------------------------------------------

def check_suspicious_tlds(domain: str) -> dict:
    """Détecte les extensions de domaine gratuites/peu fiables."""
    if not domain:
        return {"detected": False, "tld": ""}
    for tld in SUSPICIOUS_TLDS:
        if domain.endswith(tld):
            return {"detected": True, "tld": tld}
    return {"detected": False, "tld": ""}


# ---------------------------------------------------------------------------
# 7. check_ssl_certificate  (HTTP:+30 / cert invalide:+40 / timeout:+25)
# ---------------------------------------------------------------------------

def check_ssl_certificate(domain: str, url: str = "") -> dict:
    """
    Vérifie SSL/TLS du domaine.
    Retourne: {has_ssl, valid, issuer, penalty, detail}
    """
    if not domain:
        return {"has_ssl": False, "valid": False, "issuer": "", "penalty": 0, "detail": ""}

    url_lower = (url or "").strip().lower()
    if not url_lower.startswith(("http://", "https://")):
        url_lower = "http://" + url_lower
    uses_https = url_lower.startswith("https://")

    if not uses_https:
        return {
            "has_ssl": False, "valid": False, "issuer": "",
            "penalty": 30,
            "detail": "Connexion HTTP non sécurisée — aucun chiffrement SSL/TLS.",
        }

    # IP privée → pas de certificat vérifiable
    if is_ip_address(domain) or _PRIVATE_IP_RE.match(domain):
        return {
            "has_ssl": False, "valid": False, "issuer": "",
            "penalty": 30,
            "detail": f"Adresse IP ({domain}) — pas de certificat SSL vérifiable.",
        }

    ctx = ssl.create_default_context()
    try:
        with socket.create_connection((domain, 443), timeout=4) as sock:
            with ctx.wrap_socket(sock, server_hostname=domain) as ssock:
                cert = ssock.getpeercert()
                issuer_parts = dict(x[0] for x in cert.get("issuer", []))
                issuer = issuer_parts.get("organizationName", "Inconnu")
                return {
                    "has_ssl": True, "valid": True,
                    "issuer": issuer, "penalty": 0,
                    "detail": f"Certificat SSL valide (émetteur : {issuer}).",
                }

    except ssl.SSLCertVerificationError as e:
        return {
            "has_ssl": True, "valid": False, "issuer": "",
            "penalty": 40,
            "detail": f"Certificat SSL invalide/expiré : {str(e)[:80]}",
        }
    except ssl.SSLError as e:
        return {
            "has_ssl": True, "valid": False, "issuer": "",
            "penalty": 40,
            "detail": f"Erreur SSL : {str(e)[:70]}",
        }
    except socket.timeout:
        return {
            "has_ssl": True, "valid": None, "issuer": "",
            "penalty": 25,
            "detail": "Délai SSL dépassé — serveur suspect ou inaccessible.",
        }
    except (socket.gaierror, ConnectionRefusedError, OSError):
        return {
            "has_ssl": True, "valid": None, "issuer": "",
            "penalty": 0,
            "detail": "Vérification SSL impossible (domaine non joignable).",
        }


# ---------------------------------------------------------------------------
# 8. analyze_email_headers  (cumulatif, voir détails)
# ---------------------------------------------------------------------------

def analyze_email_headers(headers_text: str) -> dict:
    """
    Analyse complète des headers SMTP.
    Détecte SPF, DKIM, DMARC, From/Reply-To, Return-Path, chaîne Received,
    IPs privées, X-Originating-IP et Message-ID.
    Retourne: {issues, score_add, summary}
    """
    if not (headers_text or "").strip():
        return {"issues": [], "score_add": 0, "summary": "Aucun header fourni."}

    issues = []
    score_add = 0
    h = headers_text.lower()

    # --- SPF ---
    if "spf=pass" in h:
        issues.append("✅ SPF : Pass — expéditeur autorisé")
    elif "spf=fail" in h or "spf=softfail" in h:
        issues.append("⚠️ SPF : Fail — expéditeur non autorisé depuis ce domaine (+30 pts)")
        score_add += 30
    elif re.search(r"received-spf:", h):
        pass  # Présent mais neutre
    else:
        issues.append("⚠️ SPF : Absent — impossible de vérifier l'expéditeur (+15 pts)")
        score_add += 15

    # --- DKIM ---
    if "dkim=pass" in h:
        issues.append("✅ DKIM : Pass — signature cryptographique valide")
    elif "dkim=fail" in h:
        issues.append("⚠️ DKIM : Fail — signature invalide ou falsifiée (+25 pts)")
        score_add += 25
    elif "dkim=none" in h:
        issues.append("⚠️ DKIM : Absent — email non signé")

    # --- DMARC ---
    if "dmarc=pass" in h:
        issues.append("✅ DMARC : Pass — politique DMARC respectée")
    elif "dmarc=fail" in h or "dmarc=quarantine" in h:
        issues.append("⚠️ DMARC : Fail/Quarantine — politique non respectée (+35 pts)")
        score_add += 35

    # --- From vs Reply-To ---
    _email_domain_re = re.compile(
        r"[a-zA-Z0-9._%+\-]+@([a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})"
    )
    _email_addr_re = re.compile(
        r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"
    )

    def _extract_addr(header_name):
        line = re.search(rf"^{header_name}:(.+)$", headers_text, re.IGNORECASE | re.MULTILINE)
        if not line:
            return ""
        addrs = _email_addr_re.findall(line.group(1))
        return addrs[0].lower() if addrs else ""

    from_addr   = _extract_addr("from")
    reply_addr  = _extract_addr("reply-to")
    return_addr = _extract_addr("return-path")

    if from_addr and reply_addr and from_addr != reply_addr:
        issues.append(
            f"⚠️ From/Reply-To divergents : {from_addr} → {reply_addr} (+25 pts)"
        )
        score_add += 25

    # --- Return-Path vs From ---
    if from_addr and return_addr:
        from_domain   = from_addr.split("@")[-1]
        return_domain = return_addr.split("@")[-1]
        if from_domain != return_domain:
            issues.append(
                f"⚠️ Return-Path/From divergents : {return_domain} ≠ {from_domain} (+20 pts)"
            )
            score_add += 20

    # --- Chaîne Received ---
    received_count = len(re.findall(r"^received:", headers_text, re.IGNORECASE | re.MULTILINE))
    if received_count > 0 and (received_count < 2 or received_count > 15):
        issues.append(
            f"⚠️ Chaîne Received suspecte : {received_count} header(s) "
            f"({'trop peu' if received_count < 2 else 'trop nombreux'}) (+15 pts)"
        )
        score_add += 15

    # --- IPs privées dans Received ---
    priv_ip_in_received = re.search(
        r"received:.*?(192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+|172\.(?:1[6-9]|2\d|3[01])\.\d+\.\d+)",
        headers_text, re.IGNORECASE | re.DOTALL
    )
    if priv_ip_in_received:
        issues.append(
            f"⚠️ IP privée dans Received ({priv_ip_in_received.group(1)}) — "
            f"routage interne suspect (+30 pts)"
        )
        score_add += 30

    # --- X-Originating-IP ---
    x_orig = re.search(
        r"^x-originating-ip:\s*\[?(\d+\.\d+\.\d+\.\d+)",
        headers_text, re.IGNORECASE | re.MULTILINE
    )
    if x_orig:
        ip = x_orig.group(1)
        if _PRIVATE_IP_RE.match(ip):
            issues.append(f"⚠️ X-Originating-IP privée ({ip}) (+20 pts)")
            score_add += 20
        else:
            issues.append(f"ℹ️ X-Originating-IP publique : {ip}")

    # --- Message-ID domain vs From domain ---
    msg_id = re.search(
        r"^message-id:\s*<[^@]+@([^>]+)>", headers_text, re.IGNORECASE | re.MULTILINE
    )
    if msg_id and from_addr:
        from_domain   = from_addr.split("@")[-1]
        msg_id_domain = msg_id.group(1).strip().lower()
        if from_domain != msg_id_domain:
            issues.append(
                f"⚠️ Message-ID domain ({msg_id_domain}) ≠ From domain ({from_domain}) (+15 pts)"
            )
            score_add += 15

    auth_issues = [i for i in issues if i.startswith("⚠️")]
    summary = (
        f"{len(auth_issues)} problème(s) d'authentification détecté(s)"
        if auth_issues else "Headers d'authentification normaux"
    )

    return {"issues": issues, "score_add": score_add, "summary": summary}


# ---------------------------------------------------------------------------
# 9. check_url_reputation  (optionnel VirusTotal, +50 pts)
# ---------------------------------------------------------------------------

def check_url_reputation(url: str, api_key: str = "") -> dict:
    """
    Vérifie la réputation de l'URL via l'API VirusTotal v3.
    La clé peut être passée explicitement ou lue depuis VIRUSTOTAL_API_KEY.
    Sans clé, retourne un résultat neutre (dégradation gracieuse).
    """
    key = (api_key or os.environ.get("VIRUSTOTAL_API_KEY", "")).strip()

    if not key or not REQUESTS_AVAILABLE:
        return {
            "detected": False, "malicious_count": 0,
            "score_add": 0, "note": "Clé API VirusTotal non configurée.",
        }

    try:
        url_id = base64.urlsafe_b64encode(url.encode()).decode().rstrip("=")
        resp = requests.get(
            f"https://www.virustotal.com/api/v3/urls/{url_id}",
            headers={"x-apikey": key},
            timeout=8,
        )

        if resp.status_code == 200:
            stats = (
                resp.json()
                .get("data", {})
                .get("attributes", {})
                .get("last_analysis_stats", {})
            )
            malicious = stats.get("malicious", 0) + stats.get("suspicious", 0)
            total = sum(stats.values()) or 1

            if malicious > 0:
                return {
                    "detected": True,
                    "malicious_count": malicious,
                    "total_vendors": total,
                    "score_add": 50,
                    "note": f"Détecté par {malicious}/{total} moteurs VirusTotal.",
                }
            return {
                "detected": False, "malicious_count": 0,
                "score_add": 0, "note": "URL non détectée par VirusTotal.",
            }

        if resp.status_code == 404:
            return {
                "detected": False, "malicious_count": 0,
                "score_add": 0, "note": "URL inconnue de VirusTotal (nouvelle URL).",
            }

        return {
            "detected": False, "malicious_count": 0,
            "score_add": 0, "note": f"VirusTotal API : erreur {resp.status_code}",
        }

    except Exception as e:
        return {
            "detected": False, "malicious_count": 0,
            "score_add": 0, "note": f"Vérification VirusTotal impossible ({type(e).__name__}).",
        }


# ---------------------------------------------------------------------------
# 9b. check_google_safe_browsing  (MALWARE/SOCIAL_ENGINEERING → +40 pts)
# ---------------------------------------------------------------------------

def check_google_safe_browsing(url: str, api_key: str = "") -> dict:
    """
    Vérifie si l'URL figure dans les listes Google Safe Browsing v4.
    La clé peut être passée explicitement ou lue depuis GOOGLE_SAFE_BROWSING_KEY.
    Sans clé, retourne un résultat neutre (dégradation gracieuse).
    Free tier : illimité avec clé API (Google Cloud Console).
    """
    key = (api_key or os.environ.get("GOOGLE_SAFE_BROWSING_KEY", "")).strip()

    if not key or not REQUESTS_AVAILABLE:
        return {"is_safe": True, "threat_types": [], "score_add": 0, "note": "Clé GSB non configurée."}

    payload = {
        "client": {"clientId": "phishing-risk-scorer", "clientVersion": "2.0"},
        "threatInfo": {
            "threatTypes": [
                "MALWARE", "SOCIAL_ENGINEERING",
                "UNWANTED_SOFTWARE", "POTENTIALLY_HARMFUL_APPLICATION",
            ],
            "platformTypes":    ["ANY_PLATFORM"],
            "threatEntryTypes": ["URL"],
            "threatEntries":    [{"url": url}],
        },
    }

    try:
        resp = requests.post(
            f"https://safebrowsing.googleapis.com/v4/threatMatches:find?key={key}",
            json=payload,
            timeout=5,
        )

        if resp.status_code == 200:
            matches = resp.json().get("matches", [])
            if matches:
                threat_types = list({m["threatType"] for m in matches})
                return {
                    "is_safe": False,
                    "threat_types": threat_types,
                    "score_add": 40,
                    "note": f"Google Safe Browsing : {', '.join(threat_types)}",
                }
            return {"is_safe": True, "threat_types": [], "score_add": 0, "note": "Propre (Google Safe Browsing)"}

        return {"is_safe": True, "threat_types": [], "score_add": 0, "note": f"GSB API erreur {resp.status_code}"}

    except Exception as e:
        return {
            "is_safe": True, "threat_types": [], "score_add": 0,
            "note": f"GSB vérification impossible ({type(e).__name__})",
        }


# ---------------------------------------------------------------------------
# 9c. check_domain_age  (< 30j → +25 pts / < 1 an → +15 pts)
# ---------------------------------------------------------------------------

def check_domain_age(domain: str) -> dict:
    """
    Vérifie l'âge du domaine via WHOIS.
    Les domaines très récents (< 30 jours) sont fréquemment utilisés pour le phishing.
    Nécessite le package python-whois. Sans le package, retourne un résultat neutre.
    """
    if not WHOIS_AVAILABLE or not domain or is_ip_address(domain):
        return {"age_days": None, "is_new": False, "score_add": 0, "detail": ""}

    try:
        info = whois_lib.whois(domain)
        creation = info.creation_date

        if creation is None:
            return {"age_days": None, "is_new": False, "score_add": 0, "detail": ""}

        if isinstance(creation, list):
            creation = creation[0]

        age_days = (datetime.now() - creation.replace(tzinfo=None)).days

        if age_days < 0:
            return {"age_days": None, "is_new": False, "score_add": 0, "detail": ""}

        if age_days < 30:
            return {
                "age_days":  age_days,
                "is_new":    True,
                "score_add": 25,
                "detail":    f"⚠️ Domaine très récent ({age_days} jour(s)) — souvent utilisé pour phishing (+25 pts)",
            }
        if age_days < 365:
            return {
                "age_days":  age_days,
                "is_new":    True,
                "score_add": 15,
                "detail":    f"⚠️ Domaine < 1 an ({age_days} jours) (+15 pts)",
            }
        return {
            "age_days":  age_days,
            "is_new":    False,
            "score_add": 0,
            "detail":    f"✅ Domaine établi ({age_days // 365} an(s))",
        }

    except Exception:
        return {"age_days": None, "is_new": False, "score_add": 0, "detail": ""}


# ---------------------------------------------------------------------------
# 10. analyze_page_content  (formulaire HTTP:+20 / iframe cachée:+25 / JS:+15)
# ---------------------------------------------------------------------------

def analyze_page_content(url: str) -> dict:
    """
    Tente de scraper la page et détecte les éléments suspects dans le HTML.
    Timeout de 5 secondes. Analyse limitée aux 100 premiers Ko.
    """
    if not REQUESTS_AVAILABLE:
        return {"issues": [], "score_add": 0}

    issues = []
    score_add = 0

    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0 Safari/537.36"
            )
        }
        response = requests.get(
            url, timeout=5, verify=False,
            headers=headers, stream=True,
            allow_redirects=True
        )

        # Ignore les réponses non-HTML
        ct = response.headers.get("Content-Type", "")
        if "text/html" not in ct:
            return {"issues": [], "score_add": 0}

        # Limite à 100 Ko pour éviter les gros téléchargements
        chunks = []
        for chunk in response.iter_content(chunk_size=8192):
            chunks.append(chunk)
            if sum(len(c) for c in chunks) > 102400:
                break
        html = b"".join(chunks).decode("utf-8", errors="ignore")
        html_lower = html.lower()

        # Formulaire login sur HTTP non chiffré
        has_password = bool(re.search(r'<input[^>]+type=["\']password["\']', html, re.IGNORECASE))
        if has_password and not url.lower().startswith("https://"):
            issues.append(
                "⚠️ Formulaire de connexion sur HTTP non chiffré (+20 pts)"
            )
            score_add += 20
        elif has_password:
            issues.append("ℹ️ Champ mot de passe présent sur la page (HTTPS OK)")

        # Iframes cachées
        if re.search(
            r'<iframe[^>]+style=["\'][^"\']*(?:display\s*:\s*none|visibility\s*:\s*hidden)',
            html, re.IGNORECASE
        ):
            issues.append("⚠️ Iframe cachée détectée — technique de dissimulation (+25 pts)")
            score_add += 25

        # Redirections JavaScript excessives
        js_redir = len(re.findall(
            r'(?:window\.location|location\.href|location\.replace)',
            html, re.IGNORECASE
        ))
        if js_redir > 3:
            issues.append(
                f"⚠️ {js_redir} redirections JavaScript — comportement suspect (+15 pts)"
            )
            score_add += 15

    except requests.exceptions.Timeout:
        issues.append("ℹ️ Page inaccessible (timeout 5 s)")
    except requests.exceptions.SSLError:
        issues.append("⚠️ Erreur SSL lors de l'accès à la page")
    except Exception:
        pass  # Silencieux pour les erreurs réseau/DNS

    return {"issues": issues, "score_add": score_add}


# ---------------------------------------------------------------------------
# 11. calculate_phishing_score  — orchestrateur principal
# ---------------------------------------------------------------------------

def calculate_phishing_score(
    url: str,
    email_text: str = "",
    headers_text: str = "",
    virustotal_key: str = "",
    google_sb_key: str = "",
) -> dict:
    """
    Calcule le score de risque phishing (0-100) en combinant 13 vecteurs.

    Args:
        url:             URL à analyser (requis)
        email_text:      Corps de l'email (optionnel)
        headers_text:    Headers SMTP bruts (optionnel)
        virustotal_key:  Clé API VirusTotal (optionnel, sinon lit VIRUSTOTAL_API_KEY)
        google_sb_key:   Clé Google Safe Browsing (optionnel, sinon lit GOOGLE_SAFE_BROWSING_KEY)

    Retourne un dict avec : score, risk_level, domain, details,
    recommendation, confidence, analysis_timestamp.
    """
    url = (url or "").strip()
    email_text = (email_text or "").strip()
    headers_text = (headers_text or "").strip()

    if not url:
        return {
            "score": 0, "risk_level": "🟢 FAIBLE",
            "domain": "", "details": [],
            "recommendation": "Aucune URL fournie.",
            "confidence": 0,
            "analysis_timestamp": datetime.now().isoformat(),
        }

    domain = extract_domain(url)
    raw_score = 0
    details = []
    checks_attempted = 0
    checks_succeeded = 0

    # ── 1. URL raccourcie ──────────────────────────────────────────────────
    checks_attempted += 1
    if detect_shortened_url(url):
        raw_score += 25
        details.append(f"⚠️ URL raccourcie ({extract_domain(url)}) — destination masquée (+25 pts)")
    checks_succeeded += 1

    # ── 2. Mots d'urgence ─────────────────────────────────────────────────
    checks_attempted += 1
    urgency = detect_urgency_words(email_text)
    if urgency:
        raw_score += 20
        details.append(f"⚠️ Langage d'urgence : {', '.join(urgency[:4])} (+20 pts)")
    checks_succeeded += 1

    # ── 3. Typosquattage ──────────────────────────────────────────────────
    checks_attempted += 1
    sim = check_domain_similarity(domain)
    if sim["is_similar"]:
        raw_score += 30
        details.append(
            f"⚠️ Typosquattage probable : « {domain} » ressemble à "
            f"« {sim['similar_to']} » ({sim['similarity_score']}% similaire) (+30 pts)"
        )
    checks_succeeded += 1

    # ── 4. Adresse IP ─────────────────────────────────────────────────────
    checks_attempted += 1
    if is_ip_address(domain):
        raw_score += 35
        details.append(f"⚠️ Adresse IP directe ({domain}) — très inhabituel (+35 pts)")
    checks_succeeded += 1

    # ── 5. Extension suspecte ─────────────────────────────────────────────
    checks_attempted += 1
    tld = check_suspicious_tlds(domain)
    if tld["detected"]:
        raw_score += 15
        details.append(f"⚠️ Extension suspecte ({tld['tld']}) — domaine gratuit/peu fiable (+15 pts)")
    checks_succeeded += 1

    # ── 6. Certificat SSL ─────────────────────────────────────────────────
    checks_attempted += 1
    try:
        ssl_r = check_ssl_certificate(domain, url)
        if ssl_r["penalty"] > 0:
            raw_score += ssl_r["penalty"]
            details.append(f"⚠️ SSL : {ssl_r['detail']} (+{ssl_r['penalty']} pts)")
        elif ssl_r["valid"] is True:
            details.append(f"🔒 SSL : {ssl_r['detail']}")
        elif ssl_r["detail"]:
            details.append(f"ℹ️ SSL : {ssl_r['detail']}")
        checks_succeeded += 1
    except Exception:
        checks_succeeded += 0.5

    # ── 7. Headers SMTP ───────────────────────────────────────────────────
    if headers_text:
        checks_attempted += 1
        h_r = analyze_email_headers(headers_text)
        raw_score += h_r["score_add"]
        details.extend(h_r["issues"])
        checks_succeeded += 1

    # ── 8. Réputation VirusTotal ──────────────────────────────────────────
    checks_attempted += 1
    try:
        rep = check_url_reputation(url, virustotal_key)
        if rep["detected"]:
            raw_score += rep["score_add"]
            details.append(f"🔴 {rep['note']} (+{rep['score_add']} pts)")
        elif "non configurée" not in rep.get("note", ""):
            details.append(f"✅ VirusTotal : {rep['note']}")
        checks_succeeded += 1
    except Exception:
        checks_succeeded += 0.5

    # ── 8b. Google Safe Browsing ──────────────────────────────────────────
    checks_attempted += 1
    try:
        gsb = check_google_safe_browsing(url, google_sb_key)
        if not gsb["is_safe"]:
            raw_score += gsb["score_add"]
            details.append(f"🔴 {gsb['note']} (+{gsb['score_add']} pts)")
        elif "non configurée" not in gsb.get("note", ""):
            details.append(f"✅ {gsb['note']}")
        checks_succeeded += 1
    except Exception:
        checks_succeeded += 0.5

    # ── 8c. Âge du domaine (WHOIS) ────────────────────────────────────────
    checks_attempted += 1
    try:
        age = check_domain_age(domain)
        if age["score_add"] > 0:
            raw_score += age["score_add"]
        if age["detail"]:
            details.append(age["detail"])
        checks_succeeded += 1
    except Exception:
        checks_succeeded += 0.5

    # ── 9. Contenu de la page ─────────────────────────────────────────────
    if REQUESTS_AVAILABLE:
        checks_attempted += 1
        try:
            page = analyze_page_content(url)
            raw_score += page["score_add"]
            details.extend(page["issues"])
            checks_succeeded += 1
        except Exception:
            checks_succeeded += 0.5

    # ── Score final ────────────────────────────────────────────────────────
    score = min(int(raw_score), 100)
    confidence = round((checks_succeeded / checks_attempted) * 100) if checks_attempted else 0

    if score >= 70:
        risk_level = "🔴 DANGER"
        recommendation = (
            "NE CLIQUEZ PAS sur ce lien et ne répondez pas à cet email. "
            "Il s'agit très probablement d'une tentative de phishing. "
            "Signalez-le sur signal-spam.fr ou à votre équipe de sécurité."
        )
    elif score >= 50:
        risk_level = "🟠 ÉLEVÉ"
        recommendation = (
            "Soyez très prudent. Vérifiez l'expéditeur réel, ne saisissez aucun "
            "identifiant et contactez l'organisme via son site officiel officiel."
        )
    elif score >= 30:
        risk_level = "🟡 MOYEN"
        recommendation = (
            "Quelques signaux suspects. Vérifiez l'expéditeur et l'URL complète "
            "avant toute action. Ne fournissez aucune donnée sensible."
        )
    else:
        risk_level = "🟢 FAIBLE"
        recommendation = (
            "Aucun indicateur majeur de phishing. "
            "Restez vigilant : aucun outil n'offre une garantie absolue."
        )

    return {
        "score": score,
        "risk_level": risk_level,
        "domain": domain,
        "details": details,
        "recommendation": recommendation,
        "confidence": confidence,
        "analysis_timestamp": datetime.now().isoformat(),
    }


# ---------------------------------------------------------------------------
# 12. hash_analysis  — identifiant unique d'analyse
# ---------------------------------------------------------------------------

def hash_analysis(url: str, score: int) -> str:
    """Crée un hash MD5 unique (url + score + timestamp) pour l'historique."""
    ts = datetime.now().isoformat(timespec="microseconds")
    return hashlib.md5(f"{url}:{score}:{ts}".encode()).hexdigest()


# ---------------------------------------------------------------------------
# Tests manuels
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    FAKE_HDR = (
        "From: \"Amazon\" <no-reply@amazon.com>\n"
        "Reply-To: hacker@evil-domain.ru\n"
        "Return-Path: <bounce@spam-relay.net>\n"
        "Received: from 192.168.1.100 by mail.evil.ru\n"
        "Received: from mail.evil.ru by smtp.example.com\n"
        "Received-SPF: fail (amazon.com does not designate 10.0.0.1 as permitted)\n"
        "Authentication-Results: mx.google.com; dkim=fail; dmarc=fail; spf=fail\n"
        "Message-ID: <abc@totally-different-domain.net>\n"
    )

    tests = [
        ("https://amaz0n.com/login", "Action urgente ! Vérifiez votre compte.", FAKE_HDR),
        ("https://bit.ly/xyz",       "Cliquez maintenant !",                    ""),
        ("https://amazon.com",        "",                                        ""),
        ("http://192.168.1.1/bank",  "Vérifier compte suspendu",               ""),
        ("https://paypal-secure.tk", "Confirmer urgent",                        ""),
    ]

    print("=" * 72)
    print("  PHISHING RISK SCORER v2 — Tests")
    print("=" * 72)
    for url, email_text, headers in tests:
        r = calculate_phishing_score(url, email_text, headers)
        print(f"\n🔍 {url}")
        print(f"   Score : {r['score']}/100  |  {r['risk_level']}  |  Confiance : {r['confidence']}%")
        for d in r["details"]:
            print(f"   {d}")
        print(f"   💡 {r['recommendation'][:80]}…")
    print("\n" + "=" * 72)
