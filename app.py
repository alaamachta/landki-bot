import os
import logging
from datetime import datetime
from flask import Flask, request, jsonify
from openai import AzureOpenAI
import pytz
from flask_cors import CORS

# Flask Setup
app = Flask(__name__)
# Aktiviere CORS für alle Domains – für Produktion kannst du das später auf deine Domain einschränken
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

# Logging Setup (deutsche Zeitzone)
berlin_tz = pytz.timezone("Europe/Berlin")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logging.Formatter.converter = lambda *args: datetime.now(tz=berlin_tz).timetuple()

# Azure OpenAI Client (Foundry)
client = AzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),  # oder AZURE_OPENAI_KEY, beide gehen
    api_version=os.getenv("OPENAI_API_VERSION", "2024-07-01-preview"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT")
)

# GPT-Konfiguration
MODEL = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")

@app.route("/")
def health_check():
    return jsonify({"openai": True, "status": "ready"})

@app.route("/chat", methods=["POST"])
def chat():
    try:
        data = request.get_json()
        user_message = data.get("message", "").strip()

        if not user_message:
            return jsonify({"reply": "Bitte gib eine Nachricht ein."}), 400

        logging.info(f"Empfangen: {user_message}")

        # GPT-Aufruf
        response = client.chat.completions.create(
            model=MODEL,  # Foundry erwartet model, nicht deployment_id!
            messages=[{"role": "user", "content": user_message}],
            temperature=0.4,  # Empfohlen: 0.2–0.7 für realistische Antworten
        )

        gpt_reply = response.choices[0].message.content.strip()
        logging.info(f"Antwort gesendet: {gpt_reply}")

        return jsonify({"reply": gpt_reply})

    except Exception as e:
        logging.error(f"Fehler im Chat-Endpunkt: {str(e)}")
        return jsonify({"reply": "❌ Interner Fehler beim Verarbeiten deiner Anfrage."}), 500

# App starten (nur lokal relevant)
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
