from flask import Flask, request, jsonify
from openai import AzureOpenAI
from azure.search.documents import SearchClient
import os

app = Flask(__name__)

# 🔐 Umgebungsvariablen laden
AZURE_SEARCH_ENDPOINT = os.environ["AZURE_SEARCH_ENDPOINT"]
AZURE_SEARCH_KEY = os.environ["AZURE_SEARCH_KEY"]
AZURE_SEARCH_INDEX = os.environ["AZURE_SEARCH_INDEX"]

AZURE_OPENAI_ENDPOINT = os.environ["OPENAI_API_BASE"]
AZURE_OPENAI_KEY = os.environ["OPENAI_API_KEY"]
AZURE_OPENAI_VERSION = os.environ["OPENAI_API_VERSION"]
AZURE_OPENAI_DEPLOYMENT = os.environ["AZURE_OPENAI_DEPLOYMENT"]

# 🔎 SearchClient für Azure Cognitive Search
search_client = SearchClient(
    endpoint=AZURE_SEARCH_ENDPOINT,
    index_name=AZURE_SEARCH_INDEX,
    credential=AZURE_SEARCH_KEY
)

# 🤖 Azure OpenAI Client
openai_client = AzureOpenAI(
    api_key=AZURE_OPENAI_KEY,
    api_version=AZURE_OPENAI_VERSION,
    azure_endpoint=AZURE_OPENAI_ENDPOINT
)

@app.route("/")
def home():
    return "✅ LandKI Bot läuft erfolgreich!"

@app.route("/chat", methods=["POST"])
def chat():
    user_question = request.json.get("question", "")

    # 🔍 Suche relevante Dokumente in Azure Search
    results = search_client.search(search_text=user_question)
    content = "\n".join([doc["content"] for doc in results if "content" in doc])

    # 🧠 Anfrage an GPT-4o mit RAG-Prompt
    messages = [
        {"role": "system", "content": "Du bist ein hilfreicher Assistent für IT-Land. Beantworte Fragen nur basierend auf folgenden Dokumenten:"},
        {"role": "user", "content": f"Dokumente:\n{content}\n\nFrage: {user_question}"}
    ]

    completion = openai_client.chat.completions.create(
        model=AZURE_OPENAI_DEPLOYMENT,
        messages=messages,
        temperature=0.3
    )

    answer = completion.choices[0].message.content
    return jsonify({"answer": answer})

# Hinweis: Azure verwendet gunicorn automatisch. Kein main-Block notwendig.
