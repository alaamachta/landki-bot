from flask import Flask, request, jsonify, session
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
app.secret_key = os.getenv("APP_SECRET_KEY", "supersecret")  # Session-Schutz

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
    return "✅ LandKI Bot mit GPT-4o & Azure Search (Umschaltbarer Ton) ist aktiv!"

@app.route("/chat", methods=["POST"])
def chat():
    try:
        data = request.get_json()
        question = data.get("message", "").strip().lower()

        if not question:
            return jsonify({"response": "❌ Keine Frage erhalten."}), 400

        # 👋 Smalltalk (z. B. Begrüßung)
        greetings = ["hi", "hallo", "hey", "servus", "moin", "guten tag"]
        if question in greetings:
            return jsonify({"response": "👋 Hallo! Ich bin LandKI – möchtest du lieber per Du oder Sie angesprochen werden?"})

        # 🎯 Sprachstil erkennen und setzen
        if "siezen" in question or "sie" in question:
            session['tone'] = "sie"
            return jsonify({"response": "Natürlich. Ich werde Sie ab jetzt mit *Sie* ansprechen."})
        elif "duzen" in question or "du" in question:
            session['tone'] = "du"
            return jsonify({"response": "Alles klar – ich spreche dich ab jetzt gerne mit *Du* an."})

        tone = session.get('tone', 'du')  # Standard: du

        # 🔍 Azure Search Ergebnisse sammeln
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

        if len(context) > 3000:
            context = context[:3000]

        # 🤖 Dynamische system-Nachricht
        if tone == "sie":
            system_message = (
                "Du bist LandKI – der KI-Assistent von IT-Land. Sprich bitte in der höflichen *Sie*-Form."
                " Du antwortest im Namen von IT-Land und nutzt nur den bereitgestellten Kontext."
            )
        else:
            system_message = (
                "Du bist LandKI – unser freundlicher KI-Assistent bei IT-Land."
                " Du sprichst im Namen unseres Teams in der lockeren *Du*-Form."
                " Du antwortest auf Basis des bereitgestellten Kontexts. Wenn etwas nur indirekt erwähnt wird, darfst du logisch ergänzen (z. B. Telefonnummer für WhatsApp). Wenn du etwas nicht weißt, sei ehrlich und hilfsbereit."
            )

        start = time.time()
        response = client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": f"Kontext:\n{context}\n\nFrage:\n{question}"}
            ],
            temperature=0.4,
            max_tokens=600
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
