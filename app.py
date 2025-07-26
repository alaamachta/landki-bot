# app.py – LandKI Bot mit GPT, Fehler-Logging & /chat Endpoint

from flask import Flask, request, jsonify
import openai
import os
import logging
from flask_cors import CORS
from datetime import datetime
import pytz
from openai.error import OpenAIError

# === Flask App Setup ===
app = Flask(__name__)
CORS(app)

# === Logging Setup ===
LOG_LEVEL = os.environ.get("WEBSITE_LOGGING_LEVEL", "DEBUG")
logging.basicConfig(
    level=LOG_LEVEL,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler()]
)
tz = pytz.timezone("Europe/Berlin")
logging.Formatter.converter = lambda *args: datetime.now(tz).timetuple()

# === GPT Setup ===
openai.api_type = "azure"
openai.api_version = "2024-02-15-preview"
openai.api_base = os.environ.get("AZURE_OPENAI_ENDPOINT")
openai.api_key = os.environ.get("AZURE_OPENAI_KEY")
MODEL_NAME = os.environ.get("AZURE_OPENAI_MODEL", "gpt-4o")

# === /chat Endpoint ===
@app.route("/chat", methods=["POST"])
def chat():
    try:
        logging.info("POST /chat aufgerufen")

        # Anfrage prüfen
        data = request.get_json()
        if not data or "message" not in data:
            logging.warning("Ungültiger Request Body: %s", data)
            return jsonify({"error": "Fehlender Parameter: 'message'"}), 400

        message = data["message"]
        logging.debug(f"Eingabe: {message}")

        # GPT-Request
        response = openai.ChatCompletion.create(
            engine=MODEL_NAME,
            temperature=0.3,
            max_tokens=1000,
            messages=[
                {"role": "system", "content": "Du bist der hilfreiche digitale Assistent von LandKI."},
                {"role": "user", "content": message}
            ]
        )

        gpt_answer = response.choices[0].message["content"]
        logging.info(f"Antwort: {gpt_answer}")
        return jsonify({"response": gpt_answer})

    except OpenAIError as e:
        logging.error("OpenAI API Fehler: %s", e)
        return jsonify({"error": "Fehler bei der Anfrage an GPT."}), 500

    except Exception as e:
        logging.exception("Unerwarteter Fehler:")
        return jsonify({"error": "Fehler beim Verarbeiten der Anfrage."}), 500

# === Healthcheck ===
@app.route("/", methods=["GET"])
def index():
    return "LandKI Bot ist online 🟢"

# === Lokaler Startpunkt (für Debugging) ===
if __name__ == "__main__":
    app.run(debug=True, port=8000)
