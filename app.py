# app.py – LandKI-Terminassistent v1.0024 – Outlook Session Debug integriert

from flask import Flask, request, jsonify, session, redirect, url_for
from openai import AzureOpenAI
import os, logging, uuid, requests, pytz, pyodbc, smtplib, json
from datetime import datetime, timedelta
from flask_cors import CORS
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from msal import ConfidentialClientApplication

# === Flask Setup ===
app = Flask(__name__)
CORS(app,
     origins=["https://it-land.net"],
     supports_credentials=True)
app.secret_key = os.getenv("SECRET_KEY") or os.urandom(24).hex()

# 🔒 Session-Cookie für Cross-Origin
app.config.update({
    "SESSION_COOKIE_SAMESITE": "None",
    "SESSION_COOKIE_SECURE": True
})

# === Logging Setup ===
logging.basicConfig(
    level=os.environ.get("WEBSITE_LOGGING_LEVEL", "INFO"),
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler()]
)

# === Konfiguration ===
TZ = pytz.timezone("Europe/Berlin")
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

# === MSAL Konfiguration ===
CLIENT_ID = os.environ.get("MS_CLIENT_ID")
CLIENT_SECRET = os.environ.get("MS_CLIENT_SECRET")
TENANT_ID = os.environ.get("MS_TENANT_ID")
REDIRECT_URI = os.environ.get("MS_REDIRECT_URI") or "https://landki-bot-app-hrbtfefhgvasc5gk.germanywestcentral-01.azurewebsites.net/callback"
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
SCOPES = ["https://graph.microsoft.com/Calendars.ReadWrite", "https://graph.microsoft.com/User.Read"]

# === Outlook Login ===
@app.route("/calendar")
def calendar():
    msal_app = ConfidentialClientApplication(
        CLIENT_ID,
        authority=AUTHORITY,
        client_credential=CLIENT_SECRET
    )
    state = str(uuid.uuid4())
    session["state"] = state
    auth_url = msal_app.get_authorization_request_url(SCOPES, state=state, redirect_uri=REDIRECT_URI)
    logging.info("🔐 Weiterleitung zu Microsoft Login: " + auth_url)
    return redirect(auth_url)

@app.route("/callback")
def authorized():
    if request.args.get("state") != session.get("state"):
        return "⚠️ Sitzung abgelaufen oder ungültig. Bitte neu starten.", 400

    code = request.args.get("code")
    if not code:
        return "⚠️ Kein Autorisierungscode erhalten.", 400

    msal_app = ConfidentialClientApplication(
        CLIENT_ID,
        authority=AUTHORITY,
        client_credential=CLIENT_SECRET
    )
    result = msal_app.acquire_token_by_authorization_code(
        code,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI
    )

    if "access_token" in result:
        session["access_token"] = result["access_token"]
        logging.info("✅ Zugriffstoken erfolgreich gespeichert.")
        return "✅ Outlook-Login erfolgreich. Du kannst nun zurück zum Chat."
    else:
        logging.error("❌ Fehler beim Login: " + json.dumps(result, indent=2))
        return "❌ Fehler beim Abrufen des Tokens. Siehe Log.", 500

# === GPT Chat Endpoint ===
@app.route("/chat", methods=["POST"])
def chat():
    try:
        user_input = request.get_json()["message"]
        session_id = session.get("id") or str(uuid.uuid4())
        session["id"] = session_id

        logging.info(f"📦 Aktuelle Session-Daten im Chat: {dict(session)}")

        client = AzureOpenAI(
            api_key=AZURE_OPENAI_KEY,
            api_version=OPENAI_API_VERSION,
            azure_endpoint=AZURE_OPENAI_ENDPOINT
        )

        response = client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,
            temperature=0.2,
            messages=[
                {"role": "system", "content":
                 "Du bist ein freundlicher deutschsprachiger Terminassistent. Bitte hilf dem Nutzer, einen Termin zu buchen. Nutze Function Calling, wenn alle Daten vorliegen."},
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
                        book_resp = client.post("/book", json=args)
                        result = book_resp.get_json()
                        if book_resp.status_code == 200:
                            return jsonify({"response": "✅ Termin erfolgreich gebucht."})
                        else:
                            return jsonify({"response": f"⚠️ Fehler: {result.get('error', 'Unbekannt')}"})

        return jsonify({"response": choice.message.content})

    except Exception as e:
        logging.exception("Fehler im /chat-Endpunkt")
        return jsonify({"error": str(e)}), 500


# === /book Endpoint ===
@app.route("/book", methods=["POST"])
def book():
    data = request.get_json()
    logging.info("🛠️ /book wurde aufgerufen.")
    access_token = session.get("access_token")

    if not access_token:
        logging.warning("⚠️ Kein Access Token in Session – bitte zuerst authentifizieren über /calendar.")
        return jsonify({"error": "Kein gültiges Outlook-Zugriffstoken. Bitte neu einloggen."}), 401

    try:
        start_time_utc = datetime.fromisoformat(data['selected_time'])
        start_local = start_time_utc.astimezone(TZ)
        end_local = start_local + timedelta(minutes=30)

        # === Outlook-Kalendereintrag ===
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

        # === SQL-Eintrag ===
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

        # === E-Mail-Bestätigung ===
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

                smtp_pw = os.getenv("SMTP_PASSWORD")
                if not smtp_pw:
                    raise ValueError("SMTP_PASSWORD Umgebungsvariable fehlt.")

                with smtplib.SMTP('smtp.office365.com', 587) as s:
                    s.starttls()
                    s.login(SMTP_SENDER, smtp_pw)
                    s.sendmail(SMTP_SENDER, rcp, msg.as_string())
                logging.info(f"✅ E-Mail an {rcp} gesendet.")
            except Exception as email_error:
                logging.exception(f"❌ Fehler beim Senden der E-Mail an {rcp}")
                return jsonify({"error": f"E-Mail-Fehler: {str(email_error)}"}), 500

        return jsonify({"status": "success", "message": "Termin gebucht."})

    except Exception as e:
        logging.exception("❌ Allgemeiner Fehler bei Terminbuchung")
        return jsonify({"error": f"Fehler bei der Buchung: {str(e)}"}), 500
