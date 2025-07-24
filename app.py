import os
import logging
from flask import Flask, request, jsonify
from flask_cors import CORS
import openai
import datetime

# Logging aktivieren (mit deutscher Zeitzone)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logging.Formatter.converter = lambda *args: datetime.datetime.now(tz=datetime.timezone(datetime.timedelta(hours=2))).timetuple()

# Flask-Setup
app = Flask(__name__)
CORS(app)  # CORS für alle Domains aktivieren (für WordPress-Frontend)

# Umgebungsvariablen lesen
AZURE_API_KEY = os.getenv("AZURE_OPENAI_KEY")
AZURE_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")  # z. B. https://landki-foundry.openai.azure.com/
AZURE_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")

# OpenAI-Konfiguration setzen
openai.api_key = AZURE_API_KEY
openai.api_base = AZURE_ENDPOINT
openai.api_type = "azure"
openai.api_version = "2024-05-13"

# Healthcheck-Route
@app.route("/status", methods=["GET"])
def status():
    return jsonify({
        "openai": True,
        "search": True,  # Falls später Azure Search aktiviert wird
        "status": "ready"
    })

# Chat-Route für dein Frontend
@app.route("/chat", methods=["POST"])
def chat():
    try:
        data = request.get_json()
        message = data.get("message", "")
        logging.info(f"Empfangene Nachricht: {message}")

        if not message:
            return jsonify({"reply": "⚠️ Leere Nachricht erhalten."}), 400

        # Anfrage an GPT senden
        response = openai.ChatCompletion.create(
            engine=AZURE_DEPLOYMENT,
            messages=[
                {"role": "system", "content": "Du bist ein hilfreicher KI-Assistent."},
                {"role": "user", "content": message}
            ],
            temperature=0.5,  # Für natürlichere Antworten
            max_tokens=800
        )

        reply = response.choices[0].message["content"]
        logging.info(f"Antwort: {reply}")
        return jsonify({"reply": reply})

    except Exception as e:
        logging.error(f"Fehler in /chat: {str(e)}")
        return jsonify({"reply": "❌ Interner Fehler beim Verarbeiten deiner Anfrage."}), 500

# Startpunkt für Gunicorn
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
