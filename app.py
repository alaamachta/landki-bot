# app.py – LandKI-Terminassistent v1.0028 – OAuth2 mit robuster Fehlerbehandlung und Token-Refresh

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

berlin_tz = pytz.timezone("Europe/Berlin")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger(__name__)

SQL_SERVER = os.environ.get("SQL_SERVER")
SQL_DB = os.environ.get("SQL_DATABASE")
SQL_USER = os.environ.get("SQL_USERNAME")
SQL_PASSWORD = os.environ.get("SQL_PASSWORD")
SMTP_SENDER = os.environ.get("EMAIL_SENDER")
if not SMTP_SENDER:
    raise EnvironmentError("EMAIL_SENDER ist nicht gesetzt.")
SMTP_RECIPIENT = "info@landki.com"
AZURE_OPENAI_KEY = os.environ.get("AZURE_OPENAI_KEY")
AZURE_OPENAI_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_DEPLOYMENT = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
OPENAI_API_VERSION = os.environ.get("OPENAI_API_VERSION", "2024-10-21")

CLIENT_ID = os.environ.get("MS_CLIENT_ID")
CLIENT_SECRET = os.environ.get("MS_CLIENT_SECRET")
TENANT_ID = os.environ.get("MS_TENANT_ID")
REDIRECT_URI = os.environ.get("MS_REDIRECT_URI") or "https://landki-bot-app-hrbtfefhgvasc5gk.germanywestcentral-01.azurewebsites.net/callback"
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
SCOPES = ["https://graph.microsoft.com/Calendars.ReadWrite", "https://graph.microsoft.com/User.Read", "https://graph.microsoft.com/Mail.Send", "https://outlook.office365.com/SMTP.Send"]

@app.route("/calendar")
def calendar():
    msal_app = ConfidentialClientApplication(CLIENT_ID, authority=AUTHORITY, client_credential=CLIENT_SECRET)
    state = str(uuid.uuid4())
    session["state"] = state
    auth_url = msal_app.get_authorization_request_url(
        scopes=["User.Read", "Mail.Send", "Calendars.ReadWrite", "SMTP.Send"],  # explizit, damit nichts fehlt
        state=state,
        redirect_uri=REDIRECT_URI
    )
    logging.info("🔐 Weiterleitung zu Microsoft Login: " + auth_url)
    return redirect(auth_url)


@app.route("/callback")
def authorized():
    if request.args.get("state") != session.get("state"):
        return redirect(url_for("index"))

    msal_app = ConfidentialClientApplication(CLIENT_ID, authority=AUTHORITY, client_credential=CLIENT_SECRET)

    result = msal_app.acquire_token_by_authorization_code(
        request.args["code"],
        scopes=["User.Read", "Mail.Send", "Calendars.ReadWrite", "SMTP.Send"],
        redirect_uri=REDIRECT_URI
    )

    if "access_token" in result:
        session["access_token"] = result["access_token"]               # für Outlook + E-Mail
        session["token_expires"] = time.time() + result["expires_in"]  # Ablaufzeit merken
        session["token_cache"] = msal_app.token_cache.serialize()      # Cache für später
        return redirect("/token-debug")

    else:
        logging.error("❌ Fehler beim Token-Abruf: %s", result)
        return "Fehler beim Abrufen des Tokens. Siehe Log."


@app.route("/chat", methods=["POST"])
def chat():
    try:
        user_input = request.get_json()["message"]
        session_id = session.get("id") or str(uuid.uuid4())
        session["id"] = session_id
        logger.info(f"[CHAT] Session ID: {session_id}, Eingabe: {user_input}")

        client = AzureOpenAI(api_key=AZURE_OPENAI_KEY, api_version=OPENAI_API_VERSION, azure_endpoint=AZURE_OPENAI_ENDPOINT)

        response = client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,
            temperature=0.2,
            messages=[
                {"role": "system", "content": "Du bist ein freundlicher deutschsprachiger Terminassistent. Bitte hilf dem Nutzer, einen Termin zu buchen. Nutze Function Calling, wenn alle Daten vorliegen."},
                {"role": "user", "content": user_input},
            ],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "book_appointment",
                        "description": "Bucht einen Termin in Outlook, speichert ihn in SQL und versendet E-Mails",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "first_name": {"type": "string"},
                                "last_name": {"type": "string"},
                                "email": {"type": "string"},
                                "selected_time": {"type": "string", "format": "date-time"},
                                "user_message": {"type": "string"}
                            },
                            "required": ["first_name", "last_name", "email", "selected_time"]
                        }
                    }
                }
            ],
            tool_choice="auto"
        )

        choice = response.choices[0]

        if choice.finish_reason == "tool_calls" and choice.message.tool_calls:
            for tool_call in choice.message.tool_calls:
                if tool_call.function.name == "book_appointment":
                    args = json.loads(tool_call.function.arguments)
                    with app.test_client() as client:
                        with client.session_transaction() as sess:
                            sess.update(session)
                        book_resp = client.post("/book", json=args)
                        result = book_resp.get_json()
                        if book_resp.status_code == 200:
                            return jsonify({"response": "✅ Termin erfolgreich gebucht."})
                        elif book_resp.status_code == 401:
                            return jsonify({"response": "⚠️ Bitte melde dich neu an unter /calendar – der Zugriffstoken ist abgelaufen."})
                        else:
                            return jsonify({"response": f"⚠️ Fehler: {result.get('error', 'Unbekannt')}"})

        return jsonify({"response": choice.message.content})

    except Exception as e:
        logging.exception("Fehler im /chat-Endpunkt")
        return jsonify({"error": str(e)}), 500

@app.route("/book", methods=["POST"])
def book():
    try:
        data = request.get_json()
        logging.info("🛠️ /book wurde aufgerufen.")
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
                    logging.warning("⚠️ Silent Refresh fehlgeschlagen")
                    return jsonify({"error": "⚠️ Token abgelaufen. Bitte neu einloggen."}), 401

        access_token = session["access_token"]
        TZ = pytz.timezone("Europe/Berlin")
        start_time_utc = datetime.fromisoformat(data['selected_time'])
        start_local = start_time_utc.astimezone(TZ)
        end_local = start_local + timedelta(minutes=30)

        event = {
            "subject": f"Termin: {data['first_name']} {data['last_name']}",
            "start": {"dateTime": start_local.isoformat(), "timeZone": "Europe/Berlin"},
            "end": {"dateTime": end_local.isoformat(), "timeZone": "Europe/Berlin"},
            "body": {"contentType": "HTML", "content": data.get('user_message', '')},
            "location": {"displayName": "LandKI Kalender"},
            "attendees": []
        }

        logging.info(f"🗓️ Versuche Outlook-Termin zu erstellen: {start_local} – {end_local}")
        resp = requests.post(
            'https://graph.microsoft.com/v1.0/me/events',
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            json=event
        )
        if resp.status_code != 201:
            logging.error(f"❌ Outlook Fehler {resp.status_code}: {resp.text}")
            return jsonify({"error": f"Fehler beim Kalender-Eintrag: {resp.status_code}"}), 500

        try:
            logging.info("💾 Speichere Termin in SQL-Datenbank...")
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
                start_local, end_local, "LANDKI", "GPT-FC", data.get('user_message')
            ))
            conn.commit()
            cur.close()
            conn.close()
            logging.info("✅ SQL-Eintrag erfolgreich.")
        except Exception as sql_error:
            logging.exception("❌ Fehler beim SQL-Eintrag")
            return jsonify({"error": f"SQL-Fehler: {str(sql_error)}"}), 500

        subject = "Ihre Terminbestätigung"
        html = f"""
        <p>Sehr geehrte*r {data['first_name']} {data['last_name']},</p>
        <p>Ihr Termin ist gebucht:</p>
        <ul><li><strong>Datum:</strong> {start_local.strftime('%d.%m.%Y')}</li>
        <li><strong>Uhrzeit:</strong> {start_local.strftime('%H:%M')} Uhr</li></ul>
        {f'<p><strong>Ihre Nachricht:</strong><br>{data["user_message"]}</p>' if data.get('user_message') else ''}
        <p>Mit freundlichen Grüßen<br>Ihr Team</p>
        """

        for rcp in [data['email'], SMTP_RECIPIENT]:
            try:
                logging.info(f"📧 Sende E-Mail an {rcp}")
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
                logging.info(f"✅ E-Mail an {rcp} gesendet.")
            except Exception as email_error:
                logging.exception(f"❌ Fehler beim Senden der E-Mail an {rcp}")
                return jsonify({"error": f"E-Mail-Fehler: {str(email_error)}"}), 500

        return jsonify({"status": "success", "message": "Termin gebucht."})

    except Exception as e:
        logging.exception("❌ Allgemeiner Fehler bei Terminbuchung")
        return jsonify({"error": f"Fehler bei der Buchung: {str(e)}"}), 500

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200




# === Token-Debug ===
@app.route("/token-debug")
def token_debug():
    token = session.get("access_token")  # Holt gespeicherten Token aus Session
    if not token:
        return "Kein Token gefunden. Bitte zuerst unter /calendar anmelden."

    access_token = token
    if not access_token:
        return "Access Token fehlt im gespeicherten Token."

    # Optional: JWT-Analyse vorbereiten (unsigniert)
    import jwt
    try:
        decoded = jwt.decode(access_token, options={"verify_signature": False})
    except Exception as e:
        return f"Fehler beim Decodieren: {e}"

    # Klartext-Ausgabe
    scopes = decoded.get("scp", "Keine Scope-Angabe im Token")
    html = f"""
        <h3>Access Token:</h3>
        <textarea rows='6' cols='100'>{access_token}</textarea>
        <h3>Scopes im Token (scp):</h3>
        <pre>{scopes}</pre>
        <h3>Kompletter JWT Payload (decoded):</h3>
        <pre>{decoded}</pre>
    """
    return html

