from flask import Flask, request, jsonify
from flask_cors import CORS
from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential
from openai import AzureOpenAI
from deep_translator import GoogleTranslator
from langdetect import detect
import os
import time
import traceback
import markdown2

app = Flask(__name__)
CORS(app, resources={r"/chat": {"origins": "*"}})

# Umgebungsvariablen
AZURE_SEARCH_ENDPOINT = os.getenv("AZURE_SEARCH_ENDPOINT")
AZURE_SEARCH_KEY = os.getenv("AZURE_SEARCH_KEY")
AZURE_SEARCH_INDEX = os.getenv("AZURE_SEARCH_INDEX")
AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_KEY")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")

# Azure Clients
search_client = SearchClient(
    endpoint=AZURE_SEARCH_ENDPOINT,
    index_name=AZURE_SEARCH_INDEX,
    credential=AzureKeyCredential(AZURE_SEARCH_KEY)
)

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

        # Sprache erkennen
        lang = detect(question)

        # Tonwahl (du/sie)
        tone = "neutral"
        if lang == "de":
            if any(phrase in question.lower() for phrase in [" sie ", "ihnen", "ihr unternehmen", "was bieten sie", "kann ich sie"]):
                tone = "sie"
            else:
                tone = "du"

        if tone == "du":
            persona = (
                "Du bist LandKI – der freundliche KI-Assistent von it-land.net. "
                "Sprich den Nutzer in der Du-Form an. Antworte in seiner Sprache und nur auf Basis des bereitgestellten Kontexts. "
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
                "Antworte bitte in der Sprache des Nutzers, aber verwende einen neutralen Ton. "
                "Antworte professionell, freundlich und direkt. Wenn du etwas nicht weißt, sag das offen."
            )

        # Azure Search
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
                "response": "Ich habe dazu leider keine passenden Informationen gefunden. Frag mich gerne etwas zu unseren Leistungen oder zur Website!"
            })

        # Optional: Kontext übersetzen
        if lang != "de":
            try:
                context = GoogleTranslator(source="de", target=lang).translate(context)
            except Exception as e:
                print("⚠️ Übersetzung fehlgeschlagen:", str(e))

        # GPT-4o
        response = client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,
            messages=[
                {"role": "system", "content": persona},
                {"role": "user", "content": f"Kontext:\n{context}\n\nFrage:\n{question}"}
            ],
            temperature=0.4,
            max_tokens=600
        )

        answer_raw = response.choices[0].message.content.strip()

        # Optional: Antwort zurückübersetzen
        if lang != "de":
            try:
                answer_raw = GoogleTranslator(source="de", target=lang).translate(answer_raw)
            except Exception as e:
                print("⚠️ Rückübersetzung fehlgeschlagen:", str(e))

        answer_html = markdown2.markdown(answer_raw)
        return jsonify({"response": answer_html})

    except Exception as e:
        print("❌ Fehler im /chat-Endpoint:", str(e))
        traceback.print_exc()
        return jsonify({"response": "❌ Interner Fehler: " + str(e)}), 500
