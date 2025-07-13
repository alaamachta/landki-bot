from flask import Flask, request, jsonify
from flask_cors import CORS
import os
from openai import AzureOpenAI
from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential

app = Flask(__name__)
CORS(app)

# Umgebungsvariablen laden
AZURE_SEARCH_ENDPOINT = os.getenv("AZURE_SEARCH_ENDPOINT")
AZURE_SEARCH_KEY = os.getenv("AZURE_SEARCH_KEY")
AZURE_SEARCH_INDEX = os.getenv("AZURE_SEARCH_INDEX")

AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_KEY")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")

# Azure OpenAI Client
client = AzureOpenAI(
    api_key=AZURE_OPENAI_KEY,
    api_version="2024-05-01-preview",
    azure_endpoint=AZURE_OPENAI_ENDPOINT
)

# Azure Search Client
search_client = SearchClient(
    endpoint=AZURE_SEARCH_ENDPOINT,
    index_name=AZURE_SEARCH_INDEX,
    credential=AzureKeyCredential(AZURE_SEARCH_KEY)
)

@app.route("/")
def home():
    return "✅ LandKI Bot mit GPT-4o & Azure Search aktiv!"

@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json()
    question = data.get("message", "")

    if not question:
        return jsonify({"response": "❌ Keine Frage erhalten."}), 400

    # Suche in Azure Search
    search_results = search_client.search(question)
    docs = []
    for result in search_results:
        content = result.get("content", "") or result.get("text", "")
        if content:
            docs.append(content)
        if len(docs) >= 3:
            break

    context = "\n\n".join(docs) if docs else "Keine relevanten Inhalte gefunden."

    # GPT-4o Antwort generieren
    response = client.chat.completions.create(
        model=AZURE_OPENAI_DEPLOYMENT,
        messages=[
            {"role": "system", "content": "Beantworte Fragen nur basierend auf dem folgenden Kontext:"},
            {"role": "user", "content": f"Kontext:\n{context}\n\nFrage:\n{question}"}
        ],
        temperature=0.4
    )

    answer = response.choices[0].message.content
    return jsonify({"response": answer})
