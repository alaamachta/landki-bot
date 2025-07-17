from flask import Flask, request, jsonify
import os
import logging
import traceback
import requests
from colorlog import ColoredFormatter
from openai import AzureOpenAI
from deep_translator import MyMemoryTranslator
from langdetect import detect
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

# === Sprachübersetzung vorbereiten ===
lang_map = {
    "de": "german", "en": "english", "fr": "french", "it": "italian", "es": "spanish",
    "pt": "portuguese", "tr": "turkish", "ar": "arabic", "ru": "russian", "nl": "dutch"
}

def detect_language(text):
    try:
        return detect(text)
    except Exception as e:
        logger.warning(f"⚠️ Sprache konnte nicht erkannt werden: {e}")
        return "en"

def translate(text, target_lang):
    try:
        lang_code = lang_map.get(target_lang, "english")
        translated = MyMemoryTranslator(source="auto", target=lang_code).translate(text)
        return translated
    except Exception as e:
        logger.warning(f"⚠️ Übersetzungsfehler: {e}")
        return text

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

@app.route("/chat", methods=["POST"])
def chat():
    try:
        user_input = request.json.get("message", "")
        logger.info(f"👤 Eingabe vom User: {user_input}")

        lang = detect_language(user_input)
        logger.info(f"🌍 Erkannte Sprache: {lang}")

        translated_input = translate(user_input, "en")
        logger.info(f"📝 Übersetzt (→EN): {translated_input}")

        context = search_azure(translated_input)
        logger.info(f"📚 Kontext geladen ({len(context)} Zeichen)")

        prompt = f"Use the following context to answer the question:\n{context}\n\nQuestion: {translated_input}\nAnswer:"

        response = client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2
        )

        answer_en = response.choices[0].message.content
        logger.info(f"✅ Antwort (EN): {answer_en[:100]}...")

        answer = translate(answer_en, lang)
        logger.info(f"🔁 Antwort zurückübersetzt ({lang}): {answer[:100]}...")

        return jsonify({
            "reply": answer,
            "reply_html": markdown2.markdown(answer),
            "language": lang
        })

    except Exception as e:
        logger.error("❌ Fehler im Chat-Endpunkt:")
        logger.error(traceback.format_exc())
        return jsonify({"error": "Fehler bei Verarbeitung", "details": str(e)}), 500

@app.route("/")
def root():
    return "✅ LandKI läuft mit GPT-4o & Azure Search!"
