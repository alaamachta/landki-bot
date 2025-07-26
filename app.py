import os
import logging
from flask import Flask, request, jsonify
from flask_cors import CORS
import openai
import smtplib
import pyodbc
from email.mime.text import MIMEText
from datetime import datetime, timedelta
timezone = 'Europe/Berlin'

# Initialisiere Logging mit WebApp-Loglevel
logging.basicConfig(level=os.getenv("WEBSITE_LOGGING_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

# Flask App initialisieren
app = Flask(__name__)
CORS(app)

# GPT-Konfiguration
openai.api_type = "azure"
openai.api_key = os.getenv("AZURE_OPENAI_KEY")
openai.api_base = os.getenv("AZURE_OPENAI_ENDPOINT")
openai.api_version = os.getenv("OPENAI_API_VERSION", "2024-05-13")

deployment_id = os.getenv("AZURE_OPENAI_DEPLOYMENT")

# SQL-Verbindung vorbereiten
sql_conn_str = os.getenv("AZURE_SQL_CONNECTION_STRING")

def insert_appointment_sql(first_name, last_name, birthdate, phone, email, symptoms, symptom_duration, address):
    try:
        conn = pyodbc.connect(sql_conn_str)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS appointments (
                id INT IDENTITY(1,1) PRIMARY KEY,
                first_name NVARCHAR(100),
                last_name NVARCHAR(100),
                birthdate DATE,
                phone NVARCHAR(50),
                email NVARCHAR(100),
                symptoms NVARCHAR(MAX),
                symptom_duration NVARCHAR(100),
                address NVARCHAR(MAX),
                created_at DATETIME DEFAULT GETDATE()
            )
        """)
        cursor.execute("""
            INSERT INTO appointments (first_name, last_name, birthdate, phone, email, symptoms, symptom_duration, address)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (first_name, last_name, birthdate, phone, email, symptoms, symptom_duration, address))
        conn.commit()
        cursor.close()
        conn.close()
        logger.info("✅ SQL Insert erfolgreich für %s %s", first_name, last_name)
        return True
    except Exception as e:
        logger.error("❌ SQL Insert Fehler: %s", str(e))
        return False

# E-Mail Versandfunktion
from_email = os.getenv("EMAIL_SENDER")  # z. B. AlaaMashta@landki.onmicrosoft.com

def send_email(subject, body, recipient):
    try:
        msg = MIMEText(body, "plain")
        msg["Subject"] = subject
        msg["From"] = from_email
        msg["To"] = recipient

        with smtplib.SMTP("smtp.office365.com", 587) as server:
            server.starttls()
            server.login(from_email, os.getenv("MS_CLIENT_SECRET"))  # Nur temporär ohne OAuth
            server.sendmail(from_email, [recipient], msg.as_string())

        logger.info("✅ E-Mail erfolgreich gesendet an %s", recipient)
        return True
    except Exception as e:
        logger.error("❌ Fehler beim Senden der E-Mail: %s", str(e))
        return False

# Route für Terminbuchung
@app.route("/book-appointment", methods=["POST"])
def book_appointment():
    data = request.json
    logger.info("📥 Terminbuchung erhalten: %s", data)

    first_name = data.get("first_name")
    last_name = data.get("last_name")
    birthdate = data.get("birthdate")
    phone = data.get("phone")
    email = data.get("email")
    symptoms = data.get("symptoms")
    symptom_duration = data.get("symptom_duration")
    address = data.get("address")

    # SQL speichern
    success = insert_appointment_sql(first_name, last_name, birthdate, phone, email, symptoms, symptom_duration, address)

    # E-Mail an Patient senden
    subject = "Terminbestätigung - LandKI"
    body = f"""
Hallo {first_name} {last_name},

vielen Dank für Ihre Terminanfrage.

🗓️ Geburtsdatum: {birthdate}
📱 Telefon: {phone}
📩 E-Mail: {email}
📍 Adresse: {address}

🩺 Symptome: {symptoms}
⏱️ Dauer: {symptom_duration}

Wir bestätigen Ihnen den Eingang und melden uns in Kürze mit einem konkreten Terminvorschlag.

Viele Grüße
Ihr LandKI Team
    """
    send_email(subject, body, email)

    return jsonify({"status": "success", "message": "Terminbuchung empfangen"})

# Test-Route
@app.route("/", methods=["GET"])
def home():
    return "LandKI Bot is running."

# Start App
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
