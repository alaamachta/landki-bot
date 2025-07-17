
import os
import openai
import json
import logging
import traceback
from flask import Flask, request, jsonify
from flask_cors import CORS
from deep_translator import GoogleTranslator
from langdetect import detect
from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential
from colorlog import ColoredFormatter

# Farbiges Logging konfigurieren
formatter = ColoredFormatter(
    "%(log_color)s[%(levelname)s]%(reset)s %(message)s",
    log_colors={
        'DEBUG': 'cyan',
        'INFO': 'green',
        'WARNING': 'yellow',
        'ERROR': 'red',
        'CRITICAL': 'red,bg_white',
    }
)
handler = logging.StreamHandler()
handler.setFormatter(formatter)
logger = logging.getLogger()
logger.addHandler(handler)
logger.setLevel(logging.INFO)

app = Flask(__name__)
CORS(app)

# Umgebungsvariablen laden
openai.api_key = os.getenv("OPENAI_API_KEY")
openai_endpoint = os.getenv("OPENAI_ENDPOINT")
openai_deployment_id = os.getenv("OPENAI_DEPLOYMENT_ID")
search_endpoint = os.getenv("AZURE_SEARCH_ENDPOINT")
search_key = os.getenv("AZURE_SEARCH_KEY")
search_index = os.getenv("AZURE_SEARCH_INDEX")

def detect_language(text):
    try:
        return detect(text)
    except Exception as e:
        logger.warning(f"Spracherkennung fehlgeschlagen: {e}")
        return "en"

def translate_text(text, target_lang):
    try:
        return GoogleTranslator(source="auto", target=target_lang).translate(text)
    except Exception as e:
        logger.warning(f"Übersetzung fehlgeschlagen: {e}")
        return text

def get_search_results(query):
    try:
        search_client = SearchClient(
            endpoint=search_endpoint,
            index_name=search_index,
            credential=AzureKeyCredential(search_key)
        )
        results = search_client.search(query, top=5)
        content = ""
        for result in results:
            content += result.get('content', '') + "\n"
        return content
    except Exception as e:
        logger.error("Fehler bei Azure Search: " + str(e))
        traceback.print_exc()
        return "Fehler bei Azure Search."

@app.route("/chat", methods=["POST"])
def chat():
    try:
        user_input = request.json.get("message", "")
        if not user_input:
            return jsonify({"error": "Missing message"}), 400

        input_lang = detect_language(user_input)
        user_input_en = translate_text(user_input, "en")
        logger.info(f"Eingabe erkannt: '{user_input}' (Sprache: {input_lang})")

        search_context = get_search_results(user_input_en)
        prompt = f"Answer the following question using the context below.\n\nContext:\n{search_context}\n\nQuestion: {user_input_en}"

        response = openai.ChatCompletion.create(
            engine=openai_deployment_id,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5
        )
        answer_en = response.choices[0].message["content"]
        final_answer = translate_text(answer_en, input_lang)

        logger.info(f"Antwort (EN): {answer_en}")
        return jsonify({"reply": final_answer, "original_language": input_lang})

    except Exception as e:
        error_details = traceback.format_exc()
        logger.error(f"FEHLER: {e}\n{error_details}")
        return jsonify({
            "error": "Interner Fehler im Chat-Endpunkt.",
            "details": str(e),
            "trace": error_details
        }), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
