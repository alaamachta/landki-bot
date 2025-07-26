from flask import Flask, request, jsonify, redirect, session
from flask_cors import CORS
import os
import logging
import traceback
import requests
from colorlog import ColoredFormatter
from openai import AzureOpenAI
import markdown2
import msal
from datetime import datetime, timedelta
import json
import pyodbc  # Für SQL-Verbindung

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
app.secret_key = os.getenv("SECRET_KEY")

# === Hilfsfunktion für sichere ENV-Nutzung ===
def get_env_var(name, required=True):
    value = os.getenv(name)
    if not value and required:
        logger.error(f"❌ ENV fehlt: {name}")
        raise EnvironmentError(f"Missing environment variable: {name}")
    return value

# === ENV-Variablen ===
AZURE_OPENAI_API_KEY     = get_env_var("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_ENDPOINT    = get_env_var("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_DEPLOYMENT  = get_env_var("AZURE_OPENAI_DEPLOYMENT")
AZURE_SEARCH_ENDPOINT    = get_env_var("AZURE_SEARCH_ENDPOINT")
AZURE_SEARCH_KEY         = get_env_var("AZURE_SEARCH_KEY")
AZURE_SEARCH_INDEX       = get_env_var("AZURE_SEARCH_INDEX")
OPENAI_API_VERSION       = get_env_var("OPENAI_API_VERSION", required=False) or "2024-07-01-preview"

MS_CLIENT_ID             = get_env_var("MS_CLIENT_ID")
MS_CLIENT_SECRET         = get_env_var("MS_CLIENT_SECRET")
MS_TENANT_ID             = get_env_var("MS_TENANT_ID")
MS_REDIRECT_URI          = get_env_var("MS_REDIRECT_URI")
MS_SCOPES                = ["Calendars.Read", "Calendars.ReadWrite", "Mail.Send"]
MS_AUTHORITY             = f"https://login.microsoftonline.com/{MS_TENANT_ID}"

SQL_SERVER   = get_env_var("SQL_SERVER")
SQL_DATABASE = get_env_var("SQL_DATABASE")
SQL_USERNAME = get_env_var("SQL_USERNAME")
SQL_PASSWORD = get_env_var("SQL_PASSWORD")

# === OpenAI Client ===
client = AzureOpenAI(
    api_key=AZURE_OPENAI_API_KEY,
    api_version=OPENAI_API_VERSION,
    azure_endpoint=AZURE_OPENAI_ENDPOINT
)

# === Azure Search Funktion ===
def search_azure(query):
    try:
        headers = {
            "Content-Type": "application/json",
            "api-key": AZURE_SEARCH_KEY,
            "Accept": "application/json;odata.metadata=none"
        }
        url = f"{AZURE_SEARCH_ENDPOINT}/indexes/{AZURE_SEARCH_INDEX}/docs/search?api-version=2023-07-01-Preview"
        body = {"search": query, "top": 5}
        logger.info(f"🔍 Suche: {query}")
        response = requests.post(url, headers=headers, json=body)
        response.raise_for_status()
        results = response.json()
        contents = [doc['content'] for doc in results.get('value', []) if 'content' in doc]
        return "\n---\n".join(contents)
    except Exception:
        logger.error("❌ Azure Search fehlgeschlagen:")
        logger.error(traceback.format_exc())
        return "Fehler bei der Azure-Suche."

# === Datenbankverbindung ===
def insert_into_sql(first_name, last_name, phone, email, symptom, symptom_duration, birthday, appointment_time):
    try:
        conn_str = (
            f"DRIVER={{ODBC Driver 17 for SQL Server}};"
            f"SERVER={SQL_SERVER};"
            f"DATABASE={SQL_DATABASE};"
            f"UID={SQL_USERNAME};PWD={SQL_PASSWORD}"
        )
        with pyodbc.connect(conn_str) as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO appointments (first_name, last_name, phone, email, symptom, symptom_duration, birthday, appointment_time)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (first_name, last_name, phone, email, symptom, symptom_duration, birthday, appointment_time))
                conn.commit()
        logger.info(f"🗂️ SQL gespeichert für {first_name} {last_name}")
    except Exception:
        logger.error("❌ Fehler beim Speichern in SQL:")
        logger.error(traceback.format_exc())

# Hier folgen: Kalender-, GPT- und E-Mail-Funktionen wie in der bestehenden app.py...

# Platzhalter für nächsten Schritt (Terminbuchung + SQL + E-Mail)
@app.route("/book-test", methods=["POST"])
def book_test():
    return jsonify({"status": "bereit für SQL-Speicherung"})
