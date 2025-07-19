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
app.secret_key = os.getenv("SECRET_KEY")

# === OpenAI Client ===
client = AzureOpenAI(
    api_key=AZURE_OPENAI_KEY,
    api_version=OPENAI_API_VERSION,
    azure_endpoint=AZURE_OPENAI_ENDPOINT
)

# === Azure Search ===
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
        logger.info(f"📦 {len(contents)} Dokumente gefunden")
        return "\n---\n".join(contents)
    except Exception as e:
        logger.error("❌ Azure Search Fehler:")
        logger.error(traceback.format_exc())
        return "Fehler bei Azure Search."

@app.route("/chat", methods=["POST"])
def chat():
    try:
        user_input = request.json.get("message", "")
        logger.info(f"👤 Eingabe: {user_input}")

        context = search_azure(user_input)
        logger.info(f"📚 Kontext geladen ({len(context)} Zeichen)")

        prompt = f"Use the following context to answer the question:\n{context}\n\nQuestion: {user_input}\nAnswer:"

        response = client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2
        )

        answer = response.choices[0].message.content
        return jsonify({
            "response": answer,
            "reply_html": markdown2.markdown(answer)
        })
    except Exception as e:
        logger.error("❌ Fehler im Chat:")
        logger.error(traceback.format_exc())
        return jsonify({"error": str(e)}), 500

@app.route("/")
def root():
    return "✅ LandKI läuft!"

# === MS OAuth ===
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
        return "❌ Sicherheitsprüfung fehlgeschlagen", 400
    code = request.args.get('code')
    try:
        token_result = _get_token_by_code(code)
        logger.info(f"[MSAL] Token erhalten: {token_result}")
    except Exception as e:
        logger.error("[MSAL] Fehler beim Token holen")
        logger.error(traceback.format_exc())
        return "Fehler beim MSAL-Token holen", 500

    if "access_token" not in token_result:
        return jsonify({"error": "Token konnte nicht geholt werden", "details": token_result.get("error_description")}), 500

    session["access_token"] = token_result["access_token"]
    return redirect("/available-times")

def get_free_time_slots(access_token, days_ahead=7):
    timezone = "Europe/Berlin"
    start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=days_ahead)

    params = {
        "startDateTime": start.isoformat() + "Z",
        "endDateTime": end.isoformat() + "Z"
    }
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Prefer': f'outlook.timezone="{timezone}"'
    }

    events = requests.get(
        "https://graph.microsoft.com/v1.0/me/calendarView",
        headers=headers,
        params=params
    ).json().get("value", [])

    busy = [(datetime.fromisoformat(e["start"]["dateTime"]), datetime.fromisoformat(e["end"]["dateTime"])) for e in events]
    slots = []
    for day in range(days_ahead):
        for hour in range(8, 17):
            slot_start = (start + timedelta(days=day)).replace(hour=hour)
            slot_end = slot_start + timedelta(hours=1)
            if all(slot_end <= b_start or slot_start >= b_end for b_start, b_end in busy):
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
        "body": {"contentType": "Text", "content": f"Termin für {patient_info}"},
        "start": {"dateTime": start_time.isoformat(), "timeZone": "Europe/Berlin"},
        "end": {"dateTime": end_time.isoformat(), "timeZone": "Europe/Berlin"}
    }
    response = requests.post("https://graph.microsoft.com/v1.0/me/events", headers=headers, json=payload)
    return response.status_code == 201

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
    if success:
        return jsonify({"status": "ok", "message": "Termin gebucht!"})
    return jsonify({"status": "error", "message": "Fehler bei Buchung"}), 500
