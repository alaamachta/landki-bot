from flask import Flask, request, jsonify, session
from flask_cors import CORS
import openai
import logging
import os
import datetime
import pytz
import pyodbc
import msal
import requests
import uuid
from dateutil import parser

# Flask App Setup
app = Flask(__name__)
CORS(app)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "1234")

# GPT Setup (Azure OpenAI)
openai.api_type = "azure"
openai.api_base = os.environ["OPENAI_API_BASE"]
openai.api_version = "2024-05-01-preview"
openai.api_key = os.environ["OPENAI_API_KEY"]
GPT_DEPLOYMENT = os.environ.get("OPENAI_DEPLOYMENT", "gpt-4o")

# SQL Setup
SQL_SERVER = os.environ["SQL_SERVER"]
SQL_DATABASE = os.environ["SQL_DATABASE"]
SQL_USERNAME = os.environ["SQL_USERNAME"]
SQL_PASSWORD = os.environ["SQL_PASSWORD"]

# Verbindung zur SQL-Datenbank (ODBC-Treiber vorausgesetzt)
SQL_CONNECTION_STRING = f"DRIVER={{ODBC Driver 18 for SQL Server}};SERVER={SQL_SERVER};DATABASE={SQL_DATABASE};UID={SQL_USERNAME};PWD={SQL_PASSWORD};Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"

# Logging Setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("LandKI-Bot")

# Zeitzone
TIMEZONE = pytz.timezone("Europe/Berlin")

# E-Mail Setup (Microsoft 365 via OAuth)
EMAIL_CLIENT_ID = os.environ["EMAIL_CLIENT_ID"]
EMAIL_CLIENT_SECRET = os.environ["EMAIL_CLIENT_SECRET"]
EMAIL_TENANT_ID = os.environ["EMAIL_TENANT_ID"]
EMAIL_ACCOUNT = os.environ["EMAIL_ACCOUNT"]  # z.B. admin@landki.com
EMAIL_SCOPE = ["https://graph.microsoft.com/.default"]


def get_email_token():
    app = msal.ConfidentialClientApplication(
        EMAIL_CLIENT_ID,
        authority=f"https://login.microsoftonline.com/{EMAIL_TENANT_ID}",
        client_credential=EMAIL_CLIENT_SECRET
    )
    result = app.acquire_token_for_client(scopes=EMAIL_SCOPE)
    if "access_token" in result:
        return result["access_token"]
    else:
        raise Exception("❌ Tokenabruf für E-Mail fehlgeschlagen: " + str(result))


def send_email_to_recipient(to_address, subject, body):
    token = get_email_token()
    email_url = "https://graph.microsoft.com/v1.0/users/{}/sendMail".format(EMAIL_ACCOUNT)

    email_msg = {
        "message": {
            "subject": subject,
            "body": {
                "contentType": "HTML",
                "content": body
            },
            "toRecipients": [
                {"emailAddress": {"address": to_address}}
            ]
        }
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    response = requests.post(email_url, headers=headers, json=email_msg)

    if response.status_code != 202:
        raise Exception(f"❌ Fehler beim Senden der E-Mail an {to_address}: {response.status_code}, {response.text}")
    else:
        logger.info(f"📧 E-Mail erfolgreich gesendet an {to_address}")


# Route: book appointment
@app.route("/book-appointment", methods=["POST"])
def book_appointment():
    try:
        data = request.json

        # Extract patient data
        first_name = data.get("first_name")
        last_name = data.get("last_name")
        birthday = data.get("birthday")
        phone = data.get("phone")
        email = data.get("email")
        symptoms = data.get("symptoms")
        duration = data.get("duration")
        address = data.get("address")
        appointment_start = data.get("appointment_start")
        appointment_end = data.get("appointment_end")

        logger.info(f"📅 Buche Termin für {first_name} {last_name} am {appointment_start}")

        # SQL Insert
        with pyodbc.connect(SQL_CONNECTION_STRING) as conn:
            cursor = conn.cursor()
            insert_query = """
                INSERT INTO appointments (first_name, last_name, birthday, phone, email, symptoms, duration, address, appointment_start, appointment_end)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            cursor.execute(insert_query, (
                first_name, last_name, birthday, phone, email,
                symptoms, duration, address, appointment_start, appointment_end
            ))
            conn.commit()
            logger.info("✅ Patientendaten erfolgreich in SQL gespeichert")

        # Email-Benachrichtigungen senden
        subject = f"Neue Terminbuchung: {first_name} {last_name}"
        email_body = f"""
        <p>Ein neuer Termin wurde gebucht:</p>
        <ul>
            <li><strong>Name:</strong> {first_name} {last_name}</li>
            <li><strong>Geburtsdatum:</strong> {birthday}</li>
            <li><strong>Telefon:</strong> {phone}</li>
            <li><strong>E-Mail:</strong> {email}</li>
            <li><strong>Symptome:</strong> {symptoms}</li>
            <li><strong>Dauer:</strong> {duration}</li>
            <li><strong>Adresse:</strong> {address}</li>
            <li><strong>Start:</strong> {appointment_start}</li>
            <li><strong>Ende:</strong> {appointment_end}</li>
        </ul>
        <p>Diese Nachricht wurde automatisch von LandKI erstellt.</p>
        """

        send_email_to_recipient(EMAIL_ACCOUNT, subject, email_body)  # an Praxis
        send_email_to_recipient(email, subject, email_body)          # an Patient

        return jsonify({"status": "success", "message": "Termin gebucht, gespeichert und E-Mails gesendet."})

    except Exception as e:
        logger.error(f"❌ Fehler bei Terminbuchung: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


# Health check
@app.route("/", methods=["GET"])
def health_check():
    return "LandKI Bot läuft."

if __name__ == "__main__":
    app.run(debug=True)
