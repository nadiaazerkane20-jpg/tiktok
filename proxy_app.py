from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import time
import os

app = Flask(__name__)
CORS(app)  # Autorise tous les domaines (ton GitHub Pages inclus)

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

    # Construire les hashtags selon la niche
    niche_hashtags = {
        "business": ["business", "argent", "money", "entrepreneur"],
        "fitness": ["fitness", "workout", "musculation", "sport"],
        "beauty": ["beauty", "makeup", "skincare", "beaute"],
        "food": ["food", "recette", "cuisine", "foodtiktok"],
        "tech": ["tech", "ia", "artificialintelligence", "iphone"],
        "mindset": ["mindset", "motivation", "developpementpersonnel", "succes"],
        "travel": ["travel", "voyage", "wanderlust", "trip"],
        "all": ["viral", "trending", "carousel", "foryou"]
    }
    hashtags = niche_hashtags.get(niche, niche_hashtags["all"])

    try:
        # Lancer le scraper Apify
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
        run_data = run_resp.json()
        run_id = run_data.get("data", {}).get("id")

        if not run_id:
            return jsonify({"error": "Impossible de lancer le scraper Apify", "detail": run_data}), 500

        # Attendre que le run se termine (max 60s)
        for _ in range(20):
            time.sleep(3)
            status_resp = requests.get(
                f"{APIFY_BASE}/acts/{ACTOR_ID}/runs/{run_id}",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=10
            )
            status = status_resp.json().get("data", {}).get("status")
            if status == "SUCCEEDED":
                break
            elif status in ["FAILED", "ABORTED", "TIMED-OUT"]:
                return jsonify({"error": f"Scraper terminé avec statut: {status}"}), 500

        # Récupérer les résultats
        items_resp = requests.get(
            f"{APIFY_BASE}/acts/{ACTOR_ID}/runs/{run_id}/dataset/items",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=15
        )
        items = items_resp.json()

        # Filtrer uniquement les carrousels (imagePost ou photoMode)
        carousels = [item for item in items if item.get("imagePost") or item.get("photoMode")]

        # Formatter les résultats
        results = []
        for item in carousels[:12]:
            images = item.get("imagePost") or item.get("photoMode") or []
            results.append({
                "title": (item.get("text") or "")[:100],
                "niche": detect_niche(item.get("text", "")),
                "nicheLabel": detect_niche_label(item.get("text", "")),
                "product": detect_product(item.get("text", "")),
                "country": item.get("authorMeta", {}).get("region", country if country != "all" else "US"),
                "slides": len(images) if images else 5,
                "views": item.get("playCount", 0),
                "likes": item.get("diggCount", 0),
                "url": item.get("webVideoUrl", ""),
                "emoji": get_emoji(detect_niche(item.get("text", "")))
            })

        return jsonify({"trends": results})

    except requests.exceptions.Timeout:
        return jsonify({"error": "Timeout — Apify met trop de temps à répondre"}), 504
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def detect_niche(text):
    t = text.lower()
    if any(w in t for w in ["argent", "business", "money", "gagner", "revenu", "entrepreneur", "dropshipping"]):
        return "business"
    if any(w in t for w in ["fitness", "sport", "muscl", "mincir", "workout", "poids"]):
        return "fitness"
    if any(w in t for w in ["beauté", "beauty", "makeup", "skin", "soin", "cosmétique"]):
        return "beauty"
    if any(w in t for w in ["recette", "food", "cuisine", "manger", "repas", "cook"]):
        return "food"
    if any(w in t for w in ["tech", "ia", "ai", "iphone", "android", "app", "logiciel"]):
        return "tech"
    if any(w in t for w in ["mindset", "mental", "motivation", "succes", "habitude", "routine"]):
        return "mindset"
    if any(w in t for w in ["voyage", "travel", "pays", "trip", "destination", "hotel"]):
        return "travel"
    return "business"

def detect_niche_label(text):
    labels = {
        "business": "Business / Argent",
        "fitness": "Fitness / Santé",
        "beauty": "Beauté / Mode",
        "food": "Food / Recettes",
        "tech": "Tech / IA",
        "mindset": "Mindset / Dev perso",
        "travel": "Voyage"
    }
    return labels.get(detect_niche(text), "Business")

def detect_product(text):
    t = text.lower()
    if "formation" in t: return "Formation en ligne"
    if "ebook" in t or "guide" in t or "pdf" in t: return "Ebook / Guide PDF"
    if "coaching" in t: return "Coaching / Accompagnement"
    if "programme" in t: return "Programme digital"
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
