import os
import logging
from flask import Flask, request, jsonify
from flask_cors import CORS
import openai
import datetime

# Logging mit deutscher Zeitzone (UTC+2)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logging.Formatter.converter = lambda *args: datetime.datetime.now(
    tz=datetime.timezone(datetime.timedelta(hours=2))
).timetuple()

# Flask-Setup
app = Flask(__name__)
CORS(app)

@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    return response

# Umgebungsvariablen lesen (mit Fallback)
AZURE_API_KEY = os.getenv("AZURE_OPENAI_KEY") or os.getenv("AZURE_OPENAI_API_KEY")
AZURE_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
AZURE_VERSION = os.getenv("OPENAI_API_VERSION", "2024-07-01-preview")

# Prüfung und Logging
if not AZURE_API_KEY or not AZURE_ENDPOINT:
    logging.error("❌ AZURE API KEY oder ENDPOINT fehlt! Bitte Umgebungsvariablen prüfen.")
else:
    logging.info("✅ Chatbot wurde gestartet mit GPT-Modell: %s", AZURE_DEPLOYMENT)
    logging.info("🌐 API Endpoint: %s", AZURE_ENDPOINT)
    logging.info("📅 API Version: %s", AZURE_VERSION)

# OpenAI Konfiguration
openai.api_key = AZURE_API_KEY
openai.api_base = AZURE_ENDPOINT
openai.api_type = "azure"
openai.api_version = AZURE_VERSION

@app.route("/status", methods=["GET"])
def status():
    return jsonify({"openai": bool(AZURE_API_KEY), "status": "ready"})

@app.route("/chat", methods=["POST"])
def chat():
    try:
        data = request.get_json()
        message = data.get("message", "")
        logging.info(f"📩 Eingehende Nachricht: {message}")

        if not message:
            return jsonify({"reply": "⚠️ Leere Nachricht erhalten."}), 400

        response = openai.ChatCompletion.create(
            engine=AZURE_DEPLOYMENT,
            messages=[
                {"role": "system", "content": "Du bist ein hilfreicher KI-Assistent."},
                {"role": "user", "content": message}
            ],
            temperature=0.5,
            max_tokens=800
        )

        reply = response.choices[0].message["content"]
        logging.info(f"🤖 Antwort von GPT: {reply}")
        return jsonify({"reply": reply})

    except Exception as e:
        logging.error(f"❌ Fehler in /chat: {str(e)}")
        return jsonify({"reply": "❌ Interner Fehler beim Verarbeiten deiner Anfrage."}), 500

# Lokaler Start (nicht in Azure verwendet)
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
