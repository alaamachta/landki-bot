# app.py – LandKI-Terminassistent v1.0021 mit echtem GPT Function Calling, Outlook, SQL & E-Mail

from flask import Flask, request, jsonify, session
from openai import AzureOpenAI
import os, logging, uuid, requests, pytz, pyodbc, smtplib, json
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

# === GPT Chat Endpoint ===
@app.route("/chat", methods=["POST"])
def chat():
    try:
        user_input = request.get_json()["message"]
        session_id = session.get("id") or str(uuid.uuid4())
        session["id"] = session_id

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
                "Du bist ein intelligenter, deutschsprachiger Terminassistent. Wenn der Nutzer alle erforderlichen Daten nennt (Vorname, Nachname, E-Mail, Uhrzeit), rufe automatisch die Funktion 'book_appointment' auf. \
                Gib keine normale Textantwort zurück, wenn du stattdessen einen Function-Call machen kannst. Achte darauf, dass 'selected_time' im ISO-Format (z. B. 2025-07-28T13:00:00) übergeben wird. \
                Ignoriere irrelevante Daten. Rückfragen nur, wenn wirklich etwas fehlt."},
                {"role": "user", "content": user_input},
            ],
            tools=[{
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
            }],
            tool_choice="auto"
        )


        choice = response.choices[0]
        if choice.finish_reason == "function_call":
            call = choice.message.function_call
            args = json.loads(call.arguments)
            with app.test_client() as client:
                book_resp = client.post("/book", json=args)
                result = book_resp.get_json()
                if book_resp.status_code == 200:
                    return jsonify({"response": "✅ Termin erfolgreich gebucht."})
                else:
                    return jsonify({"response": "⚠️ Fehler bei der Buchung.", "book_error": result})

        # sonst normale Textantwort zurückgeben
        return jsonify({"response": choice.message.content})

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

        # Outlook-Termin erstellen
        event = {
            "subject": f"Termin: {data['first_name']} {data['last_name']}",
            "start": {"dateTime": start_local.isoformat(), "timeZone": "Europe/Berlin"},
            "end": {"dateTime": end_local.isoformat(), "timeZone": "Europe/Berlin"},
            "body": {"contentType": "HTML", "content": data.get('user_message', '')},
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

        # In SQL speichern
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

        # E-Mail-Versand
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
