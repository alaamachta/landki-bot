from flask import Flask, request, jsonify, session
from flask_cors import CORS
import logging
from datetime import datetime
import pytz
import os

# Core-Module importieren
from core.assistant import get_gpt_reply

# Flask App initialisieren
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)
app.secret_key = os.environ.get("SECRET_KEY", "fallback_secret")

# Logging aktivieren
log_level = os.environ.get("WEBSITE_LOGGING_LEVEL", "INFO").upper()
logging.basicConfig(level=log_level)
logger = logging.getLogger(__name__)
logger.info("App gestartet am %s", datetime.now(pytz.timezone("Europe/Berlin")))

@app.route("/ping", methods=["GET"])
def ping():
    logger.debug("Ping empfangen")
    return jsonify({"status": "ok", "timestamp": datetime.now(pytz.timezone("Europe/Berlin")).isoformat()})

@app.route("/chat", methods=["POST"])
def chat():
    try:
        data = request.get_json()
        message = data.get("message", "")
        logger.debug("Eingehende Nachricht: %s", message)

        if not message:
            return jsonify({"reply": "Bitte gib eine Nachricht ein."}), 400

        reply = get_gpt_reply(message)
        return jsonify({"reply": reply})
    
    except Exception as e:
        logger.exception("Fehler in /chat")
        return jsonify({"reply": "❌ Interner Fehler beim Verarbeiten deiner Anfrage.", "error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
