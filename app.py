
import datetime
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
import pytz
import json

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
CORS(app)
app.secret_key = os.getenv("SECRET_KEY")

def get_env_var(name, required=True):
    value = os.getenv(name)
    if not value and required:
        logger.error(f"❌ ENV fehlt: {name}")
        raise EnvironmentError(f"Missing environment variable: {name}")
    return value

# === ENV ===
AZURE_OPENAI_API_KEY     = get_env_var("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_ENDPOINT    = get_env_var("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_DEPLOYMENT  = get_env_var("AZURE_OPENAI_DEPLOYMENT")
OPENAI_API_VERSION       = get_env_var("OPENAI_API_VERSION", required=False) or "2024-07-01-preview"

MS_CLIENT_ID             = get_env_var("MS_CLIENT_ID")
MS_CLIENT_SECRET         = get_env_var("MS_CLIENT_SECRET")
MS_TENANT_ID             = get_env_var("MS_TENANT_ID")
MS_REDIRECT_URI          = get_env_var("MS_REDIRECT_URI")
MS_SCOPES                = ["Calendars.Read", "Calendars.ReadWrite"]
MS_AUTHORITY             = f"https://login.microsoftonline.com/{MS_TENANT_ID}"

client = AzureOpenAI(
    api_key=AZURE_OPENAI_API_KEY,
    api_version=OPENAI_API_VERSION,
    azure_endpoint=AZURE_OPENAI_ENDPOINT
)

@app.route("/")
def root():
    return "✅ LandKI Terminassistent läuft!"

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
        return jsonify({
            "error": "Kein Token erhalten",
            "details": token_result.get("error_description")
        }), 500
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

@app.route("/available-times")
def available_times():
    token = session.get("access_token")
    if not token:
        return redirect("/calendar")
    try:
        slots = get_exact_free_slots(token)
        return jsonify(slots)
    except Exception:
        logger.error("❌ Fehler bei /available-times:")
        logger.error(traceback.format_exc())
        return jsonify({"error": "Interner Fehler"}), 500

def get_exact_free_slots(access_token, days_ahead=365, start_hour=9, end_hour=17,
                         min_minutes=15, max_minutes=120):
    tz = pytz.timezone("Europe/Berlin")
    now = datetime.datetime.now(tz)
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Prefer": 'outlook.timezone="Europe/Berlin"'
    }
    all_free_slots = []
    for day in range(days_ahead):
        current_day = now + datetime.timedelta(days=day)
        if current_day.weekday() >= 5:
            continue
        day_start = tz.localize(datetime.datetime.combine(current_day.date(), datetime.time(hour=start_hour)))
        day_end = tz.localize(datetime.datetime.combine(current_day.date(), datetime.time(hour=end_hour)))
        url = (
            f"https://graph.microsoft.com/v1.0/me/calendarView?"
            f"startDateTime={day_start.isoformat()}&endDateTime={day_end.isoformat()}"
        )
        response = requests.get(url, headers=headers)
        events = response.json().get("value", [])
        events.sort(key=lambda e: e["start"]["dateTime"])
        current_time = day_start
        for event in events:
            event_start = tz.localize(datetime.datetime.fromisoformat(event["start"]["dateTime"]))
            if current_time < event_start:
                duration = (event_start - current_time).total_seconds() / 60
                if min_minutes <= duration <= max_minutes:
                    all_free_slots.append({
                        "start": current_time.strftime("%Y-%m-%d %H:%M"),
                        "end": event_start.strftime("%Y-%m-%d %H:%M")
                    })
            current_time = tz.localize(datetime.datetime.fromisoformat(event["end"]["dateTime"]))
        if current_time < day_end:
            duration = (day_end - current_time).total_seconds() / 60
            if min_minutes <= duration <= max_minutes:
                all_free_slots.append({
                    "start": current_time.strftime("%Y-%m-%d %H:%M"),
                    "end": day_end.strftime("%Y-%m-%d %H:%M")
                })
    return all_free_slots

def handle_appointment_request(message_text):
    if any(k in message_text.lower() for k in ["termin", "verfügbar", "frei", "zeit", "buchbar"]):
        try:
            response = requests.get("https://landki-bot-app-hrbtfefhgvasc5gk.germanywestcentral-01.azurewebsites.net/available-times")
            times = response.json()
            if not times:
                return "⚠️ Es wurden aktuell keine freien Termine gefunden."
            options = times[:3]
            list_items = ""
            for option in options:
                start = option["start"].replace(":", " Uhr ", 1)
                end = option["end"].split()[1]
                list_items += f"<li>🕒 {start} bis {end} Uhr</li>"
            return f'''
            <div>
                <strong>✅ Folgende freie Termine sind verfügbar:</strong>
                <ul>{list_items}</ul>
                <p>Möchten Sie einen dieser Termine buchen<br>oder lieber ein späteres Datum wählen?</p>
                <p><em>Antwortbeispiel: „Später im September“ oder „Ja, Termin 2“</em></p>
            </div>'''
        except Exception:
            logger.error("Fehler beim Terminabruf")
            return "❌ Fehler beim Abrufen der Termine."
    return None

@app.route("/chat", methods=["POST"])
def chat():
    try:
        user_input = request.json.get("message", "")
        logger.info(f"👤 Frage: {user_input}")
        special = handle_appointment_request(user_input)
        if special:
            return jsonify({"reply_html": special})
        response = client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,
            messages=[{"role": "user", "content": user_input}],
            temperature=0.2
        )
        answer = response.choices[0].message.content
        return jsonify({
            "response": answer,
            "reply_html": markdown2.markdown(answer)
        })
    except Exception:
        logger.error("❌ Fehler im Chat:")
        logger.error(traceback.format_exc())
        return jsonify({"error": "Fehler im Chat"}), 500
