from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import openai
import httpx
from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential
from langdetect import detect
from deep_translator import MyMemoryTranslator
import logging
import colorlog

# Logging konfigurieren
handler = colorlog.StreamHandler()
handler.setFormatter(colorlog.ColoredFormatter('%(log_color)s[%(levelname)s] %(message)s'))
logger = colorlog.getLogger()
logger.addHandler(handler)
logger.setLevel(logging.INFO)

# Flask Setup
app = Flask(__name__)
CORS(app)

# Umgebungsvariablen aus Azure
openai.api_key = os.environ["AZURE_OPENAI_KEY"]
openai.api_base = os.environ["AZURE_OPENAI_ENDPOINT"]
openai.api_type = "azure"
openai.api_version = os.environ.get("OPENAI_API_VERSION", "2024-05-01-preview")
deployment = os.environ["AZURE_OPENAI_DEPLOYMENT"]

search_endpoint = os.environ["AZURE_SEARCH_ENDPOINT"]
search_key = os.environ["AZURE_SEARCH_KEY"]
search_index = os.environ["AZURE_SEARCH_INDEX"]

# Azure Cognitive Search Client
search_client = SearchClient(
    endpoint=search_endpoint,
    index_name=search_index,
    credential=AzureKeyCredential(search_key),
)

# Funktion: Sprache erkennen
def detect_language(text):
    try:
        return detect(text)
    except Exception:
        return "unknown"

# Funktion: Übersetzen (MyMemory)
def translate(text, source, target):
    try:
        translated = MyMemoryTranslator(source=source, target=target).translate(text)
        return translated
    except Exception as e:
        logger.warning(f"Übersetzungsfehler: {e}")
        return text  # Fallback = Originaltext

# Funktion: Suche im Index
def search_knowledge_base(query):
    results = search_client.search(search_text=query, include_total_count=True)
    docs = []
    for result in results:
        if "content" in result:
            docs.append(result["content"])
    return docs

# Funktion: GPT-Aufruf mit RAG
def ask_openai(question, docs):
    content = "\n\n".join(docs[:5]) if docs else ""
    messages = [
        {"role": "system", "content": "Beantworte nur basierend auf dem Firmenwissen. Wenn du etwas nicht weißt, sag es ehrlich."},
        {"role": "user", "content": f"Frage: {question}\n\nWissen:\n{content}"}
    ]
    try:
        response = openai.ChatCompletion.create(
            engine=deployment,
            messages=messages,
            temperature=0.3,
            max_tokens=1200
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"OpenAI-Fehler: {e}")
        return "❌ Fehler beim Abrufen der Antwort. Bitte versuche es später erneut."

# Route: Test
@app.route("/test")
def test():
    return "✅ Bot läuft!"

# Route: Haupt-Chat
@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json()
    user_input = data.get("message", "")
    if not user_input:
        return jsonify({"response": "❌ Keine Eingabe erhalten."}), 400

    lang = detect_language(user_input)
    logger.info(f"Eingabe erkannt in Sprache: {lang}")

    # Falls nicht Deutsch: nach Deutsch übersetzen
    input_de = translate(user_input, source=lang, target="de") if lang != "de" else user_input
    logger.info(f"Übersetzt (→DE): {input_de}")

    docs = search_knowledge_base(input_de)
    logger.info(f"{len(docs)} Dokumente aus Index gefunden")

    response_de = ask_openai(input_de, docs)

    # Wenn Originalsprache nicht Deutsch → zurückübersetzen
    response_final = translate(response_de, source="de", target=lang) if lang != "de" else response_de
    logger.info(f"Antwort in {lang}: {response_final}")

    return jsonify({"response": response_final})

# App Start
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
