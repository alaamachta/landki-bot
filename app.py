import datetime
from flask import Flask, redirect, session, url_for, request, jsonify
import msal
import requests
import logging
import pytz
from flask_cors import CORS

app = Flask(__name__)
app.secret_key = "DEIN-GEHEIMNIS"
CORS(app)

# === Konfiguration (ersetzen mit deinen Azure-Werten) ===
CLIENT_ID = "DEINE_CLIENT_ID"
CLIENT_SECRET = "DEIN_CLIENT_SECRET"
AUTHORITY = "https://login.microsoftonline.com/common"
REDIRECT_PATH = "/callback"
SCOPE = ["Calendars.Read", "User.Read"]
REDIRECT_URI = "https://DEINE-WEB-APP.azurewebsites.net" + REDIRECT_PATH


# === MSAL Setup ===
def _build_msal_app(cache=None):
    return msal.ConfidentialClientApplication(
        CLIENT_ID, authority=AUTHORITY,
        client_credential=CLIENT_SECRET, token_cache=cache
    )

def _build_auth_url(state=None):
    return _build_msal_app().get_authorization_request_url(
        SCOPE,
        state=state or str(datetime.datetime.now().timestamp()),
        redirect_uri=REDIRECT_URI
    )

def _get_token_from_cache():
    if not session.get("token_cache"):
        return None
    cache = msal.SerializableTokenCache()
    cache.deserialize(session["token_cache"])
    cca = _build_msal_app(cache)
    accounts = cca.get_accounts()
    if accounts:
        result = cca.acquire_token_silent(SCOPE, account=accounts[0])
        session["token_cache"] = cache.serialize()
        return result
    return None

# === Routen ===
@app.route("/")
def index():
    if not session.get("access_token"):
        return redirect("/calendar")
    return redirect("/available-times")

@app.route("/calendar")
def calendar_login():
    session["state"] = str(datetime.datetime.now().timestamp())
    return redirect(_build_auth_url(session["state"]))

@app.route("/callback")
def authorized():
    if request.args.get("state") != session.get("state"):
        return redirect("/calendar")

    cache = msal.SerializableTokenCache()
    result = _build_msal_app(cache).acquire_token_by_authorization_code(
        request.args["code"],
        scopes=SCOPE,
        redirect_uri=REDIRECT_URI
    )
    if "access_token" in result:
        session["access_token"] = result["access_token"]
        session["token_cache"] = cache.serialize()
        return redirect("/available-times")
    return "Login fehlgeschlagen"

@app.route("/available-times")
def available_times():
    token = session.get("access_token")
    if not token:
        return redirect("/calendar")

    try:
        slots = get_exact_free_slots(token)
        return jsonify(slots)
    except Exception as e:
        logging.exception("Fehler beim Abrufen der freien Zeiten")
        return f"Fehler: {str(e)}", 500

@app.route("/chat", methods=["POST"])
def chat():
    user_input = request.json.get("message", "")
    response = handle_appointment_request(user_input)
    if response:
        return jsonify({"reply_html": response})
    return jsonify({"reply_html": "🤖 Ich habe dich verstanden, aber stelle deine Frage bitte etwas genauer."})


# === Termin-Funktion: Outlook analysieren ===
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
        if current_day.weekday() >= 5:  # Wochenende überspringen
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


# === GPT-Termin-Logik (zeigt 3 freie Slots) ===
def handle_appointment_request(message_text):
    if any(keyword in message_text.lower() for keyword in ["termin", "verfügbar", "frei", "zeit", "buchbar"]):
        try:
            response = requests.get("https://DEINE-WEB-APP.azurewebsites.net/available-times")
            times = response.json()

            if not times:
                return "⚠️ Es wurden aktuell keine freien Termine gefunden."

            options = times[:3]
            list_items = ""
            for option in options:
                start = option["start"].replace(":", " Uhr ", 1)
                end = option["end"].split()[1]
                list_items += f"<li>🕒 {start} bis {end} Uhr</li>"

            html_response = f"""
            <div>
              <strong>✅ Folgende freie Termine sind verfügbar:</strong>
              <ul>{list_items}</ul>
              <p>Möchten Sie einen dieser Termine buchen<br>oder lieber ein späteres Datum wählen?</p>
              <p><em>Sie können z. B. antworten: „Später im September“ oder „Ja, Termin 2“</em></p>
            </div>
            """
            return html_response
        except Exception as e:
            print(f"Fehler beim Abrufen freier Zeiten: {e}")
            return "❌ Fehler beim Abrufen der Termine."
    return None
