# app.py – LandKI-Terminassistent mit Outlook + SQL + E-Mail-Versand – Version v1.0008

from flask import Flask, request, jsonify, session
from openai import AzureOpenAI
import os
import logging
from flask_cors import CORS
from datetime import datetime, timedelta
import pytz
import pyodbc
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import requests

# === Flask Setup ===
app = Flask(__name__)
CORS(app)
app.secret_key = os.environ.get("FLASK_SECRET", "supersecret")

# === Logging Setup ===
LOG_LEVEL = os.environ.get("WEBSITE_LOGGING_LEVEL", "INFO")
logging.basicConfig(level=LOG_LEVEL, format='%(asctime)s [%(levelname)s] %(message)s')

# === Konfiguration ===
TZ = pytz.timezone("Europe/Berlin")
SQL_SERVER = os.environ.get("SQL_SERVER")
SQL_DB = os.environ.get("SQL_DATABASE")
SQL_USER = os.environ.get("SQL_USERNAME")
SQL_PASSWORD = os.environ.get("SQL_PASSWORD")
SMTP_SENDER = os.environ.get("EMAIL_SENDER")
SMTP_RECIPIENT = "info@landki.com"

# === Initialzustand ===
required_fields = ["first_name", "last_name", "birthday", "email", "selected_time"]

# === GPT-Chat Endpoint mit memory_context ===
@app.route("/chat", methods=["POST"])
def chat():
    try:
        user_input = request.get_json()["message"]
        session.setdefault("conversation_state", {})
        state = session["conversation_state"]

        # Aktuellen Fortschritt prüfen
        missing = [field for field in required_fields if field not in state]

        # Wenn alle Daten da, buche automatisch
        if not missing:
            return jsonify({"response": f"Alle Daten sind vorhanden. Möchten Sie den Termin am {state['selected_time']} buchen?"})

        # GPT vorbereiten
        context = "\n".join([f"{k}: {v}" for k, v in state.items()])

        system_prompt = f"""
Du bist ein professioneller, klarer Terminassistent einer Firma. Sammle folgende Daten:
1. Vorname
2. Nachname
3. Geburtstag (JJJJ-MM-TT)
4. E-Mail
5. Wunschtermin im Format 2025-07-28T14:00

Wenn ein Feld fehlt, frage gezielt danach. Wenn alle Felder vorhanden sind, beende die Eingabe mit einem Hinweis zur Buchung. Bereits bekannte Daten:
{context}
"""

        client = AzureOpenAI(
            api_key=os.environ["AZURE_OPENAI_KEY"],
            api_version="2024-10-21",
            azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"]
        )

        response = client.chat.completions.create(
            model=os.environ["AZURE_OPENAI_DEPLOYMENT"],
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input}
            ],
            temperature=0.3
        )

        bot_reply = response.choices[0].message.content

        # Versuche erkannte Daten (einfachste Extraktion)
        for field in required_fields:
            if field not in state and field in user_input.lower():
                state[field] = user_input  # Platzhalter – echte Extraktion kann folgen

        session["conversation_state"] = state
        return jsonify({"response": bot_reply})

    except Exception as e:
        logging.exception("Fehler im Chat-Endpunkt")
        return jsonify({"error": str(e)}), 500

# Weitere Endpunkte wie /book folgen nach finalem Test...
