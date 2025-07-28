# app.py – LandKI-Terminassistent v1.0020 mit GPT Function Calling, Outlook, SQL & E-Mail

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

# === Konversationszustand ===
conversation_memory = {}
MAX_HISTORY = 20

# === GPT Chat mit Function Calling ===
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
            "Du bist ein professioneller Terminassistent. Sprich in einfachem Deutsch.\n"
            "Deine Aufgabe: Analysiere die Nutzereingabe und erkenne folgende Felder:\n"
            "- first_name, last_name, email, selected_time (z.B. 'morgen 10 Uhr'), user_message\n"
            "Wenn alle Felder erkannt sind, rufe die Funktion `book_appointment` auf.\n"
            "Wenn etwas fehlt, frage gezielt danach."
        )

        functions = [
            {
                "name": "book_appointment",
                "description": "Bucht einen Termin, wenn alle Felder vollständig sind.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "first_name": {"type": "string"},
                        "last_name": {"type": "string"},
                        "email": {"type": "string"},
                        "selected_time": {"type": "string"},
                        "user_message": {"type": "string"},
                    },
                    "required": ["first_name", "last_name", "email", "selected_time", "user_message"]
                }
            }
        ]

        messages = [{"role": "system", "content": system_prompt}] + memory

        client = AzureOpenAI(
            api_key=AZURE_OPENAI_KEY,
            api_version=OPENAI_API_VERSION,
            azure_endpoint=AZURE_OPENAI_ENDPOINT
        )

        response = client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,
            messages=messages,
            functions=functions,
            function_call="auto",
            temperature=0.2
        )

        reply = response.choices[0].message
        memory.append({"role": "assistant", "content": reply.content or ""})

        # Wenn GPT eine Funktion aufruft:
        if reply.function_call and reply.function_call.name == "book_appointment":
            try:
                payload = json.loads(reply.function_call.arguments)
                with app.test_client() as client:
                    book_resp = client.post("/book", json=payload)
                    if book_resp.status_code == 200:
                        return jsonify({"response": "✅ Termin wurde erfolgreich gebucht."})
                    else:
                        return jsonify({"response": "⚠️ Fehler bei der Buchung.", "error": book_resp.get_json()})
            except Exception as auto_error:
                logging.warning(f"Fehler bei automatischer Buchung: {auto_error}")

        return jsonify({"response": reply.content})

    except Exception as e:
        logging.exception("Fehler im /chat-Endpunkt")
        return jsonify({"error": str(e)}), 500
