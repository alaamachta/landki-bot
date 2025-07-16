from flask import Flask, request, jsonify
from flask_cors import CORS
from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential
from openai import AzureOpenAI
from langdetect import detect
import os
import time
import traceback
import logging
import markdown2
from deep_translator import GoogleTranslator

# 📋 Logging konfigurieren
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("landki_bot.log"),
        logging.StreamHandler()
    ]
)
logging.info("📋 Logging wurde erfolgreich konfiguriert.")

# 🛠️ Flask & CORS Setup
app = Flask(__name__)
CORS(app, resources={r"/chat": {"origins": "*"}})

# 🔐 Umgebungsvariablen laden
AZURE_SEARCH_ENDPOINT = os.getenv("AZURE_SEARCH_ENDPOINT")
AZURE_SEARCH_KEY = os.getenv("AZURE_SEARCH_KEY")
AZURE_SEARCH_INDEX = os.getenv("AZURE_SEARCH_INDEX")
AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_KEY")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")

# 🔎 Azure Search Client
search_client = SearchClient(
    endpoint=AZURE_SEARCH_ENDPOINT,
    index_name=AZURE_SEARCH_INDEX,
    credential=AzureKeyCredential(AZURE_SEARCH_KEY)
)

# 🤖 GPT-Client
client = AzureOpenAI(
    api_key=AZURE_OPENAI_KEY,
    api_version="2024-05-01-preview",
    azure_endpoint=AZURE_OPENAI_ENDPOINT
)

@app.route("/")
def home():
    return "✅ LandKI Bot mit GPT-4o & Azure Search ist aktiv!"

@app.route("/chat", methods=["POST"])
def chat():
    try:
        data = request.get_json()
        question = data.get("message", "").strip()
        if not question:
            return jsonify({"response": "❌ Keine Frage erhalten."}), 400

        # 🌍 Sprache erkennen
        lang = detect(question)
        logging.info(f"🌐 Erkannte Sprache: {lang}")

        # 🧠 Anrede erkennen (nur bei Deutsch)
        tone = "neutral"
        if lang == "de":
            if any(phrase in question.lower() for phrase in [" sie ", "ihnen", "ihr unternehmen", "was bieten sie", "kann ich sie"]):
                tone = "sie"
            else:
                tone = "du"

        # 🧠 Persona definieren
        if tone == "du":
            persona = (
                "Du bist LandKI – der freundliche KI-Assistent von it-land.net. "
                "Sprich den Nutzer in der Du-Form an. Antworte in seiner Sprache und auf Basis des bereitgestellten Kontexts. "
                "Wenn du etwas nicht weißt, sag das offen und freundlich."
            )
        elif tone == "sie":
            persona = (
                "Sie sind LandKI – der freundliche KI-Assistent von it-land.net. "
                "Sprechen Sie den Nutzer in der Sie-Form an. Antworten Sie in seiner Sprache und auf Basis des bereitgestellten Kontexts. "
                "Wenn Sie etwas nicht wissen, sagen Sie das bitte offen und höflich."
            )
        else:
            persona = (
                "Du bist LandKI – der freundliche KI-Assistent von it-land.net. "
                "Antworte bitte in der Sprache des Nutzers, aber verwende einen neutralen Ton (z. B. im Arabischen). "
                "Antworte professionell, freundlich und direkt. Wenn du etwas nicht weißt, sag das offen."
            )

        # 🔍 Azure Search (max 3 Ergebnisse)
        search_results = search_client.search(question)
        docs = []
        for result in search_results:
            content = result.get("content", "") or result.get("text", "")
            if content:
                docs.append(content.strip())
            if len(docs) >= 3:
                break

        context = "\n\n".join(docs).strip()

        if not context:
            return jsonify({
                "response": "Ich habe dazu leider keine passenden Informationen gefunden. "
                            "Frag mich gerne etwas zu unseren Leistungen oder zur Website!"
            })

        # 🌐 Kontext übersetzen (optional)
        if lang != "de":
            try:
                context = GoogleTranslator(source='de', target=lang).translate(context)
                logging.info("🌍 Kontext wurde übersetzt.")
            except Exception as trans_err:
                logging.warning(f"⚠️ Fehler bei der Übersetzung des Kontexts: {trans_err}")

        if len(context) > 1500:
            context = context[:1000]  # Performance-Optimierung

        # 🤖 GPT-4o Anfrage
        start = time.time()
        response = client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,
            messages=[
                {"role": "system", "content": persona},
                {"role": "user", "content": f"Kontext:\n{context}\n\nFrage:\n{question}"}
            ],
            temperature=0.4,
            max_tokens=600
        )
        end = time.time()
        logging.info(f"✅ GPT-Antwortzeit: {end - start:.2f} Sekunden")

        # 🧾 Antwort verarbeiten
        answer = response.choices[0].message.content.strip()
        answer_html = markdown2.markdown(answer)
        return jsonify({"response": answer_html})

    except Exception as e:
        logging.error("❌ Fehler im /chat-Endpoint:")
        traceback.print_exc()
        return jsonify({"response": f"❌ Interner Fehler: {str(e)}"}), 500
