import os
import logging
import traceback
from datetime import datetime, timedelta

from flask import Flask, jsonify, request, redirect, session
from flask_cors import CORS
from flask_session import Session
import msal
import requests

from azure.identity import DefaultAzureCredential
from azure.search.documents import SearchClient
from openai import AzureOpenAI

# === Setup ===
app = Flask(__name__)
CORS(app)

app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev")
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === ENV Variablen ===
MS_CLIENT_ID = os.environ.get("MS_CLIENT_ID")
MS_CLIENT_SECRET = os.environ.get("MS_CLIENT_SECRET")
MS_TENANT_ID = os.environ.get("MS_TENANT_ID")
MS_AUTHORITY = f"https://login.microsoftonline.com/{MS_TENANT_ID}"
MS_SCOPES = ["Calendars.Read", "offline_access", "User.Read", "openid", "profile", "email"]
MS_REDIRECT_URI = os.environ.get("MS_REDIRECT_URI")

OPENAI_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT")
OPENAI_API_KEY = os.environ.get("AZURE_OPENAI_KEY")
OPENAI_DEPLOYMENT = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")

SEARCH_ENDPOINT = os.environ.get("AZURE_SEARCH_ENDPOINT")
SEARCH_KEY = os.environ.get("AZURE_SEARCH_KEY")
SEARCH_INDEX = os.environ.get("AZURE_SEARCH_INDEX")

# === Funktionen ===
def _build_msal_app(cache=None):
    return msal.ConfidentialClientApplication(
        MS_CLIENT_ID, authority=MS_AUTHORITY,
        client_credential=MS_CLIENT_SECRET, token_cache=cache
    )

def _get_token_by_code(code):
    result = _build_msal_app().acquire_token_by_authorization_code(
        code,
        scopes=MS_SCOPES,
        redirect_uri=MS_REDIRECT_URI
    )
    return result

def _get_graph_headers():
    return {
        "Authorization": f"Bearer {session['access_token']}",
        "Content-Type": "application/json"
    }

# === Routen ===
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
    if request.args.get("state") != session.get("state"):
        return "State mismatch!", 400

    code = request.args.get("code")
    try:
        token_result = _get_token_by_code(code)
        logger.info(f"[MSAL] Token erhalten: {token_result}")
    except Exception as e:
        logger.error(f"[MSAL] Fehler beim Token holen: {str(e)}")
        logger.error(traceback.format_exc())
        return "Fehler beim MSAL-Token holen", 500

    if "access_token" not in token_result:
        return jsonify({
            "error": "Token konnte nicht geholt werden",
            "details": token_result.get("error_description")
        }), 500

    session["access_token"] = token_result["access_token"]
    return redirect("/available-times")

@app.route("/available-times")
def available_times():
    try:
        now = datetime.utcnow()
        start = now.isoformat() + "Z"
        end = (now + timedelta(days=7)).isoformat() + "Z"
        logger.info(f"[Graph] Hole Kalenderdaten von {start} bis {end}")

        response = requests.get(
            f"https://graph.microsoft.com/v1.0/me/calendarview?startDateTime={start}&endDateTime={end}",
            headers=_get_graph_headers()
        )
        logger.info(f"[Graph] Status: {response.status_code}")
        logger.info(f"[Graph] Response Body: {response.text}")

        if response.status_code != 200:
            logger.error("❌ Fehler beim Abrufen der Kalenderdaten.")
            return jsonify({"error": "Kalenderzugriff fehlgeschlagen"}), 401

        events = response.json().get("value", [])
        used_slots = [
            (e["start"]["dateTime"], e["end"]["dateTime"]) for e in events
        ]

        free_slots = []
        current = now.replace(hour=9, minute=0, second=0, microsecond=0)
        end_day = now + timedelta(days=7)

        while current < end_day:
            slot_end = current + timedelta(hours=1)
            if current.weekday() < 5:  # Mo–Fr
                overlapping = any(
                    current.isoformat() < end and slot_end.isoformat() > start
                    for start, end in used_slots
                )
                if not overlapping:
                    free_slots.append(current.strftime("%Y-%m-%d %H:%M"))
            current += timedelta(hours=1)

        return jsonify({"free_slots": free_slots})

    except Exception as e:
        logger.error(f"❌ Fehler in /available-times: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({"error": "Fehler beim Verarbeiten"}), 500

@app.route("/ask", methods=["POST"])
def ask():
    data = request.get_json()
    query = data.get("question", "")
    if not query:
        return jsonify({"error": "Keine Frage angegeben"}), 400

    search_client = SearchClient(
        endpoint=SEARCH_ENDPOINT,
        index_name=SEARCH_INDEX,
        credential=SEARCH_KEY
    )
    results = search_client.search(query)
    contents = "\n\n".join([doc["content"] for doc in results])

    client = AzureOpenAI(
        azure_endpoint=OPENAI_ENDPOINT,
        api_key=OPENAI_API_KEY,
        api_version="2024-02-15-preview"
    )
    response = client.chat.completions.create(
        model=OPENAI_DEPLOYMENT,
        messages=[
            {"role": "system", "content": "Antworte nur mit Inhalten von IT-Land. Wenn nicht vorhanden, sag das ehrlich."},
            {"role": "user", "content": f"Frage: {query}\n\nKontext:\n{contents}"}
        ],
        temperature=0.3
    )
    return jsonify({"answer": response.choices[0].message.content})

# === Starten ===
if __name__ == "__main__":
    app.run(debug=True)
