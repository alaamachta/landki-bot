from flask import Flask, request, jsonify
from flask_cors import CORS
from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential
from openai import AzureOpenAI
import os
import time
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

# 🔎 Azure Search Client
search_client = SearchClient(
    endpoint=AZURE_SEARCH_ENDPOINT,
    index_name=AZURE_SEARCH_INDEX,
    credential=AzureKeyCredential(AZURE_SEARCH_KEY)
)

# 🤖 GPT-Client (GPT-4o)
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
        question = data.get("message", "").strip().lower()

        if not question:
            return jsonify({"response": "❌ Keine Frage erhalten."}), 400

        # 👉 Smalltalk direkt beantworten
        smalltalk = ["hi", "hallo", "hey", "servus", "moin", "guten tag"]
        if question in smalltalk:
            return jsonify({"response": "Hey! 😊 Wie kann ich dir weiterhelfen?"})

        # 🔍 Azure Search Ergebnisse (Top 3 Dokumente)
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

        # 🔒 Kontext begrenzen
        if len(context) > 3000:
            context = context[:3000]

        # 💬 GPT-4o anfragen
        start = time.time()
        response = client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,
            messages=[
                {"role": "system", "content": (
                    "Du bist LandKI – der freundliche KI-Assistent von it-land.net. "
                    "Nutze den bereitgestellten Kontext so gut wie möglich. Wenn etwas im Kontext nur indirekt steht, "
                    "darfst du logische Schlüsse ziehen (z. B. wenn eine Telefonnummer für WhatsApp genutzt wird). "
                    "Wenn du etwas gar nicht weißt, sei ehrlich und weise freundlich darauf hin."
                )},
                {"role": "user", "content": f"Kontext:\n{context}\n\nFrage:\n{question}"}
            ],
            temperature=0.4,
            max_tokens=600,        # Begrenzte Antwortlänge
        )
        end = time.time()
        print(f"✅ GPT-Antwortzeit: {end - start:.2f} Sekunden")

        answer_raw = response.choices[0].message.content.strip()
        answer_html = markdown2.markdown(answer_raw)
        return jsonify({"response": answer_html})

    except Exception as e:
        print("❌ Fehler im /chat-Endpoint:", str(e))
        traceback.print_exc()
        return jsonify({"response": "❌ Interner Fehler: " + str(e)}), 500
