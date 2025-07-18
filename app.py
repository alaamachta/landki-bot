from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import logging
import traceback
import requests
from colorlog import ColoredFormatter
from openai import AzureOpenAI
import markdown2

# === Logging Setup ===
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

# === Flask App ===
app = Flask(__name__)
CORS(app)  # ⚠️ Wichtig für WordPress-Frontend-Zugriff

# === ENV Variablen laden ===
AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_KEY")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")
AZURE_SEARCH_ENDPOINT = os.getenv("AZURE_SEARCH_ENDPOINT")
AZURE_SEARCH_KEY = os.getenv("AZURE_SEARCH_KEY")
AZURE_SEARCH_INDEX = os.getenv("AZURE_SEARCH_INDEX")
OPENAI_API_VERSION = os.getenv("OPENAI_API_VERSION", "2024-05-01-preview")

# === OpenAI Client ===
client = AzureOpenAI(
    api_key=AZURE_OPENAI_KEY,
    api_version=OPENAI_API_VERSION,
    azure_endpoint=AZURE_OPENAI_ENDPOINT
)

# === Azure Search ===
def search_azure(query):
    try:
        headers = {
            "Content-Type": "application/json",
            "api-key": AZURE_SEARCH_KEY,
            "Accept": "application/json;odata.metadata=none"
        }
        url = f"{AZURE_SEARCH_ENDPOINT}/indexes/{AZURE_SEARCH_INDEX}/docs/search?api-version=2023-07-01-Preview"
        body = { "search": query, "top": 5 }

        logger.info(f"🔍 Azure Search mit: {query}")
        response = requests.post(url, headers=headers, json=body)
        response.raise_for_status()
        results = response.json()
        contents = [doc['content'] for doc in results.get('value', []) if 'content' in doc]
        logger.info(f"📦 {len(contents)} Dokumente aus Index gefunden")
        return "\n---\n".join(contents)
    except Exception as e:
        logger.error("❌ Fehler bei Azure Search:")
        logger.error(traceback.format_exc())
        return "Fehler bei der Azure Search."

# === /chat Endpoint ===
@app.route("/chat", methods=["POST"])
def chat():
    try:
        user_input = request.json.get("message", "")
        logger.info(f"👤 Eingabe vom User: {user_input}")

        context = search_azure(user_input)
        logger.info(f"📚 Kontext geladen ({len(context)} Zeichen)")

        prompt = f"Use the following context to answer the question:\n{context}\n\nQuestion: {user_input}\nAnswer:"

        response = client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2  # Geringe Kreativität, präzisere Antworten
        )

        answer = response.choices[0].message.content
        logger.info(f"✅ Antwort: {answer[:100]}...")

        return jsonify({
            "response": answer,
            "reply_html": markdown2.markdown(answer)
        })

    except Exception as e:
        logger.error("❌ Fehler im Chat-Endpunkt:")
        logger.error(traceback.format_exc())
        return jsonify({"error": "Fehler bei Verarbeitung", "details": str(e)}), 500

# === Health Check ===
@app.route("/")
def root():
    return "✅ LandKI ohne Übersetzungslogik läuft!"
