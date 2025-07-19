from datetime import datetime, timedelta, time
import os
import traceback
import logging
import requests
import msal
import pytz
from flask import Flask, request, jsonify, redirect, session, url_for
from flask_cors import CORS
from openai import AzureOpenAI
from markdown2 import markdown
from colorlog import ColoredFormatter

# === Logging ===
formatter = ColoredFormatter(
    "%(log_color)s[%(levelname)s]%(reset)s %(message)s",
    log_colors={"DEBUG": "cyan", "INFO": "green", "WARNING": "yellow", "ERROR": "red", "CRITICAL": "bold_red"}
)
handler = logging.StreamHandler()
handler.setFormatter(formatter)
logger = logging.getLogger()
logger.addHandler(handler)
logger.setLevel(logging.INFO)

# === Flask App ===
app = Flask(__name__)
CORS(app)
app.secret_key = os.getenv("SECRET_KEY")

# === ENV Variablen ===
AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_KEY")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")
AZURE_SEARCH_ENDPOINT = os.getenv("AZURE_SEARCH_ENDPOINT")
AZURE_SEARCH_KEY = os.getenv("AZURE_SEARCH_KEY")
AZURE_SEARCH_INDEX = os.getenv("AZURE_SEARCH_INDEX")
OPENAI_API_VERSION = os.getenv("OPENAI_API_VERSION", "2024-07-18")

MS_CLIENT_ID = os.getenv("MS_CLIENT_ID")
MS_CLIENT_SECRET = os.getenv("MS_CLIENT_SECRET")
MS_TENANT_ID = os.getenv("MS_TENANT_ID")
MS_REDIRECT_URI = os.getenv("MS_REDIRECT_URI")
MS_SCOPES = ["Calendars.Read", "Calendars.ReadWrite", "offline_access", "User.Read"]
MS_AUTHORITY = f"https://login.microsoftonline.com/{MS_TENANT_ID}"

# === OpenAI ===
client = AzureOpenAI(api_key=AZURE_OPENAI_KEY, api_version=OPENAI_API_VERSION, azure_endpoint=AZURE_OPENAI_ENDPOINT)

def _build_msal_app():
    return msal.ConfidentialClientApplication(MS_CLIENT_ID, authority=MS_AUTHORITY, client_credential=MS_CLIENT_SECRET)

def _get_token_by_code(auth_code):
    return _build_msal_app().acquire_token_by_authorization_code(auth_code, scopes=MS_SCOPES, redirect_uri=MS_REDIRECT_URI)

@app.route("/")
def root():
    return "✅ LandKI ohne Übersetzungslogik läuft!"

@app.route("/chat", methods=["POST"])
def chat():
    try:
        user_input = request.json.get("message", "")
        logger.info(f"👤 Eingabe: {user_input}")
        context = search_azure(user_input)
        prompt = f"Nutze den folgenden Kontext:\n{context}\n\nFrage: {user_input}\nAntwort:"
        response = client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2
        )
        answer = response.choices[0].message.content
        return jsonify({"response": answer, "reply_html": markdown(answer)})
    except Exception as e:
        logger.error(traceback.format_exc())
        return jsonify({"error": "Fehler im Chat", "details": str(e)}), 500

def search_azure(query):
    try:
        headers = {
            "Content-Type": "application/json",
            "api-key": AZURE_SEARCH_KEY,
            "Accept": "application/json;odata.metadata=none"
        }
        url = f"{AZURE_SEARCH_ENDPOINT}/indexes/{AZURE_SEARCH_INDEX}/docs/search?api-version=2023-07-01-Preview"
        body = {"search": query, "top": 5}
        response = requests.post(url, headers=headers, json=body)
        response.raise_for_status()
        results = response.json()
        return "\n---\n".join([doc['content'] for doc in results.get("value", []) if "content" in doc])
    except Exception as e:
        logger.error(traceback.format_exc())
        return "Fehler bei Azure Search"

@app.route("/calendar")
def calendar_login():
    session["state"] = os.urandom(24).hex()
    logger.info(f"[OAuth] Login mit state: {session['state']}")
    auth_url = _build_msal_app().get_authorization_request_url(
        scopes=MS_SCOPES,
        state=session["state"],
        redirect_uri=MS_REDIRECT_URI
    )
    return redirect(auth_url)

@app.route("/callback")
def calendar_callback():
    incoming_state = request.args.get("state")
    expected_state = session.get("state")

    if incoming_state != expected_state:
        return "❌ State mismatch!", 400

    code = request.args.get("code")
    if not code:
        return "❌ Kein Code vorhanden", 400

    try:
        token_result = _get_token_by_code(code)
        logger.info(f"[MSAL] Token: {token_result}")
    except Exception as e:
        logger.error(traceback.format_exc())
        return "Fehler beim MSAL-Token holen", 500

    if "access_token" not in token_result:
        return jsonify({"error": "Token konnte nicht geholt werden", "details": token_result.get("error_description")}), 500

    session["access_token"] = token_result["access_token"]
    return redirect("/available-times")

@app.route("/available-times")
def show_free_slots():
    token = session.get("access_token")
    if not token:
        return redirect("/calendar")
    slots = get_free_time_slots(token)
    return jsonify({"free_slots": slots})

@app.route("/book-appointment", methods=["POST"])
def handle_booking():
    token = session.get("access_token")
    if not token:
        return redirect("/calendar")

    data = request.json
    slot = data.get("datetime")
    name = data.get("name")
    dob = data.get("dob")
    reason = data.get("reason")

    patient_info = f"{name}, geboren am {dob}, Grund: {reason}"
    subject = f"Praxis-Termin mit {name}"

    success = book_appointment(token, slot, subject, patient_info)
    return jsonify({"status": "ok" if success else "error"})

def get_free_time_slots(access_token, days_ahead=7):
    timezone = "Europe/Berlin"
    start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=days_ahead)

    headers = {
        'Authorization': f'Bearer {access_token}',
        'Prefer': f'outlook.timezone="{timezone}"'
    }

    params = {
        "startDateTime": start.isoformat() + "Z",
        "endDateTime": end.isoformat() + "Z"
    }

    events = requests.get(
        "https://graph.microsoft.com/v1.0/me/calendarView",
        headers=headers,
        params=params
    ).json().get("value", [])

    busy = [(e["start"]["dateTime"], e["end"]["dateTime"]) for e in events]
    slots = []

    for day in range(days_ahead):
        current = (start + timedelta(days=day)).astimezone(pytz.timezone(timezone))
        for hour in range(8, 17):
            slot_start = current.replace(hour=hour, minute=0)
            slot_end = current.replace(hour=hour + 1, minute=0)
            overlaps = any(
                slot_start.isoformat() < b_end and slot_end.isoformat() > b_start
                for b_start, b_end in [(datetime.fromisoformat(s), datetime.fromisoformat(e)) for s, e in busy]
            )
            if not overlaps:
                slots.append(slot_start.isoformat())

    return slots

def book_appointment(access_token, datetime_str, subject, patient_info):
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }

    start_time = datetime.fromisoformat(datetime_str)
    end_time = start_time + timedelta(hours=1)

    payload = {
        "subject": subject,
        "body": {
            "contentType": "Text",
            "content": f"Termin für {patient_info}"
        },
        "start": {
            "dateTime": start_time.isoformat(),
            "timeZone": "Europe/Berlin"
        },
        "end": {
            "dateTime": end_time.isoformat(),
            "timeZone": "Europe/Berlin"
        }
    }

    response = requests.post(
        "https://graph.microsoft.com/v1.0/me/events",
        headers=headers,
        json=payload
    )
    return response.status_code == 201
