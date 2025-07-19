import os
import logging
import traceback
from flask import Flask, request, jsonify, redirect, session
from flask_cors import CORS
from datetime import datetime, timedelta
import pytz
import msal
import requests

# === Flask Setup ===
app = Flask(__name__)
CORS(app)
app.secret_key = os.getenv("SECRET_KEY")  # z. B. xXotgkvSMVQQJ55sKNRMf9

# === Microsoft Identity ===
MS_CLIENT_ID = os.getenv("MS_CLIENT_ID")
MS_CLIENT_SECRET = os.getenv("MS_CLIENT_SECRET")
MS_TENANT_ID = os.getenv("MS_TENANT_ID")
MS_REDIRECT_URI = os.getenv("MS_REDIRECT_URI")  # z. B. https://dein-bot.azurewebsites.net/callback
MS_AUTHORITY = f"https://login.microsoftonline.com/{MS_TENANT_ID}"
MS_SCOPES = ["User.Read", "Calendars.Read"]  # KEINE reservierten Scopes hier

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

# === Kalender Auth ===
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

    params = {
        "$filter": f"start/dateTime ge '{now}' and end/dateTime le '{end}'"
    }


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

    # Gebuchte Zeiten
    booked_slots = []
    for event in events:
        try:
            start = datetime.fromisoformat(event["start"]["dateTime"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(event["end"]["dateTime"].replace("Z", "+00:00"))
            booked_slots.append((start, end))
        except Exception as e:
            logger.warning(f"[GRAPH] Ungültiges Event-Format: {event} – {e}")

    # Freie Slots zwischen 08:00–18:00 Uhr in UTC
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

# === Root-Check ===
@app.route("/")
def home():
    return "✅ LandKI Kalender-Integration läuft!"
