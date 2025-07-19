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
import pytz

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
MS_SCOPES = ["Calendars.Read", "Calendars.ReadWrite"]
MS_AUTHORITY = f"https://login.microsoftonline.com/{MS_TENANT_ID}"

# === OpenAI Client ===
client = AzureOpenAI(
    api_key=AZURE_OPENAI_KEY,
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

        logger.info(f"🔍 Azure Search mit: {query}")
        response = requests.post(url, headers=headers, json=body)
        response.raise_for_status()
        results = response.json()
        contents = [doc['content'] for doc in results.get('value', []) if 'content' in doc]
        return "\n---\n".join(contents)
    except Exception as e:
        logger.error("❌ Fehler bei Azure Search:")
        logger.error(traceback.format_exc())
        return "Fehler bei der Azure Search."

# === /chat Endpoint ===
@app.route("/chat", methods=["POST"])
def chat():
    try:
        user_input = request.json.get("message", "")
        context = search_azure(user_input)
        prompt = f"Use the following context to answer the question:\n{context}\n\nQuestion: {user_input}\nAnswer:"

        response = client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2
        )

        answer = response.choices[0].message.content
        return jsonify({"response": answer, "reply_html": markdown2.markdown(answer)})
    except Exception as e:
        logger.error("❌ Fehler im Chat:")
        logger.error(traceback.format_exc())
        return jsonify({"error": str(e)}), 500

# === MSAL OAuth Funktionen ===
def _build_msal_app():
    return msal.ConfidentialClientApplication(
        MS_CLIENT_ID,
        authority=MS_AUTHORITY,
        client_credential=MS_CLIENT_SECRET
    )

def _get_token_by_code(code):
    return _build_msal_app().acquire_token_by_authorization_code(
        code,
        scopes=MS_SCOPES,
        redirect_uri=MS_REDIRECT_URI
    )

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
        return "State mismatch!", 400
    code = request.args.get('code')
    try:
        token_result = _get_token_by_code(code)
        session["access_token"] = token_result.get("access_token")
        return redirect("/available-times")
    except Exception as e:
        logger.error(traceback.format_exc())
        return "Fehler beim Token holen", 500

# === Kalender-Funktionen ===
def get_free_time_slots(token, days=7):
    timezone = "Europe/Berlin"
    start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=days)
    params = {
        "startDateTime": start.isoformat() + "Z",
        "endDateTime": end.isoformat() + "Z"
    }
    headers = {
        'Authorization': f'Bearer {token}',
        'Prefer': f'outlook.timezone=\"{timezone}\"'
    }
    events = requests.get(
        "https://graph.microsoft.com/v1.0/me/calendarView",
        headers=headers,
        params=params
    ).json().get("value", [])

    busy = [(datetime.fromisoformat(e["start"]["dateTime"]), datetime.fromisoformat(e["end"]["dateTime"])) for e in events]
    slots = []
    for day in range(days):
        current_day = start + timedelta(days=day)
        for hour in range(8, 17):
            slot_start = current_day.replace(hour=hour)
            slot_end = slot_start + timedelta(hours=1)
            if all(not (slot_start < b_end and slot_end > b_start) for b_start, b_end in busy):
                slots.append(slot_start.isoformat())
    return slots

def book_appointment(token, datetime_str, subject, patient_info):
    start_time = datetime.fromisoformat(datetime_str)
    end_time = start_time + timedelta(hours=1)
    payload = {
        "subject": subject,
        "body": {"contentType": "Text", "content": patient_info},
        "start": {"dateTime": start_time.isoformat(), "timeZone": "Europe/Berlin"},
        "end": {"dateTime": end_time.isoformat(), "timeZone": "Europe/Berlin"}
    }
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }
    res = requests.post("https://graph.microsoft.com/v1.0/me/events", headers=headers, json=payload)
    return res.status_code == 201

@app.route("/available-times")
def available():
    token = session.get("access_token")
    if not token:
        return redirect("/calendar")
    return jsonify({"free_slots": get_free_time_slots(token)})

@app.route("/book-appointment", methods=["POST"])
def book():
    token = session.get("access_token")
    if not token:
        return redirect("/calendar")
    data = request.json
    if not data:
        return jsonify({"error": "Daten fehlen"}), 400
    success = book_appointment(
        token,
        data.get("datetime"),
        f"Praxis-Termin mit {data.get('name')}",
        f"{data.get('name')}, geboren am {data.get('dob')}, Grund: {data.get('reason')}"
    )
    return jsonify({"status": "ok" if success else "error"})

@app.route("/")
def health():
    return "✅ LandKI läuft inkl. Kalender!"
