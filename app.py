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

@app.route("/health")
def health():
    return jsonify({"status": "ok"})

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
        logger.info(f"Starting Apify run with hashtags: {hashtags}")
        run_resp = requests.post(
            f"{APIFY_BASE}/acts/{ACTOR_ID}/runs",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "hashtags": hashtags,
                "resultsPerPage": 15,
                "maxItems": 15,
                "proxyConfiguration": {"useApifyProxy": True}
            },
            timeout=30
        )

        run_raw = run_resp.json()
        logger.info(f"Apify run response: {run_raw}")

        if isinstance(run_raw, dict):
            run_id = run_raw.get("data", {}).get("id") or run_raw.get("id")
        else:
            return jsonify({"error": "Réponse Apify invalide", "detail": str(run_raw)}), 500

        if not run_id:
            return jsonify({"error": "Impossible de lancer le scraper", "detail": run_raw}), 500

        logger.info(f"Run ID: {run_id}")

        for attempt in range(25):
            time.sleep(3)
            status_resp = requests.get(
                f"{APIFY_BASE}/acts/{ACTOR_ID}/runs/{run_id}",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=15
            )
            status_raw = status_resp.json()

            if isinstance(status_raw, dict):
                status = status_raw.get("data", {}).get("status") or status_raw.get("status")
            else:
                continue

            logger.info(f"Status attempt {attempt}: {status}")
            if status == "SUCCEEDED":
                break
            elif status in ["FAILED", "ABORTED", "TIMED-OUT"]:
                return jsonify({"error": f"Scraper échoué: {status}"}), 500

        items_resp = requests.get(
            f"{APIFY_BASE}/acts/{ACTOR_ID}/runs/{run_id}/dataset/items",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=20
        )
        items_raw = items_resp.json()

        if not isinstance(items_raw, list):
            items_raw = items_raw.get("items", []) if isinstance(items_raw, dict) else []

        carousels = []
        for item in items_raw:
            if not isinstance(item, dict):
                continue
            if item.get("imagePost") or item.get("photoMode") or item.get("isSlideshow"):
                carousels.append(item)

        if not carousels:
            carousels = [item for item in items_raw if isinstance(item, dict)]

        results = []
        for item in carousels[:12]:
            if not isinstance(item, dict):
                continue
            images = item.get("imagePost") or item.get("photoMode") or []
            text = item.get("text") or item.get("desc") or ""
            author = item.get("authorMeta") or item.get("author") or {}
            if isinstance(author, str):
                author = {}

            results.append({
                "title": str(text)[:100],
                "niche": detect_niche(str(text)),
                "nicheLabel": detect_niche_label(str(text)),
                "product": detect_product(str(text)),
                "country": author.get("region", "") or (country if country != "all" else "US"),
                "slides": len(images) if isinstance(images, list) else 5,
                "views": item.get("playCount") or item.get("stats", {}).get("playCount", 0) if isinstance(item.get("stats"), dict) else 0,
                "likes": item.get("diggCount") or item.get("stats", {}).get("diggCount", 0) if isinstance(item.get("stats"), dict) else 0,
                "url": item.get("webVideoUrl") or item.get("url") or "",
                "emoji": get_emoji(detect_niche(str(text)))
            })

        return jsonify({"trends": results})

    except requests.exceptions.Timeout:
        return jsonify({"error": "Timeout — Apify met trop de temps"}), 504
    except Exception as e:
        logger.error(f"Error: {str(e)}", exc_info=True)
        return jsonify({"error": str(e)}), 500


def detect_niche(text):
    t = text.lower()
    if any(w in t for w in ["argent", "business", "money", "gagner", "revenu", "entrepreneur", "dropshipping", "income"]):
        return "business"
    if any(w in t for w in ["fitness", "sport", "muscl", "mincir", "workout", "poids", "gym"]):
        return "fitness"
    if any(w in t for w in ["beauty", "makeup", "skin", "soin", "glow", "beaute"]):
        return "beauty"
    if any(w in t for w in ["recette", "food", "cuisine", "manger", "cook", "recipe"]):
        return "food"
    if any(w in t for w in ["tech", "ai", "iphone", "android", "app", "gadget"]):
        return "tech"
    if any(w in t for w in ["mindset", "motivation", "succes", "habitude", "routine", "success"]):
        return "mindset"
    if any(w in t for w in ["voyage", "travel", "trip", "destination", "wanderlust"]):
        return "travel"
    return "business"

def detect_niche_label(text):
    labels = {
        "business": "Business / Argent", "fitness": "Fitness / Santé",
        "beauty": "Beauté / Mode", "food": "Food / Recettes",
        "tech": "Tech / IA", "mindset": "Mindset / Dev perso", "travel": "Voyage"
    }
    return labels.get(detect_niche(text), "Business")

def detect_product(text):
    t = text.lower()
    if "formation" in t: return "Formation en ligne"
    if "ebook" in t or "guide" in t or "pdf" in t: return "Ebook / Guide PDF"
    if "coaching" in t: return "Coaching / Accompagnement"
    if "programme" in t or "program" in t: return "Programme digital"
    if "shop" in t or "boutique" in t: return "E-commerce / Boutique"
    if "lien" in t or "bio" in t or "link" in t: return "Produit en bio (lien)"
    if "gratuit" in t or "free" in t: return "Lead magnet gratuit"
    return "Produit digital (lien en bio)"

def get_emoji(niche):
    emojis = {
        "business": "💰", "fitness": "💪", "beauty": "💄",
        "food": "🍕", "tech": "📱", "mindset": "🧠", "travel": "✈️"
    }
    return emojis.get(niche, "📸")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
