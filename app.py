# app.py – LandKI-Terminassistent v1.0030 – mit /book Outlook+SQL+Mail wiederhergestellt

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
import jwt

from flask import Flask, request, jsonify, session, redirect, url_for
from flask_cors import CORS
from flask_session import Session
from openai import AzureOpenAI
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from msal import ConfidentialClientApplication, SerializableTokenCache

app = Flask(__name__)
CORS(app, origins=["https://it-land.net"], supports_credentials=True)
app.config["SESSION_COOKIE_SAMESITE"] = "None"
app.config["SESSION_COOKIE_SECURE"] = True
app.secret_key = os.getenv("SECRET_KEY") or os.urandom(24).hex()
app.config["SESSION_TYPE"] = "filesystem"
app.config["SESSION_FILE_DIR"] = "/tmp/flask_session"
Session(app)

berlin_tz = pytz.timezone("Europe/Berlin")
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout), logging.StreamHandler(sys.stderr)]
)
logger = logging.getLogger("landki")

SQL_SERVER = os.environ.get("SQL_SERVER")
SQL_DB = os.environ.get("SQL_DATABASE")
SQL_USER = os.environ.get("SQL_USERNAME")
SQL_PASSWORD = os.environ.get("SQL_PASSWORD")
SMTP_SENDER = os.environ.get("EMAIL_SENDER")
SMTP_RECIPIENT = "info@landki.com"
AZURE_OPENAI_KEY = os.environ.get("AZURE_OPENAI_KEY")
AZURE_OPENAI_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_DEPLOYMENT = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
OPENAI_API_VERSION = os.environ.get("OPENAI_API_VERSION", "2024-10-21")

CLIENT_ID = os.environ.get("MS_CLIENT_ID")
CLIENT_SECRET = os.environ.get("MS_CLIENT_SECRET")
TENANT_ID = os.environ.get("MS_TENANT_ID")
REDIRECT_URI = os.environ.get("MS_REDIRECT_URI")
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
SCOPES = [
    "https://graph.microsoft.com/Calendars.ReadWrite",
    "https://graph.microsoft.com/User.Read",
    "https://graph.microsoft.com/Mail.Send",
    "https://outlook.office365.com/SMTP.Send"
]

@app.route("/book", methods=["POST"])
def book():
    try:
        data = request.get_json()
        logger.info("🛠️ /book aufgerufen – Terminbuchung wird gestartet")

        token_cache = SerializableTokenCache()
        if "token_cache" in session:
            token_cache.deserialize(session["token_cache"])

        msal_app = ConfidentialClientApplication(
            CLIENT_ID,
            authority=AUTHORITY,
            client_credential=CLIENT_SECRET,
            token_cache=token_cache
        )

        if "access_token" not in session or session.get("token_expires", 0) < time.time() + 300:
            accounts = msal_app.get_accounts()
            if accounts:
                result = msal_app.acquire_token_silent(SCOPES, account=accounts[0])
                if "access_token" in result:
                    session["access_token"] = result["access_token"]
                    session["token_expires"] = time.time() + result["expires_in"]
                    session["token_cache"] = token_cache.serialize()
                else:
                    logger.warning("⚠️ Silent Refresh fehlgeschlagen")
                    return jsonify({"error": "Token abgelaufen – bitte neu anmelden."}), 401

        access_token = session["access_token"]
        TZ = pytz.timezone("Europe/Berlin")
        start = datetime.fromisoformat(data['selected_time']).astimezone(TZ)
        end = start + timedelta(minutes=30)

        outlook_event = {
            "subject": f"Termin: {data['first_name']} {data['last_name']}",
            "start": {"dateTime": start.isoformat(), "timeZone": "Europe/Berlin"},
            "end": {"dateTime": end.isoformat(), "timeZone": "Europe/Berlin"},
            "body": {"contentType": "HTML", "content": data.get("user_message", "")},
            "location": {"displayName": "LandKI Kalender"},
            "attendees": []
        }

        response = requests.post(
            "https://graph.microsoft.com/v1.0/me/events",
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            json=outlook_event
        )

        if response.status_code != 201:
            logger.error(f"Outlook Fehler {response.status_code}: {response.text}")
            return jsonify({"error": f"Fehler beim Kalender-Eintrag: {response.status_code}"}), 500

        logger.info("📅 Outlook-Termin erfolgreich erstellt")

        conn = pyodbc.connect(
            f"DRIVER={{ODBC Driver 18 for SQL Server}};SERVER={SQL_SERVER};DATABASE={SQL_DB};"
            f"UID={SQL_USER};PWD={SQL_PASSWORD};Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
        )
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO dbo.appointments (
                first_name, last_name, email,
                appointment_start, appointment_end, created_at,
                company_code, bot_origin, user_message
            ) VALUES (?, ?, ?, ?, ?, SYSDATETIMEOFFSET(), ?, ?, ?)
        """, (
            data['first_name'], data['last_name'], data['email'],
            start, end, "LANDKI", "GPT-FC", data.get('user_message')
        ))
        conn.commit()
        cur.close()
        conn.close()
        logger.info("💾 SQL-Eintrag erfolgreich gespeichert")

        subject = "Ihre Terminbestätigung"
        html = f"""
        <p>Sehr geehrte*r {data['first_name']} {data['last_name']},</p>
        <p>Ihr Termin ist gebucht am <strong>{start.strftime('%d.%m.%Y')} um {start.strftime('%H:%M')} Uhr</strong>.</p>
        {f'<p><strong>Ihre Nachricht:</strong><br>{data["user_message"]}</p>' if data.get("user_message") else ''}
        <p>Mit freundlichen Grüßen<br>Ihr Team</p>
        """

        for rcp in [data['email'], SMTP_RECIPIENT]:
            try:
                msg = MIMEMultipart()
                msg['From'] = SMTP_SENDER
                msg['To'] = rcp
                msg['Subject'] = subject
                msg.attach(MIMEText(html, 'html'))

                def send_oauth_email(sender, recipient, msg, access_token):
                    auth_string = f"user={sender}\x01auth=Bearer {access_token}\x01\x01"
                    auth_bytes = base64.b64encode(auth_string.encode("utf-8"))
                    with smtplib.SMTP("smtp.office365.com", 587) as s:
                        s.starttls()
                        s.docmd("AUTH", "XOAUTH2 " + auth_bytes.decode("utf-8"))
                        s.sendmail(sender, recipient, msg.as_string())

                send_oauth_email(SMTP_SENDER, rcp, msg, access_token)
                logger.info(f"✅ E-Mail gesendet an {rcp}")

            except Exception as email_error:
                logger.exception(f"E-Mail-Fehler an {rcp}")
                return jsonify({"error": f"E-Mail-Fehler: {str(email_error)}"}), 500

        return jsonify({"status": "success", "message": "Termin erfolgreich gebucht."})

    except Exception as e:
        logger.exception("Fehler in /book")
        return jsonify({"error": f"Buchungsfehler: {str(e)}"}), 500
