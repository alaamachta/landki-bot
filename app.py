# app.py – LandKI Terminassistent mit GPT-4o + Outlook + Azure SQL + E-Mail

from flask import Flask, request, jsonify, redirect, session
from flask_cors import CORS
import os
import logging
import traceback
import requests
import json
import pyodbc
from datetime import datetime, timedelta
import msal
from openai import AzureOpenAI
from colorlog import ColoredFormatter

# === Logging Setup ===
formatter = ColoredFormatter(
    "%(log_color)s[%(levelname)s]%(reset)s %(message)s",
    log_colors={
        'DEBUG': 'cyan', 'INFO': 'green', 'WARNING': 'yellow', 'ERROR': 'red', 'CRITICAL': 'bold_red'
    }
)
handler = logging.StreamHandler()
handler.setFormatter(formatter)
logger = logging.getLogger()
logger.addHandler(handler)
logger.setLevel(logging.INFO)

# === Flask App ===
app = Flask(__name__)
CORS(app, supports_credentials=True)
app.secret_key = os.getenv("SECRET_KEY")

# === ENV Variablen ===
def env(name, required=True):
    value = os.getenv(name)
    if not value and required:
        logger.error(f"❌ ENV fehlt: {name}")
        raise EnvironmentError(f"Fehlende ENV: {name}")
    return value

AZURE_OPENAI_API_KEY     = env("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_ENDPOINT    = env("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_DEPLOYMENT  = env("AZURE_OPENAI_DEPLOYMENT")
OPENAI_API_VERSION       = env("OPENAI_API_VERSION", False) or "2024-07-01-preview"

SQL_SERVER               = env("SQL_SERVER")
SQL_DATABASE             = env("SQL_DATABASE")
SQL_USERNAME             = env("SQL_USERNAME")
SQL_PASSWORD             = env("SQL_PASSWORD")

MS_CLIENT_ID             = env("MS_CLIENT_ID")
MS_CLIENT_SECRET         = env("MS_CLIENT_SECRET")
MS_TENANT_ID             = env("MS_TENANT_ID")
MS_REDIRECT_URI          = env("MS_REDIRECT_URI")
MS_AUTHORITY             = f"https://login.microsoftonline.com/{MS_TENANT_ID}"
MS_SCOPES                = ["Calendars.ReadWrite"]

EMAIL_SENDER             = env("EMAIL_SENDER")
EMAIL_RECIPIENT          = env("EMAIL_RECIPIENT")

# === OpenAI Client ===
client = AzureOpenAI(
    api_key=AZURE_OPENAI_API_KEY,
    api_version=OPENAI_API_VERSION,
    azure_endpoint=AZURE_OPENAI_ENDPOINT
)

# === MSAL ===
def msal_app():
    return msal.ConfidentialClientApplication(
        MS_CLIENT_ID, authority=MS_AUTHORITY, client_credential=MS_CLIENT_SECRET
    )

def token_by_code(code):
    return msal_app().acquire_token_by_authorization_code(
        code, scopes=MS_SCOPES, redirect_uri=MS_REDIRECT_URI
    )

# === SQL Connection ===
def get_sql_conn():
    conn_str = f"DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={SQL_SERVER};DATABASE={SQL_DATABASE};UID={SQL_USERNAME};PWD={SQL_PASSWORD}"
    return pyodbc.connect(conn_str)

# === Routen ===
@app.route("/")
def root():
    return "✅ LandKI Terminassistent läuft"

@app.route("/calendar")
def calendar():
    session["state"] = os.urandom(24).hex()
    url = msal_app().get_authorization_request_url(
        scopes=MS_SCOPES, state=session["state"], redirect_uri=MS_REDIRECT_URI
    )
    return redirect(url)

@app.route("/callback")
def callback():
    if request.args.get("state") != session.get("state"):
        return "Ungültiger State", 400
    token = token_by_code(request.args.get("code"))
    if "access_token" not in token:
        return jsonify(token), 500
    session["access_token"] = token["access_token"]
    return "✅ Kalenderzugriff gespeichert"

@app.route("/book-test", methods=["POST"])
def book():
    try:
        msg = request.json.get("message", "")
        logger.info(f"📥 Nachricht: {msg}")

        gpt = client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,
            messages=[
                {"role": "system", "content": "Extrahiere Felder aus dem Text und gib ein JSON zurück mit: first_name, last_name, birthdate, phone, email, symptom, symptom_duration, address, appointment_start (ISO), service_type, note_internal"},
                {"role": "user", "content": msg}
            ]
        )
        data = json.loads(gpt.choices[0].message.content)

        # === Kalendereintrag ===
        start = datetime.fromisoformat(data["appointment_start"])
        end = start + timedelta(minutes=45)
        token = session.get("access_token")
        if not token:
            return redirect("/calendar")
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        body = {
            "subject": f"Termin: {data['first_name']} {data['last_name']} ({data['service_type']})",
            "start": {"dateTime": start.isoformat(), "timeZone": "Europe/Berlin"},
            "end": {"dateTime": end.isoformat(), "timeZone": "Europe/Berlin"},
            "location": {"displayName": "Online"},
            "body": {"contentType": "Text", "content": data["note_internal"] or "Keine Notiz"}
        }
        res = requests.post("https://graph.microsoft.com/v1.0/me/events", headers=headers, json=body)
        if res.status_code != 201:
            logger.error(res.text)
            return jsonify({"error": "Kalenderfehler"}), 500

        # === SQL Insert ===
        conn = get_sql_conn()
        cursor = conn.cursor()
        sql = """
        INSERT INTO dbo.appointments (first_name, last_name, birthdate, phone, email, symptom, symptom_duration, address, appointment_start, appointment_end, created_at, service_type, note_internal)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        values = (
            data['first_name'], data['last_name'], data['birthdate'],
            data['phone'], data['email'], data['symptom'], data['symptom_duration'],
            data['address'], start, end, datetime.utcnow(),
            data['service_type'], data['note_internal']
        )
        cursor.execute(sql, values)
        conn.commit()
        conn.close()

        return jsonify({"status": "success", "info": "Termin gespeichert."})

    except Exception:
        logger.error("❌ Fehler bei Buchung:")
        logger.error(traceback.format_exc())
        return jsonify({"error": "Interner Fehler"}), 500
