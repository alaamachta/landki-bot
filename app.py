# Datei: app.py (Startpunkt für Szenario 1: Terminbuchung)

import os
import logging
import datetime
import openai
import pyodbc
import smtplib
from email.message import EmailMessage
from flask import Flask, request, jsonify
from flask_cors import CORS
import msal
import requests

# Zeitzone für Logging auf Berlin setzen
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logging.Formatter.converter = lambda *args: datetime.datetime.now(tz=datetime.timezone(datetime.timedelta(hours=2))).timetuple()

# Flask Setup
app = Flask(__name__)
CORS(app)

# Umgebung lesen
AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_KEY")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")

SQL_SERVER = os.getenv("AZURE_SQL_SERVER")  # z. B. landki-sql-server.database.windows.net
SQL_DB = os.getenv("AZURE_SQL_DATABASE")
SQL_USER = os.getenv("AZURE_SQL_USER")
SQL_PASSWORD = os.getenv("AZURE_SQL_PASSWORD")

SMTP_CLIENT_ID = os.getenv("SMTP_CLIENT_ID")
SMTP_TENANT_ID = os.getenv("SMTP_TENANT_ID")
SMTP_CLIENT_SECRET = os.getenv("SMTP_CLIENT_SECRET")
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL")

# OpenAI config
openai.api_key = AZURE_OPENAI_KEY
openai.api_base = AZURE_OPENAI_ENDPOINT
openai.api_type = "azure"
openai.api_version = "2024-07-01-preview"

# SQL Verbindung aufbauen
def get_sql_connection():
    conn_str = f"DRIVER={{ODBC Driver 18 for SQL Server}};SERVER={SQL_SERVER};DATABASE={SQL_DB};UID={SQL_USER};PWD={SQL_PASSWORD};Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
    return pyodbc.connect(conn_str)

# Token holen für SMTP (OAuth2)
def get_smtp_token():
    authority = f"https://login.microsoftonline.com/{SMTP_TENANT_ID}"
    app_auth = msal.ConfidentialClientApplication(
        SMTP_CLIENT_ID, authority=authority, client_credential=SMTP_CLIENT_SECRET
    )
    result = app_auth.acquire_token_for_client(scopes=["https://outlook.office365.com/.default"])
    return result.get("access_token")

# E-Mail senden
def send_email(subject, body, recipient):
    token = get_smtp_token()
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = SENDER_EMAIL
    msg["To"] = recipient
    msg.set_content(body)

    with smtplib.SMTP("smtp.office365.com", 587) as smtp:
        smtp.starttls()
        smtp.ehlo()
        smtp.auth("XOAUTH2", lambda x: f"user={SENDER_EMAIL}\x01auth=Bearer {token}\x01\x01")
        smtp.send_message(msg)

# Terminbuchung (GPT ruft diesen Endpoint indirekt auf)
@app.route("/book", methods=["POST"])
def book():
    try:
        data = request.json
        name = data.get("name")
        nachname = data.get("nachname")
        alter = data.get("alter")
        geburtstag = data.get("geburtstag")
        telefon = data.get("telefon")
        symptome = data.get("symptome")
        dauer = data.get("dauer")
        adresse = data.get("adresse")
        zeitslot = data.get("zeitslot")

        # SQL speichern
        conn = get_sql_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO termine (name, nachname, alter, geburtstag, telefon, symptome, dauer, adresse, zeitslot)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            name, nachname, alter, geburtstag, telefon, symptome, dauer, adresse, zeitslot)
        conn.commit()
        cursor.close()
        conn.close()

        # E-Mail an Patient & Praxis
        body = f"Termin für {name} {nachname}, {alter} Jahre, Tel: {telefon}, {symptome} ({dauer})\nAdresse: {adresse}\nZeit: {zeitslot}"
        send_email("Terminbestätigung", body, recipient=telefon + "@sms.provider.de")  # oder E-Mail-Feld
        send_email("Neuer Termin", body, RECIPIENT_EMAIL)

        return jsonify({"status": "ok"})

    except Exception as e:
        logging.error(f"Fehler bei Terminbuchung: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/status", methods=["GET"])
def status():
    return jsonify({"status": "ready"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
