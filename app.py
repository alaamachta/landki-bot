from flask import Flask, request, jsonify, session, redirect, url_for
from flask_cors import CORS
import os
import logging
import markdown2
import traceback
from openai import AzureOpenAI

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "secret")
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)  # wichtig für Frontend-Zugriff

# Logging
logging.basicConfig(level=os.environ.get("WEBSITE_LOGGING_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

# Azure OpenAI Client Setup
AZURE_OPENAI_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_KEY = os.environ.get("AZURE_OPENAI_KEY")
AZURE_OPENAI_DEPLOYMENT = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
AZURE_SEARCH_ENDPOINT = os.environ.get("AZURE_SEARCH_ENDPOINT")
AZURE_SEARCH_KEY = os.environ.get("AZURE_SEARCH_KEY")
AZURE_SEARCH_INDEX = os.environ.get("AZURE_SEARCH_INDEX")

client = AzureOpenAI(
    azure_endpoint=AZURE_OPENAI_ENDPOINT,
    api_key=AZURE_OPENAI_KEY,
    api_version="2024-05-01-preview"
)

# Dummy Searchfunktion (kann später durch echte ersetzt werden)
def search_azure(query):
    logger.info(f"🔍 Suche Kontext für: {query}")
    return ""  # oder: Rückgabe aus echter Azure Cognitive Search

@app.route("/chat", methods=["POST"])
def chat():
    try:
        user_input = request.json.get("message", "").strip()
        logger.info(f"👤 Frage: {user_input}")

        # Fallback bei einfachen Begrüßungen
        if user_input.lower() in ["hallo", "hi", "guten tag", "hey"]:
            antwort = "Hallo! Ich bin dein digitaler Assistent. Wie kann ich helfen?"
            return jsonify({
                "response": antwort,
                "reply_html": markdown2.markdown(antwort)
            })

        # Azure Search
        context = search_azure(user_input)
        if not context:
            context = "Kein Kontext gefunden."

        # GPT-Antwort mit Kontext
        prompt = f"Nutze diesen Kontext zur Beantwortung:\n{context}\n\nFrage: {user_input}\nAntwort:"
        response = client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2
        )

        answer = response.choices[0].message.content
        logger.info(f"✅ GPT-Antwort: {answer[:100]}...")
        return jsonify({
            "response": answer,
            "reply_html": markdown2.markdown(answer)
        })

    except Exception:
        logger.error("❌ Fehler im Chat:")
        logger.error(traceback.format_exc())
        return jsonify({"error": "Fehler beim Chat"}), 500

if __name__ == "__main__":
    app.run(debug=True)
