import os
import logging
from flask import Flask, request, jsonify, session
from flask_cors import CORS
from datetime import datetime, timedelta
import pytz
import openai
import msal
import requests

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "secret")
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

# === Logging ===
berlin = pytz.timezone("Europe/Berlin")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
logger = logging.getLogger(__name__)

# === GPT Setup ===
openai.api_type = "azure"
openai.api_base = os.environ.get("OPENAI_API_BASE")
openai.api_key = os.environ.get("OPENAI_API_KEY")
openai.api_version = os.environ.get("OPENAI_API_VERSION")
deployment_id = os.environ.get("OPENAI_DEPLOYMENT_ID")

# === Outlook Setup ===
CLIENT_ID = os.environ.get("OUTLOOK_CLIENT_ID")
CLIENT_SECRET = os.environ.get("OUTLOOK_CLIENT_SECRET")
TENANT_ID = os.environ.get("OUTLOOK_TENANT_ID")
EMAIL_SENDER = os.environ.get("EMAIL_SENDER")
SCOPE = ["https://graph.microsoft.com/.default"]

# === MSAL Token Function ===
def get_token():
    app_msal = msal.ConfidentialClientApplication(
        client_id=CLIENT_ID,
        client_credential=CLIENT_SECRET,
        authority=f"https://login.microsoftonline.com/{TENANT_ID}"
    )
    result = app_msal.acquire_token_for_client(scopes=SCOPE)
    return result["access_token"]

# === Freie Termine analysieren ===
def get_available_slots():
    access_token = get_token()
    url = f"https://graph.microsoft.com/v1.0/users/{EMAIL_SENDER}/calendarview"
    headers = {"Authorization": f"Bearer {access_token}"}
    now = datetime.now().astimezone(berlin)
    start_time = now.replace(hour=9, minute=0, second=0, microsecond=0)
    end_time = (now + timedelta(days=2)).replace(hour=17)

    params = {
        "startDateTime": start_time.isoformat(),
        "endDateTime": end_time.isoformat(),
        "$top": 100
    }

    response = requests.get(url, headers=headers, params=params)
    events = response.json().get("value", [])

    busy_times = []
    for event in events:
        busy_times.append((event["start"]["dateTime"], event["end"]["dateTime"]))

    free_slots = []
    current = start_time
    while current + timedelta(minutes=15) <= end_time:
        slot_end = current + timedelta(minutes=30)
        conflict = any(
            current < datetime.fromisoformat(end) and slot_end > datetime.fromisoformat(start)
            for start, end in busy_times
        )
        if not conflict:
            free_slots.append({
                "start": current.strftime("%Y-%m-%d %H:%M"),
                "end": slot_end.strftime("%Y-%m-%d %H:%M")
            })
        current += timedelta(minutes=15)

    logger.info(f"Gefundene freie Slots: {len(free_slots)}")
    return free_slots

# === Termin eintragen in Outlook ===
def create_outlook_event(start_str, end_str, vorname, nachname):
    access_token = get_token()
    url = f"https://graph.microsoft.com/v1.0/users/{EMAIL_SENDER}/events"
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}

    body = {
        "subject": f"Neuer Termin: {vorname} {nachname}",
        "start": {"dateTime": start_str, "timeZone": "Europe/Berlin"},
        "end": {"dateTime": end_str, "timeZone": "Europe/Berlin"},
        "location": {"displayName": "Online / Praxis"},
        "attendees": [],
        "body": {
            "contentType": "HTML",
            "content": f"Neuer Termin gebucht von {vorname} {nachname}"
        }
    }

    response = requests.post(url, headers=headers, json=body)
    logger.info(f"Termin erstellt: {response.status_code}")
    return response.status_code == 201

# === GPT-Antwort generieren ===
def get_gpt_reply(message):
    messages = [
        {"role": "system", "content": "Du bist ein freundlicher Terminassistent für eine Arztpraxis. Frage schrittweise: 1. Vorname, 2. Nachname, 3. gewünschter Termin. Danach buche ihn. Sprich höflich und klar."},
        {"role": "user", "content": message}
    ]
    response = openai.ChatCompletion.create(
        engine=deployment_id,
        messages=messages,
        temperature=0.3
    )
    return response["choices"][0]["message"]["content"]

# === Flask-Routen ===
@app.route("/ping", methods=["GET"])
def ping():
    return "pong"

@app.route("/available-times", methods=["GET"])
def times():
    return jsonify(get_available_slots())

@app.route("/book-appointment", methods=["POST"])
def book():
    data = request.json
    vorname = data.get("vorname")
    nachname = data.get("nachname")
    start = data.get("start")
    end = data.get("end")

    logger.info(f"Buchung erhalten: {vorname} {nachname}, {start}–{end}")
    success = create_outlook_event(start, end, vorname, nachname)

    if success:
        return jsonify({"status": "success", "message": "Termin wurde erfolgreich eingetragen."})
    else:
        return jsonify({"status": "error", "message": "Fehler beim Eintragen des Termins."}), 500

@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json()
    message = data.get("message", "").lower()

    if "termin" in message:
        session["step"] = "vorname"
        return jsonify({"reply": "📅 Du möchtest einen Termin buchen. Wie lautet dein **Vorname**?"})

    elif session.get("step") == "vorname":
        session["vorname"] = message.strip().title()
        session["step"] = "nachname"
        return jsonify({"reply": "Wie lautet dein **Nachname**?"})

    elif session.get("step") == "nachname":
        session["nachname"] = message.strip().title()
        session["step"] = "terminwahl"
        slots = get_available_slots()
        buttons = [f"{s['start']} – {s['end']}" for s in slots[:3]]
        return jsonify({
            "reply": f"👍 Danke, {session['vorname']} {session['nachname']}.\nWähle bitte einen Termin aus:",
            "options": buttons
        })

    elif session.get("step") == "terminwahl":
        selected = message.strip()
        if "–" in selected:
            start, end = [s.strip().replace("–", "-") for s in selected.split("–")]
            success = create_outlook_event(start, end, session["vorname"], session["nachname"])
            if success:
                session.clear()
                return jsonify({"reply": "✅ Dein Termin wurde erfolgreich eingetragen. Du erhältst bald eine Bestätigung."})
            else:
                return jsonify({"reply": "❌ Es gab ein Problem beim Eintragen deines Termins. Bitte versuche es später erneut."})
        else:
            return jsonify({"reply": "Bitte wähle ein korrektes Zeitfenster."})

    # Fallback GPT
    reply = get_gpt_reply(message)
    return jsonify({"reply": reply})

# === Main ===
if __name__ == "__main__":
    app.run(debug=True)
