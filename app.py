from flask import Flask, request, jsonify
from flask_cors import CORS
from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential
from openai import AzureOpenAI
import os
import random
import time
import traceback

app = Flask(__name__)
CORS(app, resources={r"/chat": {"origins": "*"}})

# Umgebungsvariablen laden
AZURE_SEARCH_ENDPOINT = os.getenv("AZURE_SEARCH_ENDPOINT")
AZURE_SEARCH_KEY = os.getenv("AZURE_SEARCH_KEY")
AZURE_SEARCH_INDEX = os.getenv("AZURE_SEARCH_INDEX")
AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_KEY")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")

# Azure Ressourcen initialisieren
search_client = SearchClient(
    endpoint=AZURE_SEARCH_ENDPOINT,
    index_name=AZURE_SEARCH_INDEX,
    credential=AzureKeyCredential(AZURE_SEARCH_KEY)
)

client = AzureOpenAI(
    api_key=AZURE_OPENAI_KEY,
    api_version="2024-03-01-preview",
    azure_endpoint=AZURE_OPENAI_ENDPOINT
)

@app.route("/")
def home():
    return "✅ LandKI Bot mit GPT-4o & Azure Search aktiv!"

@app.route("/env")
def env():
    return jsonify({
        "AZURE_OPENAI_KEY": bool(AZURE_OPENAI_KEY),
        "AZURE_SEARCH_KEY": bool(AZURE_SEARCH_KEY),
        "AZURE_SEARCH_ENDPOINT": AZURE_SEARCH_ENDPOINT,
        "AZURE_OPENAI_DEPLOYMENT": AZURE_OPENAI_DEPLOYMENT
    })

@app.route("/chat", methods=["POST"])
def chat():
    try:
        data = request.get_json()
        question = data.get("message", "").strip().lower()

        if not question:
            return jsonify({"response": "❌ Keine Frage erhalten."}), 400

        # 🎉 Smalltalk direkt beantworten (ohne GPT)
        smalltalk = ["hi", "hallo", "hey", "servus", "moin", "guten tag"]
        if question in smalltalk:
            antworten = [
                "👋 Hallo! Schön, dass du da bist. Was möchtest du wissen?",
                "Hey! 😊 Wie kann ich dir weiterhelfen?",
                "Hallo! Was möchtest du über LandKI wissen?",
                "Hi! Frag mich gerne was zu unseren Leistungen oder Angeboten."
            ]
            return jsonify({"response": random.choice(antworten)})

        # 🔎 Azure Search Abfrage (Top 3)
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

        # 🧠 GPT-4o Anfrage vorbereiten
        start = time.time()
        response = client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,
            messages=[
                {"role": "system", "content": (
                    "Du bist LandKI – der freundliche KI-Assistent von it-land.net. "
                    "Antworte bitte nur auf Basis des folgenden Kontexts. "
                    "Wenn du etwas nicht weißt, sag offen, dass du dazu keine Informationen hast."
                )},
                {"role": "user", "content": f"Kontext:\n{context}\n\nFrage:\n{question}"}
            ],
            temperature=0.4,
            max_tokens=800
        )
        end = time.time()
        print(f"✅ GPT-Antwortzeit: {end - start:.2f} Sekunden")

        answer = response.choices[0].message.content.strip()
        return jsonify({"response": answer})

    except Exception as e:
        print("❌ Fehler im /chat-Endpoint:")
        traceback.print_exc()
        return jsonify({"response": "❌ Interner Fehler beim Antworten. Bitte versuch es später nochmal."}), 500
