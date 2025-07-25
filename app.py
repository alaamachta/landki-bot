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

@app.route("/calendar")
def calendar_login():
    session["state"] = os.urandom(24).hex()
    auth_url = _build_msal_app().get_authorization_request_url(
        scopes=MS_SCOPES,
        state=session["state"],
        redirect_uri=MS_REDIRECT_URI
    )
    return redirect(auth_url)

@app.route("/callback")
def calendar_callback():
    if request.args.get('state') != session.get('state'):
        return "❌ Ungültiger State", 400

    code = request.args.get('code')
    token_result = _get_token_by_code(code)

    if "access_token" not in token_result:
        return jsonify({"error": "Kein Token erhalten", "details": token_result.get("error_description")}), 500

    session["access_token"] = token_result["access_token"]
    return "✅ Kalenderzugriff gespeichert."

def _build_msal_app():
    return msal.ConfidentialClientApplication(
        MS_CLIENT_ID,
        authority=MS_AUTHORITY,
        client_credential=MS_CLIENT_SECRET
    )

def _get_token_by_code(auth_code):
    return _build_msal_app().acquire_token_by_authorization_code(
        auth_code,
        scopes=MS_SCOPES,
        redirect_uri=MS_REDIRECT_URI
    )

@app.route("/book-test", methods=["GET"])
def book_test():
    test_data = {
        "first_name": "Max",
        "last_name": "Muster",
        "birthdate": "1990-01-01",
        "phone": "+49 170 1234567",
        "email": "max.muster@example.com",
        "symptom": "Kopfschmerzen",
        "symptom_duration": "2 Tage",
        "address": "Musterstraße 1, 36037 Fulda",
        "appointment_start": (datetime.now(pytz.timezone("Europe/Berlin")) + timedelta(days=1, hours=1)).isoformat(),
        "appointment_end": (datetime.now(pytz.timezone("Europe/Berlin")) + timedelta(days=1, hours=2)).isoformat()
    }
    result = book_appointment(test_data)
    return jsonify(result)

# === Buchungsfunktion ===
def book_appointment(data):
    try:
        first = data.get("first_name")
        last = data.get("last_name")
        birth = data.get("birthdate")
        phone = data.get("phone")
        email = data.get("email")
        symptom = data.get("symptom")
        duration = data.get("symptom_duration")
        address = data.get("address")
        start = data.get("appointment_start")
        end = data.get("appointment_end")

        token = session.get("access_token")
        if not token:
            return {"error": "Kein Token"}

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        outlook_event = {
            "subject": f"Termin: {first} {last} – {symptom}",
            "start": {"dateTime": start, "timeZone": "Europe/Berlin"},
            "end":   {"dateTime": end, "timeZone": "Europe/Berlin"},
            "location": {"displayName": "LandKI Online"},
            "body": {
                "contentType": "Text",
                "content": f"Name: {first} {last}\nGeburtstag: {birth}\nTelefon: {phone}\nEmail: {email}\nSymptom: {symptom} ({duration})\nAdresse: {address}"
            },
            "attendees": []
        }

        response = requests.post("https://graph.microsoft.com/v1.0/me/events", headers=headers, json=outlook_event)
        if response.status_code != 201:
            logger.error("❌ Outlook-Termin fehlgeschlagen")
            return {"error": "Outlook-Termin fehlgeschlagen"}

        conn = pyodbc.connect(
            "Driver={ODBC Driver 17 for SQL Server};"
            "Server=landki-sql-server.database.windows.net;"
            "Database=landki-db;"
            "Uid=landki.sql.server;Pwd=" + os.getenv("SQL_PASSWORD") + ";"
            "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
        )

        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO appointments (first_name, last_name, birthdate, phone, email, symptom, symptom_duration, address, appointment_start, appointment_end)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (first, last, birth, phone, email, symptom, duration, address, start, end))
        conn.commit()
        conn.close()
        logger.info(f"✅ SQL gespeichert: {first} {last}")

        tenant = MS_TENANT_ID
        client_id = MS_CLIENT_ID
        client_secret = MS_CLIENT_SECRET
        authority = f"https://login.microsoftonline.com/{tenant}"
        scope = ["https://outlook.office365.com/.default"]

        app = ConfidentialClientApplication(client_id, authority=authority, client_credential=client_secret)
        result = app.acquire_token_for_client(scopes=scope)

        if "access_token" not in result:
            logger.error("❌ Token für Mailversand fehlgeschlagen")
            return {"error": "Mailtoken fehlt"}

        smtp = smtplib.SMTP("smtp.office365.com", 587)
        smtp.starttls()
        smtp.ehlo()
        smtp.authenticate("XOAUTH2", lambda x: f"user=AlaaMashta@LandKI.onmicrosoft.com\x01auth=Bearer {result['access_token']}\x01\x01".encode())

        body = f"""
Terminbestätigung
-----------------
Name: {first} {last}
Geburtsdatum: {birth}
Telefon: {phone}
E-Mail: {email}
Adresse: {address}
Symptom: {symptom} ({duration})
Termin: {start} – {end}
        """
        msg = MIMEMultipart()
        msg['From'] = "AlaaMashta@LandKI.onmicrosoft.com"
        msg['To'] = f"{email}"
        msg['Subject'] = "✅ Terminbestätigung – LandKI"
        msg.attach(MIMEText(body, "plain"))

        smtp.sendmail(msg['From'], [msg['To'], "AlaaMashta@LandKI.onmicrosoft.com"], msg.as_string())
        smtp.quit()

        logger.info("📧 Terminbestätigung gesendet")
        return {"status": "success"}

    except Exception as e:
        logger.error("💥 Fehler in book_appointment:")
        logger.error(traceback.format_exc())
        return {"error": "Interner Fehler"}
