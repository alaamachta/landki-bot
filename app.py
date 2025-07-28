# app.py – Version v1.0010 – Schleifenvermeidung + smarter Prompt + Terminprüfung

from flask import Flask, request, jsonify, session
from flask_cors import CORS
import openai
import logging
import os
from datetime import datetime, timedelta
import pytz
import smtplib
import pyodbc
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# === Flask Setup ===
app = Flask(__name__)
CORS(app)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "default_secret")

# === Logging ===
LOG_LEVEL = os.environ.get("WEBSITE_LOGGING_LEVEL", "INFO")
logging.basicConfig(
    level=LOG_LEVEL,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger()

# === OpenAI Setup ===
openai.api_type = "azure"
openai.api_base = os.environ.get("AZURE_OPENAI_ENDPOINT")
openai.api_key = os.environ.get("AZURE_OPENAI_KEY")
openai.api_version = "2024-10-21"

GPT_DEPLOYMENT = os.environ.get("AZURE_GPT_DEPLOYMENT", "gpt-4o")

# === Zeitzone ===
tz = pytz.timezone("Europe/Berlin")

# === Terminverlauf speichern ===
conversation_memory = {}

# === Helferfunktionen ===
def get_conversation_state(user_id):
    return conversation_memory.setdefault(user_id, {})

def is_complete(state):
    required_fields = ["first_name", "last_name", "birthday", "email", "preferred_time"]
    return all(state.get(field) for field in required_fields)

def build_prompt(state):
    known_parts = []
    if state.get("first_name"):
        known_parts.append(f"Vorname: {state['first_name']}")
    if state.get("last_name"):
        known_parts.append(f"Nachname: {state['last_name']}")
    if state.get("birthday"):
        known_parts.append(f"Geburtstag: {state['birthday']}")
    if state.get("email"):
        known_parts.append(f"E-Mail: {state['email']}")
    if state.get("preferred_time"):
        known_parts.append(f"Wunschtermin: {state['preferred_time']}")

    known_text = ", ".join(known_parts)
    return f"""
    Du bist ein digitaler Praxisassistent.
    Deine Aufgabe ist es, einen Termin zu buchen.
    Der Nutzer wird nach und nach Informationen geben.
    Prüfe, welche Angaben bereits gemacht wurden.
    Stelle **keine Fragen doppelt**.
    Wenn alle Daten vorhanden sind, bestätige die Buchung.
    
    Benötigte Daten:
    - Vorname
    - Nachname
    - Geburtstag (z. B. 1990-06-04)
    - E-Mail-Adresse
    - Wunschtermin im Format YYYY-MM-DDTHH:MM (z. B. 2025-07-30T15:00)

    Wenn Nutzer sagt z. B. "Ich heiße Alaa Mashta" oder "Ich bin Alaa Mashta, 1990-04-06", dann erkenne alle Daten automatisch.
    Wenn ein Wunschtermin genannt wird, prüfe, ob er realistisch ist (z. B. nicht in der Vergangenheit). Schlage bei Bedarf Alternativen vor.
    Wenn bereits alle Angaben gemacht wurden, fasse sie zusammen und schreibe "Ihre Buchung wurde erfolgreich erfasst."
    
    Aktueller Stand: {known_text}
    """

@app.route("/chat", methods=["POST"])
def chat():
    user_input = request.get_json().get("message")
    user_id = request.remote_addr  # Alternativ per Session/User-ID

    state = get_conversation_state(user_id)

    # GPT-Aufruf
    system_prompt = build_prompt(state)

    try:
        response = openai.ChatCompletion.create(
            engine=GPT_DEPLOYMENT,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input}
            ],
            temperature=0.2
        )
        answer = response.choices[0].message["content"]

        # Extraktion (vereinfachtes Beispiel)
        if "@" in user_input and "." in user_input:
            state["email"] = user_input.strip()
        if "T" in user_input:
            state["preferred_time"] = user_input.strip()
        if any(y in user_input for y in ["199", "200"]):
            state["birthday"] = user_input.strip()
        if len(user_input.split()) == 2:
            first, last = user_input.split()
            state["first_name"] = first
            state["last_name"] = last

        logger.info(f"Conversation state: {state}")

        return jsonify({"response": answer})

    except Exception as e:
        logger.error(f"Fehler bei ChatCompletion: {e}")
        return jsonify({"error": "Interner Fehler"}), 500

if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=8000)
