import os
import json
import logging
import openai
import pyodbc
import smtplib
from flask import Flask, request, jsonify
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from zoneinfo import ZoneInfo

# Flask Setup
app = Flask(__name__)

# Logging Setup
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(levelname)s:%(message)s")
logger = logging.getLogger(__name__)

# Zeitzone auf Europe/Berlin setzen
TZ = ZoneInfo("Europe/Berlin")

# SQL-Verbindungsdaten aus Umgebungsvariablen
SQL_SERVER = os.getenv("SQL_SERVER")
SQL_DATABASE = os.getenv("SQL_DATABASE")
SQL_USERNAME = os.getenv("SQL_USERNAME")
SQL_PASSWORD = os.getenv("SQL_PASSWORD")

# SQL-Verbindung
connection_string = f"DRIVER={{ODBC Driver 18 for SQL Server}};SERVER={SQL_SERVER};DATABASE={SQL_DATABASE};UID={SQL_USERNAME};PWD={SQL_PASSWORD}"

def insert_appointment(data):
    try:
        with pyodbc.connect(connection_string) as conn:
            cursor = conn.cursor()
            logger.debug("SQL-Verbindung erfolgreich aufgebaut.")

            query = """
            INSERT INTO appointments (
                first_name, last_name, birthdate, phone, email, symptom, symptom_duration, address,
                appointment_start, appointment_end, created_at, company_code, bot_origin,
                service_type, note_internal
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """

            now = datetime.now(TZ)
            start = now + timedelta(days=2)
            end = start + timedelta(minutes=15)

            cursor.execute(query, (
                data.get("first_name"),
                data.get("last_name"),
                data.get("birthdate"),  # <-- birthdate statt birthday
                data.get("phone"),
                data.get("email"),
                data.get("symptom"),
                data.get("symptom_duration"),
                data.get("address"),
                start,
                end,
                now,
                data.get("company_code"),
                data.get("bot_origin"),
                data.get("service_type"),
                data.get("note_internal")
            ))
            conn.commit()
            logger.info("✅ SQL-Eintrag erfolgreich gespeichert.")
            return True
    except Exception as e:
        logger.error(f"❌ Fehler beim SQL-Insert: {str(e)}")
        return False

def send_email(to_email, subject, body):
    try:
        from_email = "AlaaMashta@LandKI.onmicrosoft.com"

        message = MIMEMultipart()
        message["From"] = from_email
        message["To"] = to_email
        message["Subject"] = subject
        message.attach(MIMEText(body, "plain"))

        smtp_server = smtplib.SMTP("smtp.office365.com", 587)
        smtp_server.starttls()
        smtp_server.login(from_email, os.getenv("EMAIL_PASSWORD"))
        smtp_server.send_message(message)
        smtp_server.quit()

        logger.info(f"📧 E-Mail gesendet an: {to_email}")
    except Exception as e:
        logger.error(f"❌ Fehler beim E-Mail-Versand: {str(e)}")

@app.route("/book", methods=["POST"])
def book():
    try:
        data = request.get_json()
        logger.debug(f"📥 Eingehende Daten: {data}")

        if not data.get("first_name") or not data.get("birthdate"):
            return jsonify({"error": "Vorname und Geburtsdatum sind Pflichtfelder."}), 400

        success = insert_appointment(data)

        if success:
            email_body = f"Hallo {data['first_name']},\n\nIhr Termin wurde erfolgreich gebucht.\n\nViele Grüße\nIhr LandKI-Team"
            send_email(data["email"], "Terminbestätigung", email_body)

            praxis_mail = "admin@landki.com"
            praxis_body = f"Termin für {data['first_name']} {data['last_name']} wurde gebucht."
            send_email(praxis_mail, "Neuer Termin eingetragen", praxis_body)

            return jsonify({"message": "✅ Termin erfolgreich gebucht."})
        else:
            return jsonify({"error": "❌ Fehler beim Speichern des Termins."}), 500
    except Exception as e:
        logger.error(f"❌ Unerwarteter Fehler: {str(e)}")
        return jsonify({"error": "❌ Serverfehler"}), 500

if __name__ == "__main__":
    app.run(debug=True)
