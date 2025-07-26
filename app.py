# app.py – LandKI Bot mit GPT, Outlook, Logging

import os
import json
import logging
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, session, redirect
from flask_cors import CORS
import openai
import requests
import pytz
from msal import ConfidentialClientApplication

# 📌 Flask App Setup
app = Flask(__name__)
CORS(app)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "default-secret-key")

# 🌍 Zeitzone & Logging
berlin_tz = pytz.timezone("Europe/Berlin")
logging_level = os.environ.get("WEBSITE_LOGGING_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, logging_level, logging.INFO),
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# 🤖 OpenAI Config
openai.api_key = os.environ.get("AZURE_OPENAI_KEY")
openai.api_base = os.environ.get("AZURE_OPENAI_ENDPOINT")
openai.api_type = "azure"
openai.api_version = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-05-01-preview")
DEPLOYMENT_ID = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")

# 📅 MSAL / Microsoft Graph
CLIENT_ID = os.environ.get("AZURE_CLIENT_ID")
CLIENT_SECRET = os.environ.get("AZURE_CLIENT_SECRET")
TENANT_ID = os.environ.get("AZURE_TENANT_ID")
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
SCOPE = ["https://graph.microsoft.com/.default"]

# 📦 Token holen für Graph API
def get_token():
    try:
        app_msal = ConfidentialClientApplication(
            client_id=CLIENT_ID,
            client_credential=CLIENT_SECRET,
            authority=AUTHORITY
        )
        result = app_msal.acquire_token_silent(SCOPE, account=None)
        if not result:
            result = app_msal.acquire_token_for_client(scopes=SCOPE)
        return result.get("access_token")
    except Exception as e:
        logging.exception("Fehler beim Abrufen des Access Tokens")
        return None

# 📅 Termin automatisch in Outlook eintragen
def book_appointment(start_time, end_time, subject, body, location):
    try:
        token = get_token()
        if not token:
            return {"error": "Kein gültiger Token"}

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        event = {
            "subject": subject,
            "body": {
                "contentType": "Text",
                "content": body
            },
            "start": {
                "dateTime": start_time,
                "timeZone": "Europe/Berlin"
            },
            "end": {
                "dateTime": end_time,
                "timeZone": "Europe/Berlin"
            },
            "location": {
                "displayName": location
            },
            "attendees": []
        }

        response = requests.post(
            "https://graph.microsoft.com/v1.0/me/events",
            headers=headers,
            data=json.dumps(event)
        )

        if response.status_code == 201:
            logging.info("📅 Termin erfolgreich in Outlook erstellt.")
            return {"success": True}
        else:
            logging.error(f"Fehler: {response.status_code} – {response.text}")
            return {"error": response.text}
    except Exception as e:
        logging.exception("Fehler in book_appointment():")
        return {"error": str(e)}

# 🧪 Test-Endpunkt zum Erstellen eines Beispieltermins
@app.route("/test-calendar", methods=["GET"])
def test_calendar():
    start = datetime.now(berlin_tz) + timedelta(minutes=5)
    end = start + timedelta(minutes=30)
    result = book_appointment(
        start_time=start.strftime("%Y-%m-%dT%H:%M:%S"),
        end_time=end.strftime("%Y-%m-%dT%H:%M:%S"),
        subject="Testtermin über LandKI Bot",
        body="Dies ist ein automatisch eingetragener Testtermin.",
        location="Online"
    )
    return jsonify(result)

# 🤖 GPT-Chat-Endpunkt
@app.route("/chat", methods=["POST"])
def chat():
    try:
        data = request.get_json()
        user_message = data.get("message", "")
        logging.info(f"📩 Nachricht empfangen: {user_message}")

        messages = [
            {"role": "system", "content": "Du bist ein smarter Terminassistent."},
            {"role": "user", "content": user_message}
        ]

        completion = openai.ChatCompletion.create(
            engine=DEPLOYMENT_ID,
            messages=messages,
            temperature=0.4,
        )

        reply = completion.choices[0].message["content"].strip()
        logging.info(f"💬 Antwort gesendet: {reply}")
        return jsonify({"reply": reply})

    except Exception as e:
        logging.exception("Fehler im Chat-Endpunkt")
        return jsonify({"error": str(e)}), 500

# ▶️ Startpunkt (optional, wird in Azure durch gunicorn überschrieben)
if __name__ == "__main__":
    app.run(debug=True, port=5000)
