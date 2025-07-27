# Version v1.5 – Integriert: GPT-4o + Outlook + SQL + Mail + Systemprompt
from flask import Flask, request, jsonify, session, redirect
from flask_cors import CORS
import os, openai, logging, smtplib, pyodbc
from openai import OpenAIError
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
import pytz
from msal import ConfidentialClientApplication
import requests

# === Konfiguration ===
app = Flask(__name__)
CORS(app)
app.secret_key = os.environ.get("FLASK_SECRET", "devkey")

# === Logging mit Zeitzone ===
LOG_LEVEL = os.environ.get("WEBSITE_LOGGING_LEVEL", "DEBUG")
logging.basicConfig(
    level=LOG_LEVEL,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler()]
)
logging.Formatter.converter = lambda *args: datetime.now(pytz.timezone('Europe/Berlin')).timetuple()

# === GPT-4o + Azure Search Setup ===
AZURE_OPENAI_ENDPOINT = os.environ["AZURE_OPENAI_ENDPOINT"]
AZURE_OPENAI_KEY = os.environ["AZURE_OPENAI_KEY"]
AZURE_DEPLOYMENT_ID = os.environ["AZURE_DEPLOYMENT_ID"]
AZURE_SEARCH_ENDPOINT = os.environ["AZURE_SEARCH_ENDPOINT"]
AZURE_SEARCH_KEY = os.environ["AZURE_SEARCH_KEY"]
AZURE_SEARCH_INDEX = os.environ["AZURE_SEARCH_INDEX"]

# === Outlook API Setup ===
CLIENT_ID = os.environ["MS_CLIENT_ID"]
CLIENT_SECRET = os.environ["MS_CLIENT_SECRET"]
TENANT_ID = os.environ["MS_TENANT_ID"]
REDIRECT_URI = os.environ["MS_REDIRECT_URI"]
SMTP_SENDER = os.environ["SMTP_SENDER"]
SMTP_PASSWORD = os.environ["SMTP_PASSWORD"]
SMTP_RECIPIENT = os.environ["SMTP_RECIPIENT"]
SQL_CONN_STR = os.environ["SQL_CONN_STR"]

# === GPT-System-Prompt ===
GPT_SYSTEM_PROMPT = (
    "Du bist ein Terminassistent für eine Arztpraxis. "
    "Wenn der Patient einen Termin buchen will, frage schrittweise nach: Vorname, Nachname, Geburtstag (JJJJ-MM-TT), "
    "Telefonnummer, Symptome, Symptomdauer, Adresse. Fasse danach alles zusammen und frage nach Terminzeit. "
    "Erst nach Bestätigung soll die Buchung ausgelöst werden. Sprich immer höflich, klar und in Du-Form."
)

# === MSAL App ===
msal_app = ConfidentialClientApplication(
    CLIENT_ID,
    authority=f"https://login.microsoftonline.com/{TENANT_ID}",
    client_credential=CLIENT_SECRET
)

# === Outlook Access Token ===
def get_access_token():
    token = msal_app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
    return token["access_token"]

# === Freie Slots (werktags 9–17 Uhr) ===
def get_free_slots():
    access_token = get_access_token()
    today = datetime.utcnow()
    start = today.isoformat() + "Z"
    end = (today + timedelta(days=2)).isoformat() + "Z"

    url = f"https://graph.microsoft.com/v1.0/users/{SMTP_SENDER}/calendar/getSchedule"
    headers = {"Authorization": f"Bearer {access_token}"}
    body = {
        "schedules": [SMTP_SENDER],
        "startTime": {"dateTime": start, "timeZone": "UTC"},
        "endTime": {"dateTime": end, "timeZone": "UTC"},
        "availabilityViewInterval": 15
    }

    res = requests.post(url, headers=headers, json=body).json()
    slots = []
    if "value" in res:
        for schedule in res["value"]:
            for i in range(18, 54):  # 9–17 Uhr = Slots 18–53
                if schedule["availabilityView"][i] == "0":
                    hour = i // 4
                    minute = (i % 4) * 15
                    slot_time = today.replace(hour=hour, minute=minute, second=0, microsecond=0)
                    slots.append(slot_time.strftime("%Y-%m-%d %H:%M"))
    return slots

# === Termin buchen (Outlook, SQL, Mail) ===
@app.route("/book", methods=["POST"])
def book_appointment():
    try:
        data = request.get_json()
        logging.info(f"Neue Buchung: {data}")

        # SQL speichern
        conn = pyodbc.connect(SQL_CONN_STR)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO appointments (first_name, last_name, birthday, phone, symptoms, duration, address, date, email) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            data["first_name"], data["last_name"], data["birthday"],
            data["phone"], data["symptoms"], data["duration"],
            data["address"], data["date"], data["email"]
        )
        conn.commit()
        logging.info("SQL-Eintrag gespeichert")

        # E-Mail senden
        subject = "Terminbestätigung"
        html = f"<p>Hallo {data['first_name']},</p><p>Ihr Termin am {data['date']} wurde gebucht.</p>"

        for rcp in [data["email"], SMTP_RECIPIENT]:
            msg = MIMEMultipart()
            msg["From"] = SMTP_SENDER
            msg["To"] = rcp
            msg["Subject"] = subject
            msg.attach(MIMEText(html, "html"))

            with smtplib.SMTP("smtp.office365.com", 587) as s:
                s.starttls()
                s.login(SMTP_SENDER, SMTP_PASSWORD)
                s.sendmail(SMTP_SENDER, rcp, msg.as_string())

        logging.info("Bestätigungs-Mails versendet")
        return jsonify({"status": "success", "message": "Termin gebucht."})

    except Exception as e:
        logging.exception("Fehler bei Terminbuchung")
        return jsonify({"error": str(e)}), 500

# === Chat mit GPT + Search ===
@app.route("/chat", methods=["POST"])
def chat():
    try:
        user_message = request.get_json().get("message", "")
        response = openai.ChatCompletion.create(
            api_key=AZURE_OPENAI_KEY,
            api_base=AZURE_OPENAI_ENDPOINT,
            api_type="azure",
            api_version="2024-10-21",
            deployment_id=AZURE_DEPLOYMENT_ID,
            messages=[
                {"role": "system", "content": GPT_SYSTEM_PROMPT},
                {"role": "user", "content": user_message}
            ],
            extra_headers={
                "azure-search-endpoint": AZURE_SEARCH_ENDPOINT,
                "azure-search-key": AZURE_SEARCH_KEY,
                "azure-search-index": AZURE_SEARCH_INDEX
            },
            temperature=0.2  # Klar & zuverlässig
        )
        answer = response.choices[0].message["content"]
        return jsonify({"answer": answer})

    except OpenAIError as e:
        logging.exception("GPT-Fehler")
        return jsonify({"error": str(e)}), 500

# === Start ===
if __name__ == "__main__":
    app.run(debug=True)
