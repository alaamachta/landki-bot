from flask import Flask, request, jsonify
from flask_cors import CORS
from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential
from openai import AzureOpenAI
from deep_translator import GoogleTranslator
from langdetect import detect
import markdown2
import os
import time
import traceback

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
        try:
            detected_lang = detect(question)
        except Exception:
            detected_lang = "de"

        # 🧠 Ton erkennen (Du / Sie / neutral)
        tone = "neutral"
        if detected_lang == "de":
            if any(word in question.lower() for word in [" sie ", "ihnen", "ihr unternehmen", "was bieten sie", "kann ich sie"]):
                tone = "sie"
            else:
                tone = "du"

        # 🧑‍💼 Persona definieren
        if tone == "du":
            persona = (
                "Du bist LandKI – der freundliche KI-Assistent von it-land.net. "
                "Sprich den Nutzer in der Du-Form an. Antworte in seiner Sprache und nur basierend auf dem bereitgestellten Kontext. "
                "Wenn du etwas nicht weißt, sei offen, direkt und freundlich."
            )
        elif tone == "sie":
            persona = (
                "Sie sind LandKI – der freundliche KI-Assistent von it-land.net. "
                "Sprechen Sie den Nutzer in der Sie-Form an. Antworten Sie in der Sprache des Nutzers und nur basierend auf dem bereitgestellten Kontext. "
                "Wenn Sie etwas nicht wissen, sagen Sie das bitte offen und höflich."
            )
        else:
            persona = (
                "Du bist LandKI – der mehrsprachige KI-Assistent von it-land.net. "
                "Sprich neutral (z. B. bei Arabisch) und antworte in der Sprache des Nutzers. "
                "Beziehe dich ausschließlich auf den bereitgestellten Kontext. "
                "Wenn du etwas nicht weißt, sei professionell, ehrlich und hilfreich."
            )

        # 🔍 Azure Search
        search_results = search_client.search(question)
        docs = []
        for result in search_results:
            content = result.get("content", "") or result.get("text", "")
            if content:
                docs.append(content.strip())
            if len(docs) >= 3:
                break

        context = "\n\n".join(docs).strip()

        # 🌐 Kontext übersetzen, wenn Sprache ≠ Deutsch
        if context and detected_lang != "de":
            try:
                translated = GoogleTranslator(source='de', target=detected_lang).translate(context)
                context = translated
            except Exception as e:
                print("⚠️ Übersetzung fehlgeschlagen:", e)

        # 📏 Länge begrenzen
        if len(context) > 1500:
            context = context[:1000]

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
        duration = time.time() - start
        print(f"✅ GPT-Antwortzeit: {duration:.2f} Sek.")

        answer = response.choices[0].message.content.strip()
        answer_html = markdown2.markdown(answer)
        return jsonify({"response": answer_html})

    except Exception as e:
        print("❌ Fehler im /chat-Endpoint:", str(e))
        traceback.print_exc()
        return jsonify({"response": f"❌ Interner Fehler: {str(e)}"}), 500
