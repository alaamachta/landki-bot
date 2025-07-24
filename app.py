from flask import Flask, request, jsonify, session
from flask_cors import CORS
import openai
import os
import logging
from datetime import datetime
import pytz

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "debug-secret")  # für Sessions
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

# Logging
logging.basicConfig(
    level=os.environ.get("WEBSITE_LOGGING_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# GPT-Setup
openai.api_key = os.environ.get("AZURE_OPENAI_KEY")
openai.api_base = os.environ.get("AZURE_OPENAI_ENDPOINT")
openai.api_type = "azure"
openai.api_version = "2024-02-15-preview"
model = os.environ.get("AZURE_OPENAI_MODEL", "gpt-4o")

# Szenenlogik
fragen_reihenfolge = ["name", "geburtsdatum", "telefon", "email", "symptome"]
fragen_prompts = {
    "name": "Wie lautet dein voller Name?",
    "geburtsdatum": "Wie ist dein Geburtsdatum? (z.\u202fB. 24.07.1990)",
    "telefon": "Wie ist deine Telefonnummer?",
    "email": "Wie lautet deine E-Mail-Adresse?",
    "symptome": "Was sind deine Symptome oder dein Anliegen?"
}

@app.route("/ping", methods=["GET"])
def ping():
    return "pong"

@app.route("/chat", methods=["POST"])
def chat():
    user_input = request.json.get("message", "")
    logger.info(f"Eingabe: {user_input}")

    # Falls keine Szene aktiv ist, starten wir mit Hauptauswahl
    if "szenario" not in session:
        if "termin" in user_input.lower():
            session["szenario"] = "termin"
            session["antworten"] = {}
            session["step"] = 0
            frage = fragen_prompts[fragen_reihenfolge[0]]
            return jsonify({"reply": f"📅 Du möchtest einen Termin buchen. {frage}"})
        else:
            return jsonify({"reply": "🧑‍💻 Danke für deine Nachricht. Was möchtest du tun? (z.B. Termin buchen)"})

    # Wenn Szene "termin" aktiv ist, Daten sammeln
    if session.get("szenario") == "termin":
        step = session.get("step", 0)
        aktuelles_feld = fragen_reihenfolge[step]
        session["antworten"][aktuelles_feld] = user_input

        if step + 1 < len(fragen_reihenfolge):
            naechstes_feld = fragen_reihenfolge[step + 1]
            session["step"] = step + 1
            frage = fragen_prompts[naechstes_feld]
            return jsonify({"reply": frage})
        else:
            daten = session["antworten"]
            session.clear()
            zusammenfassung = f"\n\n✅ Deine Angaben:\n- Name: {daten['name']}\n- Geburtsdatum: {daten['geburtsdatum']}\n- Telefon: {daten['telefon']}\n- E-Mail: {daten['email']}\n- Symptome: {daten['symptome']}"
            return jsonify({"reply": f"Danke für alle Angaben! Wir bearbeiten deine Anfrage.{zusammenfassung}"})

    # Fallback
    return jsonify({"reply": "🚫 Fehler im Ablauf. Bitte starte neu."})

if __name__ == "__main__":
    app.run(debug=True, port=8000)
