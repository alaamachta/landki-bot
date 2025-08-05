# app.py – LandKI-Terminassistent v1.0041 – vollständig kommentiert und modularisiert

# === 📦 Imports ===
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

from datetime import datetime, timedelta
from flask import Flask, request, jsonify, session, redirect, url_for
from flask_cors import CORS
from flask_session import Session
from openai import AzureOpenAI
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from msal import ConfidentialClientApplication, SerializableTokenCache
from jwt import decode as jwt_decode

# === 🚀 Flask Setup ===
app = Flask(__name__)
CORS(app,
     origins=["https://it-land.net"],
     supports_credentials=True,
     methods=["GET", "POST", "OPTIONS"],
     allow_headers=["Content-Type", "Authorization"])

app.config["SESSION_COOKIE_SAMESITE"] = "None"
app.config["SESSION_COOKIE_SECURE"] = True
app.secret_key = os.getenv("SECRET_KEY") or os.urandom(24).hex()

# === 💾 Session Konfiguration ===
# Nutzt Dateisystem statt Redis (zukunftssicher, aber nicht verteilt)
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# === 🪵 Logging + Zeitzone ===
berlin_tz = pytz.timezone("Europe/Berlin")
logging.basicConfig(
    level=logging.DEBUG, # vorher war INFO – nun volle Debug-Ausgabe
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout), logging.StreamHandler(sys.stderr)]
)
logger = logging.getLogger("landki")

# === ⚙️ Umgebungsvariablen ===
# ⬇️ Anpassen für zukünftige Module z. B. Exchange, Teams, mehrsprachige Bots
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

# === 🔐 Token-Aktualisierung ===
def refresh_token_if_needed():
    token_cache = SerializableTokenCache()
    if "token_cache" in session:
        token_cache.deserialize(session["token_cache"])
    else:
        logging.warning("⚠️ Kein token_cache in Session gefunden")

    msal_app = ConfidentialClientApplication(
        CLIENT_ID,
        authority=AUTHORITY,
        client_credential=CLIENT_SECRET,
        token_cache=token_cache
    )

    if "access_token" not in session or session.get("token_expires", 0) < time.time() + 300:
        logging.info("🔄 Token abgelaufen oder fehlt – versuche Silent Refresh")
        accounts = msal_app.get_accounts()
        logging.debug(f"🧾 MSAL Accounts gefunden: {accounts}")
        if accounts:
            result = msal_app.acquire_token_silent(SCOPES, account=accounts[0])
            logging.debug(f"🧪 Ergebnis von acquire_token_silent: {result}")
            if result and "access_token" in result:
                session["access_token"] = result["access_token"]
                session["token_expires"] = time.time() + result["expires_in"]
                session["token_cache"] = token_cache.serialize()
                logging.info("✅ Token erneuert – gültig bis %s", session["token_expires"])
                return True
            else:
                logging.warning("⚠️ Silent Refresh fehlgeschlagen oder kein access_token im Result")
        else:
            logging.warning("⚠️ Keine MSAL-Accounts vorhanden – kein Silent Refresh möglich")
        return False

    return True

# === 💬 GPT Chat Endpoint ===
@app.route("/chat", methods=["POST"])
def chat():
    if not refresh_token_if_needed():
        return jsonify({"response": "⚠️ Bitte erneut unter /calendar anmelden – Token abgelaufen."}), 401

    user_input = request.get_json().get("message")
    session_id = session.get("id") or str(uuid.uuid4())
    session["id"] = session_id
    logger.info(f"[CHAT] Session ID: {session_id}, Eingabe: {user_input}")

    # GPT-4o mit Function Calling
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

# 🗓️ ROUTE: Verfügbare Zeiten aus Outlook-Kalender
@app.route("/available-times")
def available_times():
    # 🔐 Token prüfen und ggf. aktualisieren
    if not refresh_token_if_needed():
        return jsonify({"error": "⚠️ Zugriffstoken abgelaufen. Bitte unter /calendar neu anmelden."}), 401

    access_token = session.get("access_token")
    if not access_token:
        return jsonify({"error": "⚠️ Kein Zugriffstoken gefunden."}), 401

    # 🧾 Header für Graph API
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    # 📅 Zeitraum: Heute bis 365 Tage in die Zukunft
    start_time = datetime.now(berlin_tz)
    end_time = start_time + timedelta(days=365)

    # 🔁 Zeitraster: 15-Minuten-Intervalle (werktags von 9–17 Uhr)
    interval = timedelta(minutes=15)
    work_start = 9
    work_end = 17

    current_time = start_time.replace(hour=work_start, minute=0, second=0, microsecond=0)
    slots = []
    while current_time < end_time:
        if current_time.weekday() < 5:
            if work_start <= current_time.hour < work_end:
                slots.append(current_time)
        current_time += interval

    # 📡 Microsoft Graph: Kalenderabfrage mit getSchedule
    outlook_url = "https://graph.microsoft.com/v1.0/me/calendar/getSchedule"
    body = {
        "schedules": ["me"],
        "startTime": {"dateTime": start_time.isoformat(), "timeZone": "Europe/Berlin"},
        "endTime": {"dateTime": end_time.isoformat(), "timeZone": "Europe/Berlin"},
        "availabilityViewInterval": 15
    }

    # 🔄 Belegte Zeiträume abrufen und filtern
    resp = requests.post(outlook_url, headers=headers, json=body)
    busy_slots = set()
    if resp.ok:
        data = resp.json()
        for item in data.get("value", []):
            for schedule_item in item.get("scheduleItems", []):
                start = datetime.fromisoformat(schedule_item["start"].replace("Z", "+00:00")).astimezone(berlin_tz)
                end = datetime.fromisoformat(schedule_item["end"].replace("Z", "+00:00")).astimezone(berlin_tz)
                while start < end:
                    busy_slots.add(start)
                    start += interval

    # ✅ Nur freie Slots zurückgeben
    available = [dt.isoformat() for dt in slots if dt not in busy_slots]
    return jsonify({"slots": available})

# 🧪 ROUTE: Token-Debug (JWT-Analyse)
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

# 📤 E-Mail-Versand via SMTP mit OAuth2
# =============================================
# Diese Funktion sendet E-Mails mit Microsoft-Konto über SMTP und OAuth2.
# Sie nutzt XOAUTH2-Authentifizierung und ist DSGVO-konform, da kein Passwort gespeichert wird.
# Tritt ein Fehler auf (z. B. abgelaufenes Token), wird ein detaillierter Log-Eintrag erstellt.
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

# 📅 Kalender-Login /calendar – OAuth Login-Startpunkt
# =============================================
# Diese Route leitet Benutzer zur Microsoft-Login-Seite weiter,
# um Zugriff auf Kalender-API zu gewähren. Der Redirect erfolgt später zu /callback.
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

# === OAuth2 Callback: Microsoft-Login bestätigt ===
@app.route("/callback")
def authorized():
    # Wenn kein "state" vorhanden ist, ist Session vermutlich abgelaufen (z. B. nach App-Neustart)
    if "state" not in session:
        logging.warning("⚠️ Kein session['state'] – wahrscheinlich Session abgelaufen oder Deploymentneustart")
        return "⚠️ Sitzung abgelaufen. Bitte erneut über /calendar anmelden."

    # Sicherheitsabgleich: passt der zurückgegebene State zu unserem gespeicherten?
    if request.args.get("state") != session.get("state"):
        logging.warning("⚠️ Ungültiger State-Wert im Callback")
        return redirect(url_for("index"))

    # Neues MSAL-App-Objekt (Client + Secret + Authority)
    msal_app = ConfidentialClientApplication(CLIENT_ID, authority=AUTHORITY, client_credential=CLIENT_SECRET)

    # Tausche Authorization-Code gegen Access Token
    result = msal_app.acquire_token_by_authorization_code(
        request.args["code"],
        scopes=["User.Read", "Mail.Send", "Calendars.ReadWrite", "SMTP.Send"], # benötigte Berechtigungen
        redirect_uri=REDIRECT_URI
    )

    # ✅ Wenn Token vorhanden, speichern wir es in die Session für spätere Nutzung (Outlook + SMTP)
    if "access_token" in result:
        session["access_token"] = result["access_token"]               # für Outlook + E-Mail
        session["token_expires"] = time.time() + result["expires_in"]  # Ablaufzeit merken
        return redirect("/token-debug")

    else:
        logging.error("❌ Fehler beim Token-Abruf: %s", result)
        return "Fehler beim Abrufen des Tokens. Siehe Log."

# === Hauptfunktion für Terminbuchung: Outlook + SQL + E-Mail ===
@app.route("/book", methods=["POST"])
def book():
    try:
        data = request.get_json()  # Nutzerdaten vom Chatbot (JSON)
        logging.info("🛠️ /book wurde aufgerufen.")
        token_cache = SerializableTokenCache()
        if "token_cache" in session:
            token_cache.deserialize(session["token_cache"])

        # Token vorbereiten für API-Nutzung (ggf. mit vorhandenem Cache)
        msal_app = ConfidentialClientApplication(
            CLIENT_ID,
            authority=AUTHORITY,
            client_credential=CLIENT_SECRET,
            token_cache=token_cache
        )

        # Token automatisch erneuern, falls nötig
        if not refresh_token_if_needed():
            return jsonify({"error": "⚠️ Token abgelaufen. Bitte neu einloggen."}), 401
        access_token = session.get("access_token")
        if not access_token:
            logging.error("❌ Access Token fehlt – evtl. Session abgelaufen.")
            return jsonify({"error": "Kein Access Token gefunden. Bitte neu einloggen."}), 401
    
        # 🕒 Zeiten vorbereiten
        TZ = pytz.timezone("Europe/Berlin")
        start_time_utc = datetime.fromisoformat(data['selected_time'])
        start_local = start_time_utc.astimezone(TZ)
        end_local = start_local + timedelta(minutes=30)

        # 📅 Terminobjekt für Microsoft Graph vorbereiten
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

        # 📤 Sende Termin an Outlook-Kalender
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

        # 💾 SQL-Speicherung in Azure SQL-Datenbank
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

        # 📧 E-Mail-Versand an Kund*in + Team (SMTP OAuth)
        subject = "Ihre Terminbestätigung"
        html = f"""
        <p>Sehr geehrte*r {data['first_name']} {data['last_name']},</p>
        <p>Ihr Termin ist gebucht:</p>
        <ul><li><strong>Datum:</strong> {start_local.strftime('%d.%m.%Y')}</li>
        <li><strong>Uhrzeit:</strong> {start_local.strftime('%H:%M')} Uhr</li></ul>
        {f'<p><strong>Ihre Nachricht:</strong><br>{data["user_message"]}</p>' if data.get('user_message') else ''}
        <p>Mit freundlichen Grüßen<br>Ihr Team</p>
        """
        
        # ✉️ Empfänger: Kund*in + zentrale Adresse (SMTP_RECIPIENT)
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

# === 🏠 STARTSEITE / ROOT-ROUTE ===
@app.route("/")
def index():
    return "LandKI Bot läuft. Verwenden Sie /calendar oder /chat."

# === 🚨 GLOBALER ERROR HANDLER ===
@app.errorhandler(Exception)
def handle_exception(e):
    # Wird aufgerufen bei unerwarteten Fehlern in jeder Route
    logging.exception("Unerwarteter Fehler: %s", e)
    return jsonify({"error": "Ein interner Fehler ist aufgetreten."}), 500

# === 🧪 LOKALER START DES FLASK SERVERS (nicht auf Azure aktiv!) ===
#if __name__ == "__main__":
    # Lokaler Entwicklungsserver mit Debug-Logs
    #app.run(debug=True) # ❗ Auf Azure wird dieser Block ignoriert (wird von Gunicorn oder Azure-Webserver gestartet)
