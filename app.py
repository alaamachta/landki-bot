import os
import logging
import openai
import smtplib
import json
import pytz
import pyodbc
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from flask_cors import CORS
from msal import ConfidentialClientApplication

# Konfiguration
openai.api_key = os.environ.get("OPENAI_API_KEY")
AZURE_SQL_SERVER = os.environ.get("AZURE_SQL_SERVER")
AZURE_SQL_DB = os.environ.get("AZURE_SQL_DB")
AZURE_SQL_USER = os.environ.get("AZURE_SQL_USER")
AZURE_SQL_PASSWORD = os.environ.get("AZURE_SQL_PASSWORD")
SMTP_CLIENT_ID = os.environ.get("SMTP_CLIENT_ID")
SMTP_CLIENT_SECRET = os.environ.get("SMTP_CLIENT_SECRET")
SMTP_TENANT_ID = os.environ.get("SMTP_TENANT_ID")
SMTP_SENDER = os.environ.get("SMTP_SENDER")
SMTP_RECIPIENT = os.environ.get("SMTP_RECIPIENT")
LOGGING_LEVEL = os.environ.get("WEBSITE_LOGGING_LEVEL", "INFO")

# Logging
logging.basicConfig(level=LOGGING_LEVEL, format='[%(asctime)s] %(levelname)s in %(module)s: %(message)s')
logger = logging.getLogger(__name__)

# Flask App
app = Flask(__name__)
CORS(app)

def send_confirmation_email(patient_email, subject, body):
    try:
        authority = f"https://login.microsoftonline.com/{SMTP_TENANT_ID}"
        app_msal = ConfidentialClientApplication(
            SMTP_CLIENT_ID,
            authority=authority,
            client_credential=SMTP_CLIENT_SECRET,
        )
        token_response = app_msal.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
        access_token = token_response.get("access_token")

        if not access_token:
            raise Exception("Failed to obtain access token for SMTP")

        message = MIMEMultipart()
        message["Subject"] = subject
        message["From"] = SMTP_SENDER
        message["To"] = patient_email
        message.attach(MIMEText(body, "plain"))

        smtp = smtplib.SMTP("smtp.office365.com", 587)
        smtp.starttls()
        smtp.login(SMTP_SENDER, access_token)
        smtp.sendmail(SMTP_SENDER, patient_email, message.as_string())
        smtp.quit()

        logger.info(f"E-Mail an {patient_email} gesendet.")
    except Exception as e:
        logger.error(f"E-Mail-Fehler: {e}")

def insert_appointment_to_sql(data):
    try:
        conn_str = (
            f"DRIVER={{ODBC Driver 18 for SQL Server}};SERVER={AZURE_SQL_SERVER};DATABASE={AZURE_SQL_DB};"
            f"UID={AZURE_SQL_USER};PWD={AZURE_SQL_PASSWORD};Encrypt=yes;TrustServerCertificate=no"
        )
        with pyodbc.connect(conn_str) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS appointments (
                    id INT PRIMARY KEY IDENTITY(1,1),
                    first_name NVARCHAR(100),
                    last_name NVARCHAR(100),
                    birthday DATE,
                    phone NVARCHAR(50),
                    email NVARCHAR(100),
                    symptoms NVARCHAR(500),
                    duration NVARCHAR(100),
                    address NVARCHAR(300),
                    appointment_start DATETIME,
                    appointment_end DATETIME
                )
            """)
            cursor.execute("""
                INSERT INTO appointments (first_name, last_name, birthday, phone, email, symptoms, duration, address, appointment_start, appointment_end)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                data["first_name"], data["last_name"], data["birthday"],
                data["phone"], data["email"], data["symptoms"], data["duration"],
                data["address"], data["appointment_start"], data["appointment_end"]
            )
            conn.commit()
        logger.info("SQL-Eintrag erfolgreich.")
    except Exception as e:
        logger.error(f"SQL-Fehler: {e}")

@app.route("/book-appointment", methods=["POST"])
def book_appointment():
    try:
        data = request.get_json()
        insert_appointment_to_sql(data)

        subject = "Terminbestätigung – LandKI"
        body = f"""
Sehr geehrte/r {data['first_name']} {data['last_name']},

Ihr Termin wurde erfolgreich gebucht:
Datum: {data['appointment_start']} bis {data['appointment_end']}
Symptome: {data['symptoms']}

Adresse:
{data['address']}

Vielen Dank für Ihre Buchung!
Ihr LandKI-Team
        """
        send_confirmation_email(data["email"], subject, body)
        send_confirmation_email(SMTP_RECIPIENT, "Neue Terminbuchung", body)

        return jsonify({"status": "success", "message": "Terminbuchung empfangen"})
    except Exception as e:
        logger.error(f"Fehler bei Terminbuchung: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/chat", methods=["POST"])
def chat():
    try:
        message = request.json.get("message", "")
        logger.info(f"Nachricht erhalten: {message}")

        system_prompt = """
Du bist der freundliche Assistent von LandKI. Wenn jemand Hilfe braucht, begrüßt du die Person und bietest diese Optionen:

🟢 Termin buchen
🔵 Terminstatus prüfen
🔴 Termin stornieren

Frage am Anfang z. B.: Wie kann ich Ihnen helfen? Möchten Sie einen Termin buchen oder ändern?
        """
        completion = openai.ChatCompletion.create(
            engine="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message},
            ],
            temperature=0.5
        )
        reply = completion.choices[0].message.content
        return jsonify({"reply": reply})

    except Exception as e:
        logger.error(f"Fehler bei GPT-Antwort: {e}")
        return jsonify({"error": "Fehler beim Verarbeiten der Anfrage."}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
