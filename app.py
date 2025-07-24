# app.py (aktuelle Version mit CORS-Fix und Logging)

from flask import Flask, request, jsonify, session
from flask_cors import CORS
from datetime import datetime
import logging
import os

# GPT / Outlook / SQL / Mail Funktionen (Platzhalter)
from core.assistant import get_gpt_reply
from core.calendar import get_free_time_slots, book_appointment
from core.mail import send_email
from core.database import insert_patient_data

# Zeitzone setzen
os.environ['TZ'] = 'Europe/Berlin'

# Logging vorbereiten
logging_level = os.environ.get("WEBSITE_LOGGING_LEVEL", "DEBUG").upper()
logging.basicConfig(level=getattr(logging, logging_level), format='%(asctime)s %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# Flask App
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "test-secret")
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)  # wichtig für JS

@app.route("/chat", methods=["POST"])
def chat():
    try:
        data = request.get_json()
        user_message = data.get("message", "")

        logger.debug(f"Empfangene Nachricht: {user_message}")

        # GPT-Antwort generieren (z. B. mit Terminvorschlägen, Button-Ausgabe etc.)
        reply = get_gpt_reply(user_message)

        logger.info("Antwort erfolgreich generiert")
        return jsonify({"reply": reply})

    except Exception as e:
        logger.exception("Fehler beim Verarbeiten der Anfrage")
        return jsonify({"reply": "❌ Interner Fehler beim Verarbeiten deiner Anfrage."}), 500

# Testendpunkt für PowerShell
@app.route("/ping", methods=["GET"])
def ping():
    return jsonify({"status": "Bot läuft", "zeit": datetime.now().strftime('%Y-%m-%d %H:%M:%S')})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
