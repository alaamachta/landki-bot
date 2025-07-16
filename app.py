
from flask import Flask, request, jsonify
from flask_cors import CORS
from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential
from openai import AzureOpenAI
from langdetect import detect
from googletrans import Translator
import os
import traceback
import markdown2

app = Flask(__name__)
CORS(app, resources={r"/chat": {"origins": "*"}})

# 🔐 Umgebungsvariablen laden
AZURE_SEARCH_ENDPOINT = os.getenv("AZURE_SEARCH_ENDPOINT")
AZURE_SEARCH_KEY = os.getenv("AZURE_SEARCH_KEY")
AZURE_SEARCH_INDEX = os.getenv("AZURE_SEARCH_INDEX")
AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_KEY")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")

# Azure Search Client & GPT-Client
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

translator = Translator()

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

        # 🧠 Anrede-Tonfall erkennen (nur bei Deutsch)
        tone = "neutral"
        if lang == "de":
            if any(phrase in question.lower() for phrase in [" sie ", "ihnen", "ihr unternehmen", "was bieten sie", "kann ich sie"]):
                tone = "sie"
            else:
                tone = "du"

        # 👤 Persona dynamisch anpassen
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

        # 🔎 Suche im Index (Azure Cognitive Search)
        search_results = search_client.search(question)
        docs = []
        for result in search_results:
            content = result.get("content", "") or result.get("text", "")
            if content:
                docs.append(content.strip())
            if len(docs) >= 3:
                break

        context = "

".join(docs).strip()

        # 🌐 Kontext übersetzen (wenn Sprache ≠ Deutsch)
        if lang != "de" and context:
            translated_context = translator.translate(context, src="de", dest=lang).text
        else:
            translated_context = context

        if not translated_context:
            return jsonify({
                "response": "Ich habe dazu leider keine passenden Informationen gefunden. "
                            "Frag mich gerne etwas zu unseren Leistungen oder zur Website!"
            })

        if len(translated_context) > 1500:
            translated_context = translated_context[:1000]

        # 🤖 GPT-4o anfragen
        response = client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,
            messages=[
                {"role": "system", "content": persona},
                {"role": "user", "content": f"Kontext:
{translated_context}

Frage:
{question}"}
            ],
            temperature=0.4,
            max_tokens=600
        )

        answer = response.choices[0].message.content.strip()
        answer_html = markdown2.markdown(answer)

        return jsonify({"response": answer_html})

    except Exception as e:
        print("❌ Fehler im /chat-Endpoint:", str(e))
        traceback.print_exc()
        return jsonify({"response": "❌ Interner Fehler: " + str(e)}), 500
