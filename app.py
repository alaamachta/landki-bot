# app.py – LandKI-Terminassistent v1.0029 – SMTP XOAUTH2 Fix + Logging Cleanup

import os
import uuid
import json
import logging
import requests
import smtplib
import pytz
import pyodbc
import base64
import time
import sys

from flask import Flask, request, jsonify, session, redirect, url_for
from flask_cors import CORS
from flask_session import Session
from openai import AzureOpenAI
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from msal import ConfidentialClientApplication, SerializableTokenCache

# === Flask-Konfiguration ===
app = Flask(__name__)
CORS(app, origins=["https://it-land.net"], supports_credentials=True)
app.config["SESSION_COOKIE_SAMESITE"] = "None"
app.config["SESSION_COOKIE_SECURE"] = True
app.secret_key = os.getenv("SECRET_KEY") or os.urandom(24).hex()
app.config["SESSION_TYPE"] = "filesystem"
app.config["SESSION_FILE_DIR"] = "/tmp/flask_session"
Session(app)

# === Logging ===
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("landki")
TZ = pytz.timezone("Europe/Berlin")

# === Umgebungsvariablen ===
SQL_SERVER = os.getenv("SQL_SERVER")
SQL_DB = os.getenv("SQL_DATABASE")
SQL_USER = os.getenv("SQL_USERNAME")
SQL_PASSWORD = os.getenv("SQL_PASSWORD")
AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_KEY")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")
OPENAI_API_VERSION = os.getenv("OPENAI_API_VERSION", "2024-10-21")
SMTP_SENDER = os.getenv("EMAIL_SENDER")
SMTP_RECIPIENT = "info@landki.com"
CLIENT_ID = os.getenv("MS_CLIENT_ID")
CLIENT_SECRET = os.getenv("MS_CLIENT_SECRET")
TENANT_ID = os.getenv("MS_TENANT_ID")
REDIRECT_URI = os.getenv("MS_REDIRECT_URI") or "https://landki-bot-app-hrbtfefhgvasc5gk.germanywestcentral-01.azurewebsites.net/callback"
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
SCOPES = [
    "https://graph.microsoft.com/Calendars.ReadWrite",
    "https://graph.microsoft.com/User.Read",
    "https://graph.microsoft.com/Mail.Send",
    "https://outlook.office365.com/SMTP.Send"
]

# === Kalender-Login ===
@app.route("/calendar")
def calendar():
    try:
        msal_app = ConfidentialClientApplication(CLIENT_ID, authority=AUTHORITY, client_credential=CLIENT_SECRET)
        state = str(uuid.uuid4())
        session["state"] = state
        auth_url = msal_app.get_authorization_request_url(
            scopes=SCOPES,
            state=state,
            redirect_uri=REDIRECT_URI
        )
        return redirect(auth_url)
    except Exception as e:
        logger.exception("Fehler in /calendar")
        return f"<pre>Fehler in /calendar: {str(e)}</pre>", 500

@app.route("/callback")
def authorized():
    if request.args.get("state") != session.get("state"):
        return redirect(url_for("index"))

    msal_app = ConfidentialClientApplication(CLIENT_ID, authority=AUTHORITY, client_credential=CLIENT_SECRET)
    result = msal_app.acquire_token_by_authorization_code(
        request.args["code"],
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI
    )

    if "access_token" in result:
        session["access_token"] = result["access_token"]
        session["token_expires"] = time.time() + result["expires_in"]
        session["token_cache"] = msal_app.token_cache.serialize()
        return redirect("/token-debug")
    else:
        logger.error("Token-Abruf fehlgeschlagen: %s", result)
        return "Fehler beim Abrufen des Tokens. Siehe Log."

# === Debug ===
@app.route("/token-debug")
def token_debug():
    token = session.get("access_token")
    if not token:
        return "Kein Token gespeichert. Bitte /calendar erneut aufrufen."
    try:
        import jwt
        decoded = jwt.decode(token, options={"verify_signature": False})
        scopes = decoded.get("scp", "Nicht angegeben")
        return f"""
            <h3>Token:</h3>
            <textarea rows=6 cols=100>{token}</textarea>
            <h3>Scopes:</h3><pre>{scopes}</pre>
            <h3>Payload:</h3><pre>{decoded}</pre>
        """
    except Exception as e:
        return f"Fehler beim Decodieren: {e}"

@app.route("/")
def index():
    return "LandKI Bot läuft – /calendar oder /chat verwenden."
