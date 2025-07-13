from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import openai
from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential

app = Flask(__name__)
CORS(app)

# 🔐 Konfiguration aus Umgebungsvariablen
AZURE_SEARCH_ENDPOINT = os.getenv("AZURE_SEARCH_ENDPOINT")
AZURE_SEARCH_KEY = os.getenv("AZURE_SEARCH_KEY")
AZURE_SEARCH_INDEX = os.getenv("AZURE_SEARCH_INDEX")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_KEY")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")

# Setup Clients
search_client = SearchClient(
    endpoint=AZURE_SEARCH_ENDPOINT,
    index_name=AZURE_SEARCH_INDEX,
    credential=AzureKeyCredential(AZURE_SEARCH_KEY)
)

openai.api_type = "azure"
openai.api_key = AZURE_OPENAI_KEY
openai.api_base = AZURE_OPENAI_ENDPOINT
openai.api_version = "2024-05-01-preview"

@app.route("/")
def home():
    return "✅ LandKI Bot mit GPT-4o & Azure Search aktiv!"

@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json()
    question = data.get("message")

    # Suche relevante Dokumente in Azure Search
    search_results = search_client.search(question)
    docs = []
    for result in search_results:
        content = result.get("content", "") or result.get("text", "")
        if content:
            docs.append(content)
        if len(docs) >= 3:
            break

    context = "\n\n".join(docs) if docs else "Keine passenden Informationen gefunden."

    # GPT-4o Antwort basierend auf Kontext
    response = openai.ChatCompletion.create(
        engine=AZURE_OPENAI_DEPLOYMENT,
        messages=[
            {"role": "system", "content": "Beantworte Fragen nur basierend auf folgendem Kontext:"},
            {"role": "user", "content": f"Kontext:\n{context}\n\nFrage:\n{question}"}
        ],
        temperature=0.4
    )

    answer = response.choices[0].message["content"]
    return jsonify({"response": answer})
