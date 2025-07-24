# ✅ Vollständige und stabile app.py für LandKI Bot (Stand 2025-07-24)

from flask import Flask, request, jsonify, session
from flask_cors import CORS
import openai
import logging
import os
import time
from datetime import datetime
import pytz

# Flask App starten
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)  # Wichtig für CORS Fehler
app.secret_key = os.getenv("FLASK_SECRET_KEY", "test-secret")  # Session Key

# Logging konfigurieren (mit Zeitzone Europe/Berlin)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
berlin_tz = pytz.timezone("Europe/Berlin")

# Azure OpenAI Konfiguration
openai.api_type = "azure"
openai.api_base = os.getenv("AZURE_OPENAI_ENDPOINT")  # z. B. https://NAME.openai.azure.com
openai.api_version = os.getenv("AZURE_OPENAI_VERSION", "2024-07-01-preview")
openai.api_key = os.getenv("AZURE_OPENAI_API_KEY")

# Modellname in Azure (Deployment-Name!)
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")

# Systemnachricht für GPT
SYSTEM_PROMPT = """
Du bist ein professioneller deutscher Terminassistent für eine Praxis oder ein Büro.
Sprich immer Höflich, verständlich und in normalem Alltagsdeutsch.
Wenn der Nutzer nach einem Termin fragt oder ein Datum/Vorschlag nennt, dann analysiere die Zeitangabe und reagiere mit einer passenden Antwort.
Wenn Name, Geburtstag oder Symptom gefragt werden, leite durch den Prozess.
Sprich immer auf Deutsch. Wenn du ein Datum siehst, formatiere es klar.
"""

# POST-Endpunkt für Chat
@app.route("/chat", methods=["POST"])
def chat():
    try:
        data = request.get_json()
        user_message = data.get("message", "")

        if not user_message:
            return jsonify({"reply": "❌ Keine Nachricht erhalten."}), 400

        logging.info(f"Eingabe vom Nutzer: {user_message}")

        # GPT-Aufruf vorbereiten
        response = openai.ChatCompletion.create(
            engine=AZURE_OPENAI_DEPLOYMENT,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            temperature=0.3,  # Für konsistente Antworten
            max_tokens=800,
        )

        reply = response.choices[0].message.content.strip()
        logging.info(f"Antwort von GPT: {reply}")
        return jsonify({"reply": reply})

    except Exception as e:
        logging.exception("Fehler im /chat-Endpunkt")
        return jsonify({"reply": "❌ Interner Fehler beim Verarbeiten deiner Anfrage."}), 500

# Startpunkt für Tests
if __name__ == "__main__":
    app.run(debug=True, port=5000)
