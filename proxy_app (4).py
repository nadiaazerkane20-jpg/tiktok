from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import time
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

APIFY_BASE = "https://api.apify.com/v2"
ACTOR_ID = "clockworks~tiktok-scraper"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"

@app.route("/health")
def health():
    return jsonify({"status": "ok"})

# ─── PROXY CLAUDE ─────────────────────────────────────────────────────────────
@app.route("/claude", methods=["POST"])
def claude_proxy():
    body = request.json or {}
    api_key = body.pop("anthropicKey", "")

    if not api_key:
        return jsonify({"error": "Clé Anthropic manquante"}), 400

    try:
        resp = requests.post(
            ANTHROPIC_URL,
            headers={
                "x-api-key": api_key,
                "anthropic-version": ANTHROPIC_VERSION,
                "Content-Type": "application/json"
            },
            json=body,
            timeout=60
        )
        return jsonify(resp.json()), resp.status_code
    except Exception as e:
        logger.error(f"Claude proxy error: {e}")
        return jsonify({"error": str(e)}), 500

# ─── PROXY TRENDING ───────────────────────────────────────────────────────────
@app.route("/trending", methods=["POST"])
def trending():
    body = request.json or {}
    api_key = body.get("apiKey", "")
    country = body.get("country", "all")
    niche = body.get("niche", "all")

    if not api_key:
        return jsonify({"error": "Clé Apify manquante"}), 400

    niche_hashtags = {
        "business": ["business", "money", "entrepreneur", "sidehustle"],
        "fitness": ["fitness", "workout", "gym", "sport"],
        "beauty": ["beauty", "makeup", "skincare", "glow"],
        "food": ["food", "recipe", "cooking", "foodtiktok"],
        "tech": ["tech", "ai", "iphone", "gadgets"],
        "mindset": ["mindset", "motivation", "success", "selfimprovement"],
        "travel": ["travel", "wanderlust", "trip", "explore"],
        "all": ["viral", "foryou", "trending", "fyp"]
    }
    hashtags = niche_hashtags.get(niche, niche_hashtags["all"])

    try:
        run_resp = requests.post(
            f"{APIFY_BASE}/acts/{ACTOR_ID}/runs",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"hashtags": hashtags, "resultsPerPage": 15, "maxItems": 15, "proxyConfiguration": {"useApifyProxy": True}},
            timeout=30
        )
        run_raw = run_resp.json()
        run_id = run_raw.get("data", {}).get("id") or run_raw.get("id") if isinstance(run_raw, dict) else None

        if not run_id:
            return jsonify({"error": "Impossible de lancer le scraper", "detail": run_raw}), 500

        for attempt in range(25):
            time.sleep(3)
            status_resp = requests.get(
                f"{APIFY_BASE}/acts/{ACTOR_ID}/runs/{run_id}",
                headers={"Authorization": f"Bearer {api_key}"}, timeout=15
            )
            status_raw = status_resp.json()
            status = status_raw.get("data", {}).get("status") or status_raw.get("status") if isinstance(status_raw, dict) else None
            if status == "SUCCEEDED": break
            elif status in ["FAILED", "ABORTED", "TIMED-OUT"]:
                return jsonify({"error": f"Scraper échoué: {status}"}), 500

        items_resp = requests.get(
            f"{APIFY_BASE}/acts/{ACTOR_ID}/runs/{run_id}/dataset/items",
            headers={"Authorization": f"Bearer {api_key}"}, timeout=20
        )
        items_raw = items_resp.json()
        if not isinstance(items_raw, list):
            items_raw = items_raw.get("items", []) if isinstance(items_raw, dict) else []

        carousels = [item for item in items_raw if isinstance(item, dict) and (item.get("imagePost") or item.get("photoMode") or item.get("isSlideshow"))]
        if not carousels:
            carousels = [item for item in items_raw if isinstance(item, dict)]

        results = []
        for item in carousels[:12]:
            if not isinstance(item, dict): continue
            images = item.get("imagePost") or item.get("photoMode") or []
            text = item.get("text") or item.get("desc") or ""
            author = item.get("authorMeta") or item.get("author") or {}
            if isinstance(author, str): author = {}
            results.append({
                "title": str(text)[:100],
                "niche": detect_niche(str(text)),
                "nicheLabel": detect_niche_label(str(text)),
                "product": detect_product(str(text)),
                "country": author.get("region", "") or (country if country != "all" else "US"),
                "slides": len(images) if isinstance(images, list) else 5,
                "views": item.get("playCount") or 0,
                "likes": item.get("diggCount") or 0,
                "url": item.get("webVideoUrl") or item.get("url") or "",
                "emoji": get_emoji(detect_niche(str(text)))
            })
        return jsonify({"trends": results})

    except requests.exceptions.Timeout:
        return jsonify({"error": "Timeout"}), 504
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def detect_niche(text):
    t = text.lower()
    if any(w in t for w in ["argent", "business", "money", "gagner", "entrepreneur", "dropshipping"]): return "business"
    if any(w in t for w in ["fitness", "sport", "muscl", "workout", "gym"]): return "fitness"
    if any(w in t for w in ["beauty", "makeup", "skin", "soin", "glow"]): return "beauty"
    if any(w in t for w in ["recette", "food", "cuisine", "cook", "recipe"]): return "food"
    if any(w in t for w in ["tech", "ai", "iphone", "android", "app"]): return "tech"
    if any(w in t for w in ["mindset", "motivation", "succes", "habitude", "success"]): return "mindset"
    if any(w in t for w in ["voyage", "travel", "trip", "destination"]): return "travel"
    return "business"

def detect_niche_label(text):
    labels = {"business": "Business / Argent", "fitness": "Fitness / Santé", "beauty": "Beauté / Mode", "food": "Food / Recettes", "tech": "Tech / IA", "mindset": "Mindset / Dev perso", "travel": "Voyage"}
    return labels.get(detect_niche(text), "Business")

def detect_product(text):
    t = text.lower()
    if "formation" in t: return "Formation en ligne"
    if "ebook" in t or "guide" in t: return "Ebook / Guide PDF"
    if "coaching" in t: return "Coaching"
    if "programme" in t: return "Programme digital"
    if "shop" in t or "boutique" in t: return "E-commerce"
    return "Produit digital (lien en bio)"

def get_emoji(niche):
    return {"business": "💰", "fitness": "💪", "beauty": "💄", "food": "🍕", "tech": "📱", "mindset": "🧠", "travel": "✈️"}.get(niche, "📸")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
