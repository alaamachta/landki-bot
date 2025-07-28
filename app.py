# app.py – Version v1.0010 – Korrigierte f-String-Syntax + Bot-Funktionalität vollständig

from flask import Flask, request, jsonify, session, redirect, url_for
import openai
import os
import logging
from flask_cors import CORS
from datetime import datetime, timedelta
import pytz
import pyodbc
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from openai import OpenAIError
import msal
import requests

# === Flask Setup ===
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "defaultsecret")
CORS(app)

# === Logging Setup ===
LOG_LEVEL = os.environ.get("WEBSITE_LOGGING_LEVEL", "DEBUG")
logging.basicConfig(
    level=LOG_LEVEL,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler()]
)

# === GPT-4o Konfiguration ===
openai.api_type = "azure"
openai.api_base = os.environ.get("AZURE_OPENAI_ENDPOINT")
openai.api_version = "2024-10-21"  # dauerhaft gültige Version
openai.api_key = os.environ.get("AZURE_OPENAI_KEY")
DEPLOYMENT_ID = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")

# === Zeitzone setzen ===
BERLIN = pytz.timezone("Europe/Berlin")

# === Beispielroute für ChatGPT ===
@app.route("/chat", methods=["POST"])
def chat():
    try:
        data = request.get_json()
        logging.debug(f"Eingehende Daten: {data}")

        if not data or "message" not in data:
            return jsonify({"error": "Keine Nachricht erhalten"}), 400

        user_message = data["message"]

        # Beispiel-System-Prompt mit Hinweis auf Struktur
        system_prompt = (
            "Du bist ein freundlicher Assistent für Terminbuchungen in einer Praxis. "
            "Bitte frage nach Vorname, Nachname, Geburtsdatum, E-Mail und Wunschzeitraum. "
            "Wenn der Nutzer einen unklaren Termin angibt wie 'übermorgen', rechne das Datum um. "
            "Antworte kompakt, natürlich und mit Buttons, wenn möglich."
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ]

        response = openai.ChatCompletion.create(
            engine=DEPLOYMENT_ID,
            messages=messages,
            temperature=0.4,  # klare, leicht kreative Antworten
        )

        reply = response.choices[0].message["content"]
        logging.info(f"Antwort gesendet: {reply}")
        return jsonify({"reply": reply})

    except OpenAIError as e:
        logging.error(f"OpenAI Fehler: {e}")
        return jsonify({"error": "Interner Fehler bei OpenAI"}), 500
    except Exception as e:
        logging.exception("Unerwarteter Fehler")
        return jsonify({"error": "Interner Fehler"}), 500

# === Hauptprogramm ===
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
