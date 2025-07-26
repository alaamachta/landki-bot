# app.py (NEUER AUFBAU – STABIL)
# ----------------------------------
# Funktionen: /chat-Endpoint, Logging, Vorbereitung für Outlook/SQL/Email

from flask import Flask, request, jsonify
from flask_cors import CORS
import logging
import os
import pytz
from datetime import datetime

# === Flask Setup ===
app = Flask(__name__)
CORS(app)

# === Logging Setup ===
log_level = os.environ.get("WEBSITE_LOGGING_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
)
timezone = pytz.timezone("Europe/Berlin")
logging.info("[INIT] App gestartet – Logging Level: %s", log_level)

# === Beispiel-Endpoint /chat ===
@app.route("/chat", methods=["POST"])
def chat():
    try:
        data = request.get_json()
        user_message = data.get("message", "")

        logging.info("[CHAT] Eingabe: %s", user_message)

        if "termin" in user_message.lower():
            reply = "Super, ich helfe dir gerne bei der Terminbuchung! ✨"
        else:
            reply = "Ich bin dein smarter Assistent – wie kann ich helfen?"

        return jsonify({"reply": reply})

    except Exception as e:
        logging.exception("[ERROR] Fehler im /chat Endpoint")
        return jsonify({"error": str(e)}), 500

# === Healthcheck (optional) ===
@app.route("/health", methods=["GET"])
def health():
    return "OK", 200

# === Local Debug (optional) ===
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
