from flask import Flask, request, jsonify, redirect, session
from flask_cors import CORS
import os
import logging
import traceback
import requests
import pyodbc
import smtplib
from email.message import EmailMessage
from datetime import datetime
from colorlog import ColoredFormatter
from openai import AzureOpenAI
import markdown2

# === Logging Setup ===
formatter = ColoredFormatter(
    "%(log_color)s[%(levelname)s]%(reset)s %(message)s",
    log_colors={
        'DEBUG': 'cyan',
        'INFO': 'green',
        'WARNING': 'yellow',
        'ERROR': 'red',
        'CRITICAL': 'bold_red',
    }
)
handler = logging.StreamHandler()
handler.setFormatter(formatter)
logger = logging.getLogger()
logger.addHandler(handler)
logger.setLevel(logging.INFO)

# === Flask Setup ===
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)
app.secret_key = os.getenv("SECRET_KEY", "test-secret")

# === ENV Variablen ===
def get_env(name, required=True):
    val = os.getenv(name)
    if required and not val:
        logger.error(f"❌ Fehlende ENV: {name}")
        raise Exception(f"Missing ENV: {name}")
    return val

AZURE_OPENAI_KEY = get_env("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_ENDPOINT = get_env("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_DEPLOYMENT = get_env("AZURE_OPENAI_DEPLOYMENT")
OPENAI_API_VERSION = get_env("OPENAI_API_VERSION", False) or "2024-07-01-preview"
SQL_CONN_STR = get_env("AZURE_SQL_CONNECTION_STRING")
SMTP_USER = get_env("SMTP_USER")
SMTP_PASS = get_env("SMTP_PASS")

# === OpenAI Setup ===
client = AzureOpenAI(
    api_key=AZURE_OPENAI_KEY,
    api_version=OPENAI_API_VERSION,
    azure_endpoint=AZURE_OPENAI_ENDPOINT
)

# === Routes ===
@app.route("/")
def home():
    return "✅ LandKI Bot läuft."

@app.route("/calendar-test")
def calendar_test():
    return "📅 Kalenderroute erreichbar."

@app.route("/book-test")
def book_test():
    return "📘 Buchungsroute erreichbar."

@app.route("/chat", methods=["POST"])
def chat():
    try:
        user_input = request.json.get("message", "")
        response = client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,
            messages=[{"role": "user", "content": user_input}],
            temperature=0.3
        )
        answer = response.choices[0].message.content
        return jsonify({"response": answer, "reply_html": markdown2.markdown(answer)})
    except Exception as e:
        logger.error("GPT Fehler: " + str(e))
        logger.debug(traceback.format_exc())
        return jsonify({"error": "Fehler im Chat."}), 500

@app.route("/book", methods=["POST"])
def book():
    try:
        data = request.json
        logger.info("📥 Neue Buchung erhalten")

        # Daten vorbereiten
        name = f"{data['first_name']} {data['last_name']}"
        appt_time = datetime.strptime(data['appointment_time'], "%Y-%m-%d %H:%M")

        # 📧 E-Mail an Praxis + Patient
        email = EmailMessage()
        email['Subject'] = f"Terminbestätigung – {name}"
        email['From'] = SMTP_USER
        email['To'] = f"{data['email']}, {SMTP_USER}"
        email.set_content(
            f"Patient: {name}\nGeburtstag: {data['birthdate']}\nTelefon: {data['phone']}\nSymptom: {data['symptom']}\nDauer: {data['symptom_duration']}\nAdresse: {data['address']}\nTermin: {appt_time}"
        )

        with smtplib.SMTP("smtp.office365.com", 587) as smtp:
            smtp.starttls()
            smtp.login(SMTP_USER, SMTP_PASS)
            smtp.send_message(email)
        logger.info("📧 E-Mail gesendet")

        # 📦 SQL speichern
        conn = pyodbc.connect(SQL_CONN_STR)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO appointments (first_name, last_name, phone, email, birthdate, symptom, symptom_duration, address, appointment_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data['first_name'], data['last_name'], data['phone'], data['email'], data['birthdate'],
            data['symptom'], data['symptom_duration'], data['address'], data['appointment_time']
        ))
        conn.commit()
        conn.close()
        logger.info("💾 Termin in SQL gespeichert")

        return jsonify({"status": "success", "message": "Termin gespeichert und bestätigt."})

    except Exception as e:
        logger.error("❌ Fehler bei /book: " + str(e))
        logger.debug(traceback.format_exc())
        return jsonify({"error": "Interner Fehler"}), 500
