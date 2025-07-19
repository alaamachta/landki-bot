import os
import logging
import traceback
from flask import Flask, request, jsonify, redirect, session
from flask_cors import CORS
from datetime import datetime, timedelta
import pytz
import msal
import requests
import openai

# === Flask Setup ===
app = Flask(__name__)
CORS(app)
app.secret_key = os.getenv("SECRET_KEY")

# === Microsoft Identity ===
MS_CLIENT_ID = os.getenv("MS_CLIENT_ID")
MS_CLIENT_SECRET = os.getenv("MS_CLIENT_SECRET")
MS_TENANT_ID = os.getenv("MS_TENANT_ID")
MS_REDIRECT_URI = os.getenv("MS_REDIRECT_URI")
MS_AUTHORITY = f"https://login.microsoftonline.com/{MS_TENANT_ID}"
MS_SCOPES = ["https://graph.microsoft.com/Calendars.Read", "https://graph.microsoft.com/User.Read"]

# === GPT Key ===
openai.api_key = os.getenv("OPENAI_API_KEY")

# === Logging ===
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("app")

# === MSAL Setup ===
def _build_msal_app(cache=None):
    return msal.ConfidentialClientApplication(
        MS_CLIENT_ID,
        client_credential=MS_CLIENT_SECRET,
        authority=MS_AUTHORITY,
        token_cache=cache,
    )

def _get_token_by_code(auth_code):
    app_msal = _build_msal_app()
    return app_msal.acquire_token_by_authorization_code(
        code=auth_code,
        scopes=MS_SCOPES,
        redirect_uri=MS_REDIRECT_URI
    )

# === Microsoft Login & Callback ===
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
        logger.info(f"[MSAL] Token erhalten: {token_result}")
    except Exception as e:
        logger.error(f"[MSAL] Fehler beim Token holen: {str(e)}")
        logger.error(traceback.format_exc())
        return "Fehler beim MSAL-Token holen", 500

    if "access_token" not in token_result:
        return jsonify({"error": "Token konnte nicht geholt werden", "details": token_result.get("error_description")}), 500

    session["access_token"] = token_result["access_token"]
    return redirect("/available-times")

# === Kalenderabfrage ===
@app.route("/available-times")
def get_free_times():
    access_token = session.get("access_token")
    if not access_token:
        return redirect("/calendar")

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    now = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    end = (datetime.utcnow() + timedelta(days=2)).replace(microsecond=0).isoformat() + "Z"

    url = "https://graph.microsoft.com/v1.0/me/calendar/events"
    params = {
        "$filter": f"start/dateTime ge '{now}' and end/dateTime le '{end}'",
        "$orderby": "start/dateTime",
    }

    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        events = response.json().get("value", [])
    except Exception as e:
        logger.error(f"[GRAPH] Fehler beim Abrufen des Kalenders: {e}")
        logger.error(traceback.format_exc())
        return jsonify({"error": "Kalender konnte nicht geladen werden."}), 500

    booked_slots = []
    for event in events:
        try:
            start = datetime.fromisoformat(event["start"]["dateTime"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(event["end"]["dateTime"].replace("Z", "+00:00"))
            booked_slots.append((start, end))
        except Exception as e:
            logger.warning(f"[GRAPH] Ungültiges Event-Format: {event} – {e}")

    tz = pytz.utc
    free_slots = []
    current = datetime.utcnow().replace(minute=0, second=0, microsecond=0, tzinfo=tz)
    end_time = current + timedelta(days=2)

    while current < end_time:
        start_slot = current
        end_slot = current + timedelta(hours=1)

        if 8 <= current.hour < 18:
            conflict = any(bs <= start_slot < be or bs < end_slot <= be for bs, be in booked_slots)
            if not conflict:
                free_slots.append(start_slot.isoformat())

        current += timedelta(hours=1)

    return jsonify({"free_slots": free_slots})

# === GPT-Analysefunktion ===
def call_gpt_to_extract_data(user_input):
    system_prompt = """Du bist ein Terminassistent. Analysiere Benutzereingaben und extrahiere:
- intent: "book_appointment" wenn ein Termin gebucht werden soll, sonst "none"
- name: vollständiger Name, falls vorhanden
- date: Datum im Format YYYY-MM-DD (falls erkannt)
- time: Uhrzeit im Format HH:MM (24h)
- reason: optionaler Text (Grund des Termins)

Antworte immer als JSON:
{"intent": ..., "name": ..., "date": ..., "time": ..., "reason": ...}"""

    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input}
            ],
            temperature=0.1
        )
        content = response.choices[0].message.content
        return eval(content)
    except Exception as e:
        logger.error(f"[GPT] Fehler: {e}")
        return {"intent": "none"}

# === Terminbuchung ===
def book_appointment(name, date_str, time_str, reason):
    access_token = session.get("access_token")
    if not access_token:
        return "⚠️ Bitte melde dich vorher über /calendar an."

    try:
        start_dt = datetime.fromisoformat(f"{date_str}T{time_str}:00")
        end_dt = start_dt + timedelta(hours=1)
    except Exception as e:
        return f"⛔ Ungültiges Datum oder Uhrzeit: {e}"

    event = {
        "subject": f"Termin: {reason or 'Allgemein'}",
        "body": {
            "contentType": "HTML",
            "content": f"Buchung durch {name}. Grund: {reason}"
        },
        "start": {
            "dateTime": start_dt.isoformat(),
            "timeZone": "UTC"
        },
        "end": {
            "dateTime": end_dt.isoformat(),
            "timeZone": "UTC"
        },
        "attendees": [],
        "location": {
            "displayName": "Online oder vor Ort"
        }
    }

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    url = "https://graph.microsoft.com/v1.0/me/calendar/events"

    try:
        res = requests.post(url, headers=headers, json=event)
        res.raise_for_status()
        return f"✅ Termin wurde für {name} am {date_str} um {time_str} Uhr gebucht."
    except Exception as e:
        logger.error(f"[GRAPH] Buchungsfehler: {e}")
        return "❌ Termin konnte nicht gebucht werden."

# === Chat mit Termin-Handling ===
@app.route("/chat", methods=["POST"])
def chat():
    user_input = request.json.get("message", "")

    gpt_response = call_gpt_to_extract_data(user_input)

    if gpt_response.get("intent") == "book_appointment":
        name = gpt_response.get("name")
        date = gpt_response.get("date")
        time = gpt_response.get("time")
        reason = gpt_response.get("reason")

        if not all([name, date, time]):
            return jsonify({"response": "Bitte gib deinen Namen, ein Datum (z. B. 2025-07-22) und eine Uhrzeit (z. B. 14:00) an."})

        response_text = book_appointment(name, date, time, reason)
        return jsonify({"response": response_text})

    return jsonify({"response": "Ich habe dich verstanden: " + user_input})

# === Root Test ===
@app.route("/")
def home():
    return "✅ LandKI Kalender-Integration + GPT läuft!"
