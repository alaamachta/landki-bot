import os
from flask import Flask, request, jsonify
from openai import AzureOpenAI
from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential

app = Flask(__name__)

# ENV-Vars (in Azure App Service setzen)
AZURE_SEARCH_ENDPOINT = os.environ["AZURE_SEARCH_ENDPOINT"]
AZURE_SEARCH_KEY = os.environ["AZURE_SEARCH_KEY"]
AZURE_SEARCH_INDEX = os.environ["AZURE_SEARCH_INDEX"]
AZURE_OPENAI_ENDPOINT = os.environ["AZURE_OPENAI_ENDPOINT"]
AZURE_OPENAI_KEY = os.environ["AZURE_OPENAI_KEY"]
AZURE_OPENAI_DEPLOYMENT = os.environ["AZURE_OPENAI_DEPLOYMENT"]

# Clients
search_client = SearchClient(
    endpoint=AZURE_SEARCH_ENDPOINT,
    index_name=AZURE_SEARCH_INDEX,
    credential=AzureKeyCredential(AZURE_SEARCH_KEY)
)

openai_client = AzureOpenAI(
    api_key=AZURE_OPENAI_KEY,
    api_version="2024-05-01-preview",
    azure_endpoint=AZURE_OPENAI_ENDPOINT
)

@app.route("/", methods=["GET"])
def home():
    return "✅ LandKI Bot läuft mit RAG!"

@app.route("/chat", methods=["POST"])
def chat():
    user_input = request.json.get("message", "")

    # Schritt 1: RAG - Suche
    search_results = search_client.search(user_input, top=5)
    context = "\n".join([doc["content"] for doc in search_results])

    # Schritt 2: GPT-4o antwortet mit Kontext
    response = openai_client.chat.completions.create(
        model=AZURE_OPENAI_DEPLOYMENT,
        messages=[
            {"role": "system", "content": "Antworte nur auf Basis der Website-Inhalte:"},
            {"role": "user", "content": f"{context}\n\nFrage: {user_input}"}
        ],
        temperature=0.2
    )

    return jsonify({
        "response": response.choices[0].message.content
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
