
from flask import Flask, request, jsonify
import os
import logging
import traceback
import requests
from colorlog import ColoredFormatter
from openai import AzureOpenAI
from deep_translator import GoogleTranslator
from langdetect import detect
import markdown2

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

def detect_language(text):
    try:
        return detect(text)
    except Exception as e:
        logger.warning(f"Spracherkennung fehlgeschlagen: {e}")
        return "en"

def translate(text, target_lang):
    try:
        return GoogleTranslator(source="auto", target=target_lang).translate(text)
    except Exception as e:
        logger.warning(f"Übersetzung fehlgeschlagen: {e}")
        return text

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
        detected_lang = detect_language(user_input)
        translated_input = translate(user_input, "en")
        logger.info(f"📨 Eingabe: {user_input} → Übersetzt: {translated_input} (Sprache: {detected_lang})")

        context = search_azure(translated_input)
        prompt = f"Use the following context to answer the question:\n{context}\n\nQuestion: {translated_input}\nAnswer:"

        response = client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2
        )

        answer_en = response.choices[0].message.content
        answer = translate(answer_en, detected_lang)
        logger.info("✅ Antwort erfolgreich erstellt.")
        return jsonify({
            "reply": answer,
            "reply_html": markdown2.markdown(answer),
            "language": detected_lang
        })
    except Exception as e:
        logger.error("❌ Fehler im /chat Endpunkt")
        logger.error(traceback.format_exc())
        return jsonify({
            "error": "Fehler beim Verarbeiten der Anfrage.",
            "details": str(e)
        }), 500

@app.route("/", methods=["GET"])
def root():
    return "LandKI – GPT-4o + Search + Übersetzung + Markdown (Debug-Version läuft!)"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
