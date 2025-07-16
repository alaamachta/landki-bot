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
        question = data.get("message", "").strip()
        if not question:
            return jsonify({"response": "❌ Keine Frage erhalten."}), 400

        # 🔍 Anredeform & Sprache automatisch erkennen
        q_lower = question.lower()
        tone = "du"
        if any(phrase in q_lower for phrase in [
            " sie ", "ihnen", "ihr unternehmen", "können sie", "kann ich sie", 
            "wie erreiche ich sie", "was bieten sie", "mit ihnen sprechen"
        ]):
            tone = "sie"

        # 🧠 System-Prompt dynamisch erzeugen
        if tone == "du":
            persona = (
                "Du bist LandKI – der freundliche, mehrsprachige KI-Assistent von it-land.net. "
                "Sprich den Nutzer **in der Du-Form** an. "
                "Antworte **in der Sprache**, in der die Frage gestellt wurde – z. B. Arabisch, Englisch oder Französisch. "
                "Nutze den bereitgestellten Kontext. "
                "Wenn du keine passende Information findest, sag das ehrlich und freundlich."
            )
        else:
            persona = (
                "Sie sind LandKI – der professionelle, mehrsprachige KI-Assistent von it-land.net. "
                "Sprechen Sie den Nutzer **in der Sie-Form** an. "
                "Antworten Sie **in der Sprache**, in der die Frage gestellt wurde – z. B. Arabisch, Englisch oder Französisch. "
                "Nutzen Sie den bereitgestellten Kontext. "
                "Falls Sie keine passende Information finden, sagen Sie das bitte höflich."
            )

        # 🔍 Suche im Index (Azure Cognitive Search)
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

        if len(context) > 1500:
            context = context[:1000]  # Performance-Optimierung

        # 🤖 GPT-4o anfragen
        response = client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,
            messages=[
                {"role": "system", "content": persona},
                {"role": "user", "content": f"Kontext:\n{context}\n\nFrage:\n{question}"}
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
