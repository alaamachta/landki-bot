from flask import Flask, request, jsonify
from flask_cors import CORS
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

lang_map = {
    "de": "german", "en": "english", "fr": "french", "it": "italian", "es": "spanish",
    "pt": "portuguese", "tr": "turkish", "ar": "arabic", "ru": "russian", "nl": "dutch"
}

def detect_language(text):
    try:
        return detect(text)
    except:
        return "en"

def translate(text, target_lang):
    try:
        lang_code = lang_map.get(target_lang, "english")
        return MyMemoryTranslator(source="auto", target=lang_code).translate(text)
    except:
        return text

def search_azure(query):
    try:
        headers = {
            "Content-Type": "application/json",
            "api-key": AZURE_SEARCH_KEY,
            "Accept": "application/json;odata.metadata=none"
        }
        url = f"{AZURE_SEARCH_ENDPOINT}/indexes/{AZURE_SEARCH_INDEX}/docs/search?api-version=2023-07-01-Preview"
        body = { "search": query, "top": 1 }

        response = requests.post(url, headers=headers, json=body)
        response.raise_for_status()
        results = response.json()
        contents = [doc['content'] for doc in results.get('value', []) if 'content' in doc]
        return "\n---\n".join(contents)
    except:
        return ""

def is_smalltalk(msg):
    patterns = ["hallo", "hi", "wie geht", "servus", "moin", "wer bist", "danke", "ciao", "tschüss"]
    return any(p in msg.lower() for p in patterns)

@app.route("/chat", methods=["POST"])
def chat():
    try:
        user_input = request.json.get("message", "")
        lang = detect_language(user_input)
        translated_input = translate(user_input, "en")

        if is_smalltalk(user_input):
            prompt = translated_input
        else:
            context = search_azure(translated_input)
            prompt = f"{context}\n\nQ: {translated_input}\nA:"
            max_context_chars = 6000
            if len(context) > max_context_chars:
                context = context[:max_context_chars]
                logger.info("✂️ Kontext wurde gekürzt auf 6000 Zeichen")

        response = client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1, # Weniger kreative, klarere, kürzere Antworten
            max_tokens=50  # max_tokens=300 bedeutet, dass GPT-4o maximal ca. 200–250 Wörter zurückgeben darf.
        )

        answer_en = response.choices[0].message.content
        answer = translate(answer_en, lang)

        return jsonify({
            "reply": answer,
            "reply_html": markdown2.markdown(answer),
            "language": lang
        })
    except Exception as e:
        logger.error(traceback.format_exc())
        return jsonify({"error": "Fehler bei Verarbeitung", "details": str(e)}), 500

@app.route("/")
def root():
    return "✅ LandKI optimierte Version läuft!"
