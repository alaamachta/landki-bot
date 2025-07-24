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
CORS(app)  # Cross-Origin erlauben

# Zusätzliche CORS-Header setzen (für sichere Browser)
@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    return response

# Umgebungsvariablen lesen
AZURE_API_KEY = os.getenv("AZURE_OPENAI_KEY")
AZURE_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")

# Log Umgebungsvariablen und Startstatus
logging.info("💡 Starte LandKI Bot mit GPT-Modell: %s", AZURE_DEPLOYMENT)
if not AZURE_API_KEY:
    logging.warning("⚠️ AZURE_OPENAI_KEY fehlt!")
if not AZURE_ENDPOINT:
    logging.warning("⚠️ AZURE_OPENAI_ENDPOINT fehlt!")
if not AZURE_DEPLOYMENT:
    logging.warning("⚠️ AZURE_OPENAI_DEPLOYMENT fehlt – nutze Default: 'gpt-4o'")


# OpenAI Konfiguration
openai.api_key = AZURE_API_KEY
openai.api_base = AZURE_ENDPOINT
openai.api_type = "azure"
openai.api_version = "2024-07-01-preview"

# Statusprüfung
@app.route("/status", methods=["GET"])
def status():
    return jsonify({"openai": True, "search": True, "status": "ready"})

# Chat-Route
@app.route("/chat", methods=["POST"])
def chat():
    try:
        data = request.get_json()
        message = data.get("message", "")
        logging.info(f"Empfangene Nachricht: {message}")

        if not message:
            return jsonify({"reply": "⚠️ Leere Nachricht erhalten."}), 400

        # Anfrage an GPT
        response = openai.ChatCompletion.create(
            engine=AZURE_DEPLOYMENT,
            messages=[
                {"role": "system", "content": "Du bist ein hilfreicher KI-Assistent."},
                {"role": "user", "content": message}
            ],
            temperature=0.5,  # Natürlich klingend
            max_tokens=800
        )

        reply = response.choices[0].message["content"]
        logging.info(f"Antwort: {reply}")
        return jsonify({"reply": reply})

    except Exception as e:
        logging.error(f"Fehler in /chat: {str(e)}")
        return jsonify({"reply": "❌ Interner Fehler beim Verarbeiten deiner Anfrage."}), 500

# Lokaler Start (nicht relevant bei Azure)
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
