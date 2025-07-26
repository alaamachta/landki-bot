# ✅ KOMPLETTE app.py mit Logging, Kalender, SQL, E-Mail (LandKI Bot)
# Version: 2025-07-26

from flask import Flask, request, jsonify, session, redirect, url_for
from flask_cors import CORS
import openai
import logging
import os
from datetime import datetime, timedelta
import pytz
import uuid
import msal
import requests
import pyodbc
from azure.identity import DefaultAzureCredential

# 🌍 Flask App initialisieren
app = Flask(__name__)
CORS(app)
app.secret_key = os.getenv("FLASK_SECRET_KEY", str(uuid.uuid4()))

# 🌐 Zeitzone setzen
berlin_tz = pytz.timezone("Europe/Berlin")

# 🔧 Logging-Konfiguration
logging_level = os.getenv("WEBSITE_LOGGING_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, logging_level, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
)

# 🔑 Azure App-Registrierung (OAuth2 für Outlook & Mail)
CLIENT_ID = os.getenv("AZURE_CLIENT_ID")
CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET")
TENANT_ID = os.getenv("AZURE_TENANT_ID")
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
SCOPES = ["https://graph.microsoft.com/.default"]
REDIRECT_URI = os.getenv("AZURE_REDIRECT_URI")

# 💬 GPT-Setup
openai.api_key = os.getenv("AZURE_OPENAI_API_KEY")
openai.api_base = os.getenv("AZURE_OPENAI_ENDPOINT")
openai.api_type = "azure"
openai.api_version = "2024-05-01-preview"
DEPLOYMENT_ID = os.getenv("AZURE_OPENAI_DEPLOYMENT")

# 💾 SQL-Verbindung
SQL_SERVER = os.getenv("SQL_SERVER")
SQL_DATABASE = os.getenv("SQL_DATABASE")
SQL_USERNAME = os.getenv("SQL_USERNAME")
SQL_PASSWORD = os.getenv("SQL_PASSWORD")
SQL_DRIVER = os.getenv("SQL_DRIVER", "ODBC Driver 17 for SQL Server")

conn_str = (
    f"DRIVER={{{SQL_DRIVER}}};SERVER={SQL_SERVER};DATABASE={SQL_DATABASE};"
    f"UID={SQL_USERNAME};PWD={SQL_PASSWORD}"
)

# 🔁 Zugriffstoken erhalten (OAuth2 für Outlook)
def get_access_token():
    app_msal = msal.ConfidentialClientApplication(
        CLIENT_ID, authority=AUTHORITY, client_credential=CLIENT_SECRET
    )
    result = app_msal.acquire_token_for_client(scopes=SCOPES)
    if "access_token" in result:
        return result["access_token"]
    else:
        logging.error("❌ Fehler beim Abrufen des Zugriffstokens: %s", result.get("error_description"))
        return None

# 📅 Outlook-Termin erstellen
def create_calendar_event(first_name, last_name, start, end, email, notes):
    access_token = get_access_token()
    if not access_token:
        raise Exception("Kein Zugriffstoken erhalten")

    event = {
        "subject": f"Termin mit {first_name} {last_name}",
        "start": {"dateTime": start, "timeZone": "Europe/Berlin"},
        "end": {"dateTime": end, "timeZone": "Europe/Berlin"},
        "attendees": [{"emailAddress": {"address": email}, "type": "required"}],
        "body": {"contentType": "Text", "content": notes or ""}
    }

    response = requests.post(
        "https://graph.microsoft.com/v1.0/me/events",
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        json=event
    )
    if not response.ok:
        raise Exception(f"Fehler bei Outlook-Event: {response.text}")

# 💾 SQL-Speicherung
def insert_appointment(first_name, last_name, birthdate, phone, email, symptom, symptom_duration, address, start, end, created_at, company_code, notes):
    conn = pyodbc.connect(conn_str)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO dbo.appointments (
            first_name, last_name, birthdate, phone, email, symptom,
            symptom_duration, address, appointment_start, appointment_end,
            created_at, company_code, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        first_name, last_name, birthdate, phone, email, symptom,
        symptom_duration, address, start, end, created_at, company_code, notes
    )
    conn.commit()
    conn.close()

# 📧 Dummy-E-Mail-Sendung (noch nicht produktiv)
def send_email(recipient, start_time, first_name, last_name):
    logging.info(f"📧 E-Mail an {recipient} wird vorbereitet (Mock). Termin: {start_time} für {first_name} {last_name}.")

# 📦 Hauptfunktion zur Terminbuchung (inkl. Logging)
@app.route("/book", methods=["POST"])
def book_appointment():
    try:
        data = request.get_json()
        logging.info("📥 Starte Buchung mit Daten: %s", data)

        # Daten extrahieren
        first_name = data.get("first_name")
        last_name = data.get("last_name")
        email = data.get("email")
        phone = data.get("phone")
        birthdate = data.get("birthdate")
        symptom = data.get("symptom")
        symptom_duration = data.get("symptom_duration")
        address = data.get("address")
        appointment_start = data.get("appointment_start")
        appointment_end = data.get("appointment_end")
        notes = data.get("notes", "")
        company_code = data.get("company_code", "LK")

        # Aktionen ausführen
        create_calendar_event(first_name, last_name, appointment_start, appointment_end, email, notes)
        insert_appointment(first_name, last_name, birthdate, phone, email, symptom, symptom_duration, address, appointment_start, appointment_end, datetime.now(berlin_tz), company_code, notes)
        send_email(email, appointment_start, first_name, last_name)

        return jsonify({"status": "success"})

    except Exception as e:
        logging.error("❌ Fehler bei Terminbuchung: %s", str(e))
        return jsonify({"status": "error", "message": str(e)}), 500

# 🧪 Gesundheitstest
@app.route("/ping")
def ping():
    return "pong", 200

# 🚀 Starten (für Gunicorn, z. B. via: gunicorn app:app)
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
