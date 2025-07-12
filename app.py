import os
from flask import Flask, request, jsonify
from azure.search.documents import SearchClient
from azure.search.documents.models import VectorQuery
from azure.core.credentials import AzureKeyCredential
import openai

app = Flask(__name__)

@app.route("/", methods=["GET"])
def index():
    return "LandKI Bot läuft!"

@app.route("/api/message", methods=["POST"])
def chat():
    user_input = request.json.get("message")

    embed = openai.Embedding.create(
        input=user_input,
        model="text-embedding-3-small"
    )
    vector = embed["data"][0]["embedding"]

    search_client = SearchClient(
        endpoint=os.getenv("AZURE_SEARCH_ENDPOINT"),
        index_name="index_itland_webcrawler",
        credential=AzureKeyCredential(os.getenv("AZURE_SEARCH_KEY"))
    )

    results = search_client.search(
        search_text=None,
        vector_queries=[VectorQuery(vector=vector, k=3, fields="contentVector")]
    )

    context = "\n".join([doc["content"] for doc in results])

    messages = [
        {"role": "system", "content": "Antworte basierend auf folgendem Kontext:"},
        {"role": "user", "content": f"{context}\n\nFrage: {user_input}"}
    ]

    response = openai.ChatCompletion.create(
        engine="gpt-4o",
        messages=messages,
        temperature=0.3
    )

    return jsonify({"response": response.choices[0].message["content"]})