import os
import traceback
import markdown2
from flask import Flask, request, jsonify
from flask_cors import CORS
from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential
from openai import AzureOpenAI, RateLimitError
from langdetect import detect as detect_lang

print("🚀 Starte LandKI-Bot...")

# Umgebungsvariablen prüfen
required_env = [
    "AZURE_SEARCH_ENDPOINT", "AZURE_SEARCH_KEY", "AZURE_SEARCH_INDEX",
    "AZURE_OPENAI_KEY", "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_DEPLOYMENT"
]

for var in required_env:
    value = os.getenv(var)
    print(f"🔍 {var} = {'✅ OK' if value else '❌ FEHLT!'}")
    if not value:
        raise RuntimeError(f"❌ Umgebungsvariable {var} ist nicht gesetzt!")

# Variablen einlesen
AZURE_SEARCH_ENDPOINT = os.getenv("AZURE_SEARCH_ENDPOINT")
AZURE_SEARCH_KEY = os.getenv("AZURE_SEARCH_KEY")
AZURE_SEARCH_INDEX = os.getenv("AZURE_SEARCH_INDEX")
AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_KEY")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")

# Flask-App starten
app = Flask(__name__)
CORS(app, resources={r"/chat": {"origins": "*"}})

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
    return "✅ LandKI Bot läuft (Token optimiert + RateLimit-Schutz)"

@app.route("/chat", methods=["POST"])
def chat():
    try:
        data = request.get_json()
        question = data.get("message", "").strip()
        if not question:
            return jsonify({"response": "❌ Keine Frage erhalten."}), 400

        # Sprache erkennen
        lang = detect_lang(question)
        print(f"🌐 Sprache erkannt: {lang}")

        # Azure Search abrufen
        search_results = search_client.search(question)
        docs = []
        for result in search_results:
            content = result.get("content", "") or result.get("text", "")
            if content:
                docs.append(content.strip())
            if len(docs) >= 2:  # Weniger Kontext → weniger Token
                break

        context = "\n\n".join(docs).strip()
        context = context[:2000]  # Max 2000 Zeichen
        print("📚 Kontextlänge:", len(context))

        if not context:
            return jsonify({
                "response": "Ich habe dazu leider keine passenden Informationen gefunden. Frag mich gerne etwas zu unseren Leistungen oder zur Website!"
            })

        # System-Prompt
        persona = (
            "Du bist LandKI – ein freundlicher Assistent von it-land.net. "
            "Antworte bitte in der Sprache des Nutzers, direkt und ehrlich."
        )

        # GPT-Request mit RateLimitError-Schutz
        try:
            response = client.chat.completions.create(
                model=AZURE_OPENAI_DEPLOYMENT,
                messages=[
                    {"role": "system", "content": f"{persona} Nutzersprache: {lang.upper()}."},
                    {"role": "user", "content": f"Kontext:\n{context}\n\nFrage:\n{question}"}
                ],
                temperature=0.4,
                max_tokens=350  # Reduziert für geringeren Verbrauch
            )
        except RateLimitError:
            print("⚠️ RateLimit erreicht. Antworte freundlich.")
            return jsonify({
                "response": "⏳ Ich habe gerade viele Anfragen gleichzeitig erhalten. Bitte warte kurz und versuche es gleich nochmal."
            }), 429

        answer_raw = response.choices[0].message.content.strip()
        print("✅ GPT-Antwort empfangen.")

        # Markdown → HTML
        answer_html = markdown2.markdown(answer_raw)
        return jsonify({"response": answer_html})

    except Exception as e:
        print("❌ Fehler im /chat-Endpoint:", str(e))
        traceback.print_exc()
        return jsonify({"response": "❌ Interner Fehler: " + str(e)}), 500
