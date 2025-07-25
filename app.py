from flask import Flask, request, jsonify
from flask_cors import CORS
import openai
import logging
import os
from datetime import datetime
import pytz

app = Flask(__name__)
CORS(app)

# Setze dein Azure OpenAI API-Schlüssel und Endpunkt hier
openai.api_type = "azure"
openai.api_base = os.environ.get("AZURE_OPENAI_ENDPOINT")
openai.api_key = os.environ.get("AZURE_OPENAI_KEY")
openai.api_version = "2024-05-13"

de_timezone = pytz.timezone("Europe/Berlin")

# Logging-Konfiguration
logging.basicConfig(
    level=os.getenv("WEBSITE_LOGGING_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

@app.route("/chat", methods=["POST"])
def chat():
    try:
        user_input = request.json.get("message", "")
        logger.info(f"Empfangene Nachricht: {user_input}")

        if not user_input:
            return jsonify({"reply": "Fehlende Eingabe.", "reply_html": "<p>Bitte gib eine Nachricht ein.</p>"})

        system_prompt = (
            "Du bist der digitale Terminassistent von LandKI."
            " Begrüße den Nutzer freundlich und hilf ihm, einen Termin zu buchen."
            " Wenn der Nutzer allgemeine Fragen stellt, gib kurze, neutrale Antworten."
            " Antworte immer auf Deutsch und im HTML-Format."
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input},
        ]

        response = openai.ChatCompletion.create(
            engine="gpt-4o",  # GPT-4o Modell
            messages=messages,
            temperature=0.3,  # Klar, sachlich
            max_tokens=700,
            top_p=1,
            frequency_penalty=0,
            presence_penalty=0
        )

        reply = response.choices[0].message.content.strip()
        logger.info(f"Antwort generiert: {reply}")

        return jsonify({
            "reply": strip_html(reply),
            "reply_html": reply
        })

    except Exception as e:
        logger.exception("Fehler beim Verarbeiten der Nachricht")
        return jsonify({"reply": "Fehler beim Verarbeiten.", "reply_html": "<p>❌ Interner Fehler. Bitte versuchen Sie es später erneut.</p>"})

def strip_html(text):
    # Fallback, falls HTML-Text für einfache Anzeige benötigt wird
    import re
    return re.sub('<[^<]+?>', '', text)

@app.route("/")
def index():
    return "LandKI Bot API ist online."

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8000)
