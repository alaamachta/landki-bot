# Version: v1.0 – Minimalversion nur mit GPT
from flask import Flask, request, jsonify
from flask_cors import CORS
import logging
import uuid
import os
from openai import AzureOpenAI, OpenAIError

# === Konfiguration ===
AZURE_OPENAI_KEY = os.environ.get("AZURE_OPENAI_KEY")
AZURE_OPENAI_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_DEPLOYMENT = os.environ.get("AZURE_OPENAI_DEPLOYMENT")  # z. B. "gpt-4o"
AZURE_OPENAI_API_VERSION = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21")  # empfohlen für GPT-4o

# === Flask App Setup ===
app = Flask(__name__)
CORS(app)

# === Logging Setup ===
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("landki")

# === Ping Test ===
@app.route("/ping", methods=["GET"])
def ping():
    return "pong"

# === GPT Chat Endpoint ===
@app.route("/chat", methods=["POST"])
def chat():
    try:
        data = request.get_json()
        user_input = data.get("message", "").strip()
        if not user_input:
            return jsonify({"error": "Leere Eingabe."}), 400

        session_id = str(uuid.uuid4())
        logger.info(f"[{session_id}] Neue Anfrage: {user_input}")

        client = AzureOpenAI(
            api_key=AZURE_OPENAI_KEY,
            api_version=AZURE_OPENAI_API_VERSION,
            azure_endpoint=AZURE_OPENAI_ENDPOINT
        )

        response = client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,
            temperature=0.2,
            messages=[
                {"role": "system", "content": "Du bist ein freundlicher deutschsprachiger Assistent."},
                {"role": "user", "content": user_input}
            ]
        )

        reply = response.choices[0].message.content.strip()
        logger.info(f"[{session_id}] Antwort: {reply}")
        return jsonify({"response": reply})

    except OpenAIError as oe:
        logger.error(f"OpenAI-Fehler: {oe}")
        return jsonify({"error": f"OpenAI Error: {str(oe)}"}), 500
    except Exception as e:
        logger.error(f"Unbekannter Fehler: {e}")
        return jsonify({"error": f"Serverfehler: {str(e)}"}), 500
