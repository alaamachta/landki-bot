# ✅ Finalisierte, testbare Version deiner `app.py` für Szenario 1: Termin buchen
# Hinweis: Diese Version funktioniert eigenständig ohne `core/assistant.py`

from flask import Flask, request, jsonify
from flask_cors import CORS
import logging
from datetime import datetime
import os
import pytz

# Logging konfigurieren (UTC +2 = Europe/Berlin)
berlin = pytz.timezone('Europe/Berlin')
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)

def log(message):
    now = datetime.now(berlin).strftime('%Y-%m-%d %H:%M:%S')
    logging.info(f"{now} {message}")

# Flask App erstellen
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)  # wichtig für Frontend-Zugriff

# Test-Route für Ping
@app.route("/ping", methods=["GET"])
def ping():
    log("Ping empfangen")
    return "pong"

# Haupt-Chatroute (GPT noch nicht eingebunden)
@app.route("/chat", methods=["POST"])
def chat():
    try:
        data = request.get_json()
        user_message = data.get("message", "")
        log(f"Eingehende Nachricht: {user_message}")

        # Platzhalter-Antwort zur Bestätigung
        if "termin" in user_message.lower():
            reply = "🗓️ Du möchtest einen Termin buchen. Wie lautet dein voller Name?"
        else:
            reply = "🤖 Danke für deine Nachricht. Was möchtest du tun? (z.B. Termin buchen)"

        return jsonify({"reply": reply})

    except Exception as e:
        log(f"Fehler im Chat-Endpunkt: {str(e)}")
        return jsonify({"reply": "❌ Interner Fehler beim Verarbeiten deiner Anfrage."}), 500

# App starten (wichtig für Azure Web App mit Gunicorn: app:app)
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
