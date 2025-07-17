
from flask import Flask, request, jsonify
import os
import logging
import traceback
import requests
from colorlog import ColoredFormatter
from openai import AzureOpenAI

# Farb-Logging konfigurieren
formatter = ColoredFormatter(
    "%(log_color)s[%(levelname)s]%(reset)s %(message)s",
    log_colors={
        'DEBUG': 'cyan',
        'INFO': 'green',
        'WARNING': 'yellow',
        'ERROR': 'red',
        'CRITICAL': 'bold_red',
    }
)
handler = logging.StreamHandler()
handler.setFormatter(formatter)
logger = logging.getLogger()
logger.addHandler(handler)
logger.setLevel(logging.INFO)

app = Flask(__name__)

# Azure-Konfiguration
AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_KEY")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")
AZURE_SEARCH_ENDPOINT = os.getenv("AZURE_SEARCH_ENDPOINT")
AZURE_SEARCH_KEY = os.getenv("AZURE_SEARCH_KEY")
AZURE_SEARCH_INDEX = os.getenv("AZURE_SEARCH_INDEX")

client = AzureOpenAI(
    api_key=AZURE_OPENAI_KEY,
    api_version="2024-02-15-preview",
    azure_endpoint=AZURE_OPENAI_ENDPOINT
)

def search_azure(query):
    try:
        headers = {
            "Content-Type": "application/json",
            "api-key": AZURE_SEARCH_KEY
        }
        url = f"{AZURE_SEARCH_ENDPOINT}/indexes/{AZURE_SEARCH_INDEX}/docs/search?api-version=2023-07-01-Preview"
        body = {
            "search": query,
            "top": 5
        }
        logger.info(f"🔎 Suche mit: {query}")
        response = requests.post(url, headers=headers, json=body)
        response.raise_for_status()
        results = response.json()
        contents = [doc['content'] for doc in results.get('value', []) if 'content' in doc]
        logger.info(f"📄 {len(contents)} Ergebnisse aus Azure Search")
        return "\n---\n".join(contents)
    except Exception as e:
        logger.error("❌ Fehler bei Azure Search")
        logger.error(traceback.format_exc())
        return "Fehler bei der Azure Search."

@app.route("/chat", methods=["POST"])
def chat():
    try:
        user_input = request.json.get("message", "")
        logger.info(f"📨 Eingabe: {user_input}")

        context = search_azure(user_input)
        prompt = f"Nutze die folgenden Inhalte als Wissensbasis:\n{context}\n\nFrage: {user_input}\nAntwort:"

        response = client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2
        )

        answer = response.choices[0].message.content
        logger.info("✅ Antwort erfolgreich erstellt.")
        return jsonify({"response": answer})
    except Exception as e:
        logger.error("❌ Fehler im /chat Endpunkt")
        logger.error(traceback.format_exc())
        return jsonify({
            "error": "Fehler beim Verarbeiten der Anfrage.",
            "details": str(e)
        }), 500

@app.route("/", methods=["GET"])
def root():
    return "LandKI – Azure GPT-4o RAG Bot (Debug-Version läuft!)"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
