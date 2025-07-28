# app.py – LandKI-Terminassistent v1.0016 mit GPT Function Calling, Outlook, SQL & E-Mail

from flask import Flask, request, jsonify, session
from openai import AzureOpenAI
import os, logging, uuid, requests, pytz, pyodbc, smtplib, dateparser, json
from datetime import datetime, timedelta
from flask_cors import CORS
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# === Flask Setup ===
app = Flask(__name__)
CORS(app)
app.secret_key = os.getenv("SECRET_KEY") or os.urandom(24).hex()

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
BIRTHDAY_REQUIRED = False

conversation_memory = {}
MAX_HISTORY = 20

# === GPT Chat Endpoint ===
@app.route("/chat", methods=["POST"])
def chat():
    try:
        user_input = request.get_json()["message"]
        session_id = session.get("id") or str(uuid.uuid4())
        session["id"] = session_id
        memory = conversation_memory.setdefault(session_id, [])
        memory.append({"role": "user", "content": user_input})
        memory[:] = memory[-MAX_HISTORY:]

        system_prompt = (
            "Du bist ein professioneller, geduldiger Terminassistent. Sprich in einfachem, professionellem Deutsch.\n"
            "Erkenne mehrere Angaben in einer Nachricht und verwende Function Calling, wenn möglich.\n"
            "Extrahiere: first_name, last_name, email, selected_time (datetime), user_message.\n"
            "Falls etwas fehlt, frage gezielt nach."
        )

        messages = [{"role": "system", "content": system_prompt}] + memory

        client = AzureOpenAI(
            api_key=AZURE_OPENAI_KEY,
            api_version=OPENAI_API_VERSION,
            azure_endpoint=AZURE_OPENAI_ENDPOINT
        )

        response = client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,
            messages=messages,
            temperature=0.3,
            functions=[
                {
                    "name": "book_appointment",
                    "description": "Bucht einen Termin für den Nutzer",
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
            ],
            function_call="auto"
        )

        choice = response.choices[0].message

        if choice.function_call:
            arguments = json.loads(choice.function_call.arguments)
            logging.info("Function Calling: %s", arguments)

            with app.test_client() as client:
                book_resp = client.post("/book", json=arguments)
                if book_resp.status_code == 200:
                    return jsonify({"response": "✅ Termin wurde erfolgreich gebucht."})
                else:
                    return jsonify({"response": "⚠️ Fehler bei der Buchung.", "book_error": book_resp.get_json()})

        reply = choice.content or "Ich habe deine Nachricht erhalten. Bitte teile mir die fehlenden Daten mit."
        memory.append({"role": "assistant", "content": reply})
        return jsonify({"response": reply})

    except Exception as e:
        logging.exception("Fehler im /chat-Endpunkt")
        return jsonify({"error": str(e)}), 500


# === /book Endpoint ===
@app.route("/book", methods=["POST"])
def book():
    data = request.get_json()
    access_token = session.get("access_token")
    if not access_token:
        return jsonify({"error": "Nicht authentifiziert."}), 401

    try:
        start_time_utc = datetime.fromisoformat(data['selected_time'])
        start_local = start_time_utc.astimezone(TZ)
        end_local = start_local + timedelta(minutes=30)

        outlook_body = f"Neuer Termin mit {data['first_name']} {data['last_name']}<br>E-Mail: {data['email']}"
        if BIRTHDAY_REQUIRED:
            outlook_body += f"<br>Geburtstag: {data['birthday']}"
        if data.get('user_message'):
            outlook_body += f"<br><strong>Nachricht:</strong><br>{data['user_message']}"

        event = {
            "subject": f"Termin: {data['first_name']} {data['last_name']}",
            "start": {"dateTime": start_local.isoformat(), "timeZone": "Europe/Berlin"},
            "end": {"dateTime": end_local.isoformat(), "timeZone": "Europe/Berlin"},
            "body": {"contentType": "HTML", "content": outlook_body},
            "location": {"displayName": "LandKI Kalender"},
            "attendees": []
        }

        resp = requests.post(
            'https://graph.microsoft.com/v1.0/me/events',
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            json=event
        )
        if resp.status_code != 201:
            logging.error(f"Outlook Fehler: {resp.text}")
            return jsonify({"error": "Fehler beim Kalender-Eintrag."}), 500

        conn = pyodbc.connect(
            f"DRIVER={{ODBC Driver 18 for SQL Server}};SERVER={SQL_SERVER};DATABASE={SQL_DB};"
            f"UID={SQL_USER};PWD={SQL_PASSWORD};Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
        )
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO dbo.appointments (
                first_name, last_name, birthdate, phone, email, address,
                appointment_start, appointment_end, created_at,
                company_code, bot_origin, service_type, note_internal, user_message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, SYSDATETIMEOFFSET(), ?, ?, ?, ?, ?)
        """, (
            data['first_name'], data['last_name'],
            data.get('birthday') if BIRTHDAY_REQUIRED else None,
            data.get('phone'), data['email'], data.get('address'),
            start_local, end_local, "LANDKI", "GPT-ASSIST", "Standard",
            "Termin gebucht via Bot", data.get('user_message')
        ))
        conn.commit()
        cur.close()
        conn.close()

        subject = "Ihre Terminbestätigung"
        html = f"""
        <p>Sehr geehrte*r {data['first_name']} {data['last_name']},</p>
        <p>Ihr Termin ist gebucht:</p>
        <ul><li><strong>Datum:</strong> {start_local.strftime('%d.%m.%Y')}</li>
        <li><strong>Uhrzeit:</strong> {start_local.strftime('%H:%M')} Uhr</li></ul>
        {f'<p><strong>Ihre Nachricht:</strong><br>{data["user_message"]}</p>' if data.get('user_message') else ''}
        <p>Dies ist eine automatische Terminbestätigung.<br>Ihre Daten wurden gemäß DSGVO verarbeitet.</p>
        <p>Mit freundlichen Grüßen<br>Ihr Team</p>
        """

        for rcp in [data['email'], SMTP_RECIPIENT]:
            msg = MIMEMultipart()
            msg['From'] = SMTP_SENDER
            msg['To'] = rcp
            msg['Subject'] = subject
            msg.attach(MIMEText(html, 'html'))
            with smtplib.SMTP('smtp.office365.com', 587) as s:
                s.starttls()
                s.login(SMTP_SENDER, os.getenv("SMTP_PASSWORD"))
                s.sendmail(SMTP_SENDER, rcp, msg.as_string())

        return jsonify({"status": "success", "message": "Termin gebucht."})

    except Exception as e:
        logging.exception("Fehler bei Terminbuchung")
        return jsonify({"error": str(e)}), 500
