# app.py – LandKI-Terminassistent v1.0034 – Optimiert ohne Redis

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
from jwt import decode as jwt_decode

app = Flask(__name__)
CORS(app, origins=["https://it-land.net"], supports_credentials=True)
app.config["SESSION_COOKIE_SAMESITE"] = "None"
app.config["SESSION_COOKIE_SECURE"] = True
app.secret_key = os.getenv("SECRET_KEY") or os.urandom(24).hex()

# Kein Redis, nur Filesystem
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Logging + Zeitzone
berlin_tz = pytz.timezone("Europe/Berlin")
logging.basicConfig(
    level=logging.DEBUG, # vorher war INFO – nun volle Debug-Ausgabe
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout), logging.StreamHandler(sys.stderr)]
)
logger = logging.getLogger("landki")

# Umgebungsvariablen laden
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

# ✅ Token automatisch erneuern, wenn nötig
def refresh_token_if_needed():
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
        logging.info("🔄 Token abgelaufen oder fehlt – versuche Silent Refresh")
        accounts = msal_app.get_accounts()
        if accounts:
            result = msal_app.acquire_token_silent(SCOPES, account=accounts[0])
            if "access_token" in result:
                session["access_token"] = result["access_token"]
                session["token_expires"] = time.time() + result["expires_in"]
                session["token_cache"] = token_cache.serialize()
                logging.info("✅ Token erneuert – gültig bis %s", session["token_expires"])
                return True
            else:
                logging.warning("⚠️ Silent Refresh fehlgeschlagen")
        else:
            logging.warning("⚠️ Keine Accounts für Silent Refresh")
        return False

    return True

@app.route("/chat", methods=["POST"])
def chat():
    if not refresh_token_if_needed():
        return jsonify({"response": "⚠️ Bitte erneut unter /calendar anmelden – Token abgelaufen."}), 401

    user_input = request.get_json().get("message")
    session_id = session.get("id") or str(uuid.uuid4())
    session["id"] = session_id
    logger.info(f"[CHAT] Session ID: {session_id}, Eingabe: {user_input}")

    client = AzureOpenAI(
        api_key=AZURE_OPENAI_KEY,
        api_version=OPENAI_API_VERSION,
        azure_endpoint=AZURE_OPENAI_ENDPOINT
    )

    response = client.chat.completions.create(
        model=AZURE_OPENAI_DEPLOYMENT,
        temperature=0.2,
        messages=[
            {"role": "system", "content": "Du bist ein deutschsprachiger, empathischer Terminassistent."},
            {"role": "user", "content": user_input},
        ],
        tools=[{
            "type": "function",
            "function": {
                "name": "book_appointment",
                "description": "Bucht einen Termin",
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
        }],
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
                        return jsonify({"response": "⚠️ Bitte erneut unter /calendar anmelden."})
                    else:
                        return jsonify({"response": f"⚠️ Fehler: {result.get('error', 'Unbekannt')}"})

    return jsonify({"response": choice.message.content})

@app.route("/available-times")
def available_times():
    if not refresh_token_if_needed():
        return jsonify({"error": "⚠️ Zugriffstoken abgelaufen. Bitte unter /calendar neu anmelden."}), 401

    access_token = session.get("access_token")
    if not access_token:
        return jsonify({"error": "⚠️ Kein Zugriffstoken gefunden."}), 401

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Prefer": 'outlook.timezone="Europe/Berlin"'
    }

    # Zeitraum: 1 Jahr im Voraus
    now = datetime.now(berlin_tz)
    start_time = now.replace(hour=9, minute=0, second=0, microsecond=0)
    end_time = now + timedelta(days=365)
    end_time = end_time.replace(hour=17, minute=0, second=0, microsecond=0)

    # Schrittweise abrufen: MS Graph erlaubt nur ca. 30 Tage pro Abfrage
    interval_days = 30
    busy_slots = []

    for offset in range(0, 365, interval_days):
        period_start = start_time + timedelta(days=offset)
        period_end = min(start_time + timedelta(days=offset + interval_days), end_time)

        url = (
            f"https://graph.microsoft.com/v1.0/me/calendarview"
            f"?startdatetime={period_start.isoformat()}&enddatetime={period_end.isoformat()}"
            f"&$orderby=start/dateTime"
        )

        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            logging.error("❌ Fehler beim Kalenderabruf: %s", response.text)
            continue

        for event in response.json().get("value", []):
            start = datetime.fromisoformat(event["start"]["dateTime"])
            end = datetime.fromisoformat(event["end"]["dateTime"])
            busy_slots.append((start, end))

    # Slots generieren: 15-minütig, nur Mo–Fr, 09–17 Uhr
    free_slots = []
    current = start_time
    while current < end_time:
        if current.weekday() < 5:  # Mo–Fr
            slot_end = current + timedelta(minutes=15)
            if not any(start < slot_end and current < end for start, end in busy_slots):
                free_slots.append(current.isoformat())
        current += timedelta(minutes=15)

    logging.info("📅 %s freie Slots im Jahr gefunden", len(free_slots))
    return jsonify({"slots": free_slots})


@app.route("/token-debug")
def token_debug():
    token = session.get("access_token")
    if not token:
        return "⚠️ Kein Token gefunden. Bitte zuerst unter /calendar anmelden."

    try:
        decoded = jwt_decode(token, options={"verify_signature": False})
    except Exception as e:
        return f"Fehler beim Decodieren: {e}"

    scopes = decoded.get("scp", "Keine Scope-Angabe im Token")
    expires_at_unix = session.get("token_expires", 0)
    expires_at = datetime.fromtimestamp(expires_at_unix, tz=berlin_tz).strftime("%Y-%m-%d %H:%M:%S %Z")

    html = f"""
        <h2>Token-Debug</h2>
        <h3>Access Token:</h3>
        <textarea rows='6' cols='100'>{token}</textarea>
        <h3>Scopes im Token (scp):</h3>
        <pre>{scopes}</pre>
        <h3>Gültig bis:</h3>
        <pre>{expires_at}</pre>
        <h3>Kompletter JWT Payload (decoded):</h3>
        <pre>{json.dumps(decoded, indent=2)}</pre>
    """
    return html

@app.route("/")
def index():
    return "LandKI Bot läuft. Verwenden Sie /calendar oder /chat."


# ✅ Globale Funktion für E-Mail-Versand via SMTP OAuth2
def send_oauth_email(sender, recipient, msg, access_token):
    try:
        auth_string = f"user={sender}\x01auth=Bearer {access_token}\x01\x01"
        auth_bytes = base64.b64encode(auth_string.encode("utf-8")).decode("utf-8")
        
        with smtplib.SMTP("smtp.office365.com", 587, timeout=10) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()

            code, response = server.docmd("AUTH", "XOAUTH2 " + auth_bytes)
            if code != 235:
                raise smtplib.SMTPAuthenticationError(code, response)

            server.sendmail(sender, recipient, msg.as_string())
            logging.info(f"✅ E-Mail an {recipient} gesendet via SMTP OAuth2")
    except smtplib.SMTPAuthenticationError as auth_err:
        logging.error(f"❌ AUTH-Fehler beim E-Mail-Versand: {auth_err.smtp_code} - {auth_err.smtp_error.decode()}")
        raise
    except Exception as e:
        logging.exception(f"❌ Allgemeiner Fehler beim SMTP-Versand an {recipient}")
        raise

# ✅ Optimierte Route: /calendar (mit Logging & Fehlerprüfung)
@app.route("/calendar")
def calendar():
    if app.debug:
        logging.debug("🎯 CLIENT_ID: %s", CLIENT_ID)
        logging.debug("🎯 REDIRECT_URI: %s", REDIRECT_URI)
        logging.debug("🎯 CLIENT_SECRET gesetzt: %s", bool(CLIENT_SECRET))  # nur lokal

    try:
        msal_app = ConfidentialClientApplication(
            CLIENT_ID,
            authority=AUTHORITY,
            client_credential=CLIENT_SECRET
        )

        state = str(uuid.uuid4())
        session["state"] = state

        auth_url = msal_app.get_authorization_request_url(
            scopes=SCOPES,
            state=state,
            redirect_uri=REDIRECT_URI
        )

        logging.info("🔐 Weiterleitung zu Microsoft Login: %s", auth_url)
        return redirect(auth_url)

    except Exception as e:
        logging.exception("❌ Fehler in /calendar: %s", str(e))
        return f"<pre>Fehler in /calendar: {str(e)}</pre>", 500


@app.route("/callback")
def authorized():
    if "state" not in session:
        logging.warning("⚠️ Kein session['state'] – wahrscheinlich Session abgelaufen oder Deploymentneustart")
        return "⚠️ Sitzung abgelaufen. Bitte erneut über /calendar anmelden."

    if request.args.get("state") != session.get("state"):
        logging.warning("⚠️ Ungültiger State-Wert im Callback")
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

        if not refresh_token_if_needed(msal_app, token_cache):
            return jsonify({"error": "⚠️ Token abgelaufen. Bitte neu einloggen."}), 401
            
        
        access_token = session.get("access_token")
        if not access_token:
            logging.error("❌ Access Token fehlt – evtl. Session abgelaufen.")
            return jsonify({"error": "Kein Access Token gefunden. Bitte neu einloggen."}), 401
    
        # 🔍 Debugging: Länge und Ausschnitt vom Token anzeigen
        logging.info(f"📧 Access Token geladen. Start: {access_token[:20]}... Länge: {len(access_token)}")
        logging.info(f"📧 Access Token SMTP beginnt mit: {access_token[:25]}... (Länge: {len(access_token)})")
        


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
            "attendees": [
                {
                    "emailAddress": {"address": data["email"], "name": f"{data['first_name']} {data['last_name']}"},
                    "type": "required"
                }
            ]

        }

        logging.info(f"🗓️ Versuche Outlook-Termin zu erstellen: {start_local} – {end_local}")
        resp = requests.post(
            'https://graph.microsoft.com/v1.0/me/events',
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            json=event
        )
        if resp.status_code != 201:
            logging.error(f"❌ Outlook Fehler {resp.status_code}: {resp.text}")
            return jsonify({
                "error": f"Fehler beim Kalender-Eintrag: {resp.status_code}",
                "details": resp.text
            }), 500


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
        
                send_oauth_email(SMTP_SENDER, rcp, msg, access_token)
        
            except Exception as e:
                logging.exception(f"❌ Fehler beim Senden an {rcp}")





        return jsonify({"status": "success", "message": "Termin gebucht."})

    except Exception as e:
        logging.exception("❌ Allgemeiner Fehler bei Terminbuchung")
        return jsonify({"error": f"Fehler bei der Buchung: {str(e)}"}), 500

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200
        
    # ✅ Token-Ablaufzeit aus Session interpretieren
    expires_at_unix = session.get("token_expires", 0)
    expires_at = datetime.fromtimestamp(expires_at_unix, tz=berlin_tz).strftime("%Y-%m-%d %H:%M:%S %Z")

    html = f"""
        <h3>Access Token:</h3>
        <textarea rows='6' cols='100'>{token}</textarea>
        <h3>Scopes im Token (scp):</h3>
        <pre>{scopes}</pre>
        <h3>Gültig bis:</h3>
        <pre>{expires_at}</pre>
        <h3>Kompletter JWT Payload (decoded):</h3>
        <pre>{decoded}</pre>
    """
    return html

@app.route("/")
def index():
    return "LandKI Bot läuft. Verwenden Sie /calendar oder /chat."


# Globaler Error Handler
@app.errorhandler(Exception)
def handle_exception(e):
    logging.exception("Unerwarteter Fehler: %s", e)
    return jsonify({"error": "Ein interner Fehler ist aufgetreten."}), 500

# Starte Server nur lokal (nicht auf Azure)
if __name__ == "__main__":
    app.run(debug=True)
