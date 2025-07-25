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
import pytz
import pyodbc
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from msal import ConfidentialClientApplication

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

# === ENV-Variablen ===
def get_env_var(name, required=True):
    value = os.getenv(name)
    if not value and required:
        logger.error(f"❌ ENV fehlt: {name}")
        raise EnvironmentError(f"Missing environment variable: {name}")
    return value

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
MS_SCOPES                = ["Calendars.Read", "Calendars.ReadWrite"]
MS_AUTHORITY             = f"https://login.microsoftonline.com/{MS_TENANT_ID}"

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

@app.route("/")
def root():
    return "✅ LandKI GPT-4o läuft!"

@app.route("/env-debug")
def env_debug():
    return jsonify({
        "AZURE_OPENAI_API_KEY": bool(os.getenv("AZURE_OPENAI_API_KEY")),
        "AZURE_OPENAI_ENDPOINT": os.getenv("AZURE_OPENAI_ENDPOINT"),
        "AZURE_OPENAI_DEPLOYMENT": os.getenv("AZURE_OPENAI_DEPLOYMENT"),
        "OPENAI_API_VERSION": OPENAI_API_VERSION
    })

@app.route("/chat", methods=["POST"])
def chat():
    try:
        user_input = request.json.get("message", "")
        logger.info(f"👤 Frage: {user_input}")
        context = search_azure(user_input)
        prompt = f"Nutze diesen Kontext zur Beantwortung:\n{context}\n\nFrage: {user_input}\nAntwort:"

        response = client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2
        )

        answer = response.choices[0].message.content
        logger.info(f"✅ GPT-Antwort: {answer[:100]}...")
        return jsonify({
            "response": answer,
            "reply_html": markdown2.markdown(answer)
        })

    except Exception:
        logger.error("❌ Fehler im Chat:")
        logger.error(traceback.format_exc())
        return jsonify({"error": "Fehler beim Chat"}), 500

# ... weitere Funktionen folgen wie in deinem vollständigen Code (Outlook, SQL, book_appointment usw.)
# Wenn du willst, teile ich die Datei gern in Blöcken oder erweitere um weitere Debug-Stellen.
