from flask import Flask, request, jsonify
from flask_cors import CORS
import openai
import os
import logging
import msal
import requests
from datetime import datetime, timedelta
import pytz

# Initialisiere Flask-App
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)  # Aktiviere CORS

# Setze das Logging-Level (z. B. DEBUG, INFO, WARNING)
logging.basicConfig(level=os.getenv("WEBSITE_LOGGING_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

# MSAL-Konfiguration (für Outlook)
TENANT_ID = os.getenv("AZURE_TENANT_ID")
CLIENT_ID = os.getenv("AZURE_CLIENT_ID")
CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET")
SCOPES = ["https://graph.microsoft.com/.default"]
USER_EMAIL = os.getenv("OUTLOOK_CALENDAR_USER")

# GPT-Konfiguration
openai.api_type = "azure"
openai.api_base = os.getenv("AZURE_OPENAI_ENDPOINT")
openai.api_key = os.getenv("AZURE_OPENAI_KEY")
openai.api_version = "2024-07-01-preview"
model = os.getenv("AZURE_OPENAI_MODEL", "gpt-4o")

# Systemprompt für Szenario: Terminbuchung
SYSTEM_PROMPT = """
Du bist ein freundlicher, deutscher Praxis-Assistent. Begrüße den Nutzer, biete folgende Optionen an und frage bei Bedarf nach Details:

1. 📅 Termin buchen  → Frage nach Vorname, Nachname, Geburtstag, Telefonnummer, Symptomen, Symptomdauer, Adresse → Outlook-Termin + SQL + Mail
2. ❓ Terminstatus prüfen → Frage nach Vorname, Nachname, Geburtstag → Termin anzeigen
3. ❌ Termin stornieren → Frage nach Vorname, Nachname, Geburtstag → Termin löschen

Sprich IMMER Deutsch. Nutze klare, kurze Sätze. Stelle Rückfragen, wenn Infos fehlen. Schließe mit einer netten Bestätigung.

Wenn Nutzer "Termin buchen" schreibt, antworte:
"📅 Du möchtest einen Termin buchen. Wie lautet dein Vorname?"

Wenn der Vorname vorhanden ist, frage:
"Und dein Nachname?"
"""

# Session-Speicher (einfach)
sessions = {}

def get_token():
    app_msal = msal.ConfidentialClientApplication(
        CLIENT_ID, authority=f"https://login.microsoftonline.com/{TENANT_ID}", client_credential=CLIENT_SECRET
    )
    result = app_msal.acquire_token_for_client(scopes=SCOPES)
    if "access_token" in result:
        return result["access_token"]
    else:
        logger.error("Fehler beim Abrufen des Tokens: %s", result.get("error_description"))
        return None

def book_appointment(data):
    access_token = get_token()
    if not access_token:
        return False

    berlin_tz = pytz.timezone('Europe/Berlin')
    start_dt = berlin_tz.localize(datetime.strptime(data['start'], "%Y-%m-%dT%H:%M"))
    end_dt = berlin_tz.localize(datetime.strptime(data['end'], "%Y-%m-%dT%H:%M"))

    payload = {
        "subject": f"Termin mit {data['vorname']} {data['nachname']}",
        "start": {"dateTime": start_dt.isoformat(), "timeZone": "Europe/Berlin"},
        "end": {"dateTime": end_dt.isoformat(), "timeZone": "Europe/Berlin"},
        "location": {"displayName": "Online / Praxis"},
        "attendees": [
            {"emailAddress": {"address": USER_EMAIL, "name": "Praxis"}, "type": "required"},
            {"emailAddress": {"address": data['email'], "name": f"{data['vorname']} {data['nachname']}"}, "type": "required"},
        ]
    }

    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    response = requests.post(f"https://graph.microsoft.com/v1.0/users/{USER_EMAIL}/events", headers=headers, json=payload)

    if response.status_code == 201:
        logger.info("Termin erfolgreich erstellt für %s %s", data['vorname'], data['nachname'])
        return True
    else:
        logger.error("Fehler bei Terminbuchung: %s", response.text)
        return False

@app.route("/ping", methods=["GET"])
def ping():
    return "pong"

@app.route("/chat", methods=["POST"])
def chat():
    user_message = request.json.get("message", "")
    session_id = request.remote_addr  # primitive Sitzungstrennung
    session = sessions.setdefault(session_id, {"history": []})

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        *session["history"],
        {"role": "user", "content": user_message}
    ]

    try:
        response = openai.ChatCompletion.create(
            engine=model,
            messages=messages,
            temperature=0.3,
        )
        assistant_reply = response.choices[0].message.content
        session["history"].append({"role": "user", "content": user_message})
        session["history"].append({"role": "assistant", "content": assistant_reply})
        return jsonify({"reply": assistant_reply})
    except Exception as e:
        logger.exception("Fehler bei GPT-Antwort")
        return jsonify({"reply": f"❌ Interner Fehler beim Verarbeiten deiner Anfrage."})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
