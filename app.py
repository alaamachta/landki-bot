import logging
from flask import Flask, request, jsonify
import openai
import requests
import os

# === Logging konfigurieren ===
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] : %(message)s"
)

app = Flask(__name__)

# === Azure OpenAI Konfiguration ===
openai.api_type = "azure"
openai.api_base = os.getenv("AZURE_OPENAI_ENDPOINT")  # z. B. https://...openai.azure.com/
openai.api_version = "2024-05-01-preview"
openai.api_key = os.getenv("AZURE_OPENAI_KEY")

GPT_DEPLOYMENT = "gpt-4o"  # Name deines Deployments

# === Azure Cognitive Search Konfiguration ===
SEARCH_ENDPOINT = os.getenv("AZURE_SEARCH_ENDPOINT")  # z. B. https://itlandaisearch3.search.windows.net/
SEARCH_KEY = os.getenv("AZURE_SEARCH_KEY")
SEARCH_INDEX = "index_itland_webcrawler"

# === RAG-Funktion: Hole relevante Inhalte aus Azure Search ===
def get_context_from_search(query):
    headers = {
        "Content-Type": "application/json",
        "api-key": SEARCH_KEY
    }
    search_url = f"{SEARCH_ENDPOINT}/indexes/{SEARCH_INDEX}/docs/search?api-version=2023-07-01"
    body = {
        "search": query,
        "top": 5
    }

    try:
        response = requests.post(search_url, headers=headers, json=body)
        response.raise_for_status()
        results = response.json()
        context = "\n".join([doc.get("content", "") for doc in results.get("value", [])])
        logging.debug(f"RAG-Treffer: {len(results.get('value', []))} Dokumente")
        return context
    except Exception as e:
        logging.error(f"Fehler bei Azure Search: {e}")
        return ""

# === Hauptfunktion: Chat mit GPT-4o + Kontext ===
@app.route("/chat", methods=["POST"])
def chat():
    user_input = request.json.get("message", "")
    logging.debug(f"Nutzerfrage: {user_input}")

    try:
        context = get_context_from_search(user_input)

        system_prompt = f"""
Du bist ein hilfreicher Assistent für die Website LandKI. Beantworte Fragen nur auf Basis folgender Inhalte:
---
{context}
---
Wenn die Antwort nicht in den Inhalten steht, sag ehrlich, dass du es nicht weißt.
Antworten bitte in der Sprache des Nutzers. Nutze Markdown für Formatierung.
"""

        response = openai.ChatCompletion.create(
            engine=GPT_DEPLOYMENT,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input}
            ],
            temperature=0.3,
            max_tokens=1000
        )

        reply = response.choices[0].message.content
        return jsonify({"reply": reply})

    except Exception as e:
        logging.error(f"Fehler bei Chat-Verarbeitung: {e}")
        return jsonify({"error": str(e)}), 500


# === Debug-Route: Einfacher GET-Test für Azure oder HealthCheck ===
@app.route("/", methods=["GET"])
def index():
    return "OK – Minimalversion aktiv"

# === Erweiterte Fehleranalyse (optional) ===
@app.route("/status", methods=["GET"])
def status():
    try:
        # Prüfe z. B. ob die ENV-Variablen vorhanden sind
        assert openai.api_key is not None, "OpenAI API Key fehlt"
        assert SEARCH_ENDPOINT is not None, "SEARCH_ENDPOINT fehlt"
        return jsonify({"status": "ready", "openai": True, "search": True})
    except Exception as e:
        logging.error(f"/status Fehler: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


# === Starten der App ===
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
