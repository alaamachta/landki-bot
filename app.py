from flask import Flask, request, jsonify, redirect, session
from flask_cors import CORS
import os
import logging
import traceback
import requests
from colorlog import ColoredFormatter
from openai import AzureOpenAI
from urllib.parse import urlencode
import markdown2
import msal
from datetime import datetime, timedelta
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

# === Flask App Setup ===
app = Flask(__name__)
CORS(app)
app.secret_key = os.getenv("SECRET_KEY")

# === Sichere ENV-Initialisierung ===
def get_env_var(name, required=True):
    value = os.getenv(name)
    if not value and required:
        logger.error(f"❌ Umgebungsvariable '{name}' fehlt!")
        raise EnvironmentError(f"Missing environment variable: {name}")
    return value

# === ENV-Variablen laden ===
AZURE_OPENAI_API_KEY      = get_env_var("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_ENDPOINT     = get_env_var("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_DEPLOYMENT   = get_env_var("AZURE_OPENAI_DEPLOYMENT")
AZURE_SEARCH_ENDPOINT     = get_env_var("AZURE_SEARCH_ENDPOINT")
AZURE_SEARCH_KEY          = get_env_var("AZURE_SEARCH_KEY")
AZURE_SEARCH_INDEX        = get_env_var("AZURE_SEARCH_INDEX")
OPENAI_API_VERSION        = os.getenv("OPENAI_API_VERSION", "2024-07-18")

MS_CLIENT_ID              = get_env_var("MS_CLIENT_ID")
MS_CLIENT_SECRET          = get_env_var("MS_CLIENT_SECRET")
MS_TENANT_ID              = get_env_var("MS_TENANT_ID")
MS_REDIRECT_URI           = get_env_var("MS_REDIRECT_URI")
MS_SCOPES                 = ["Calendars.Read", "Calendars.ReadWrite"]
MS_AUTHORITY              = f"https://login.microsoftonline.com/{MS_TENANT_ID}"

# === OpenAI Client ===
try:
    client = AzureOpenAI(
        api_key=AZURE_OPENAI_API_KEY,
        api_version=OPENAI_API_VERSION,
        azure_endpoint=AZURE_OPENAI_ENDPOINT
    )
    logger.info("✅ AzureOpenAI-Client initialisiert.")
except Exception:
    logger.error("❌ Fehler bei AzureOpenAI-Initialisierung:")
    logger.error(traceback.format_exc())
    raise

# === Azure Cognitive Search Funktion ===
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
        logger.info(f"📦 {len(contents)} Dokumente gefunden.")
        return "\n---\n".join(contents)
    except Exception:
        logger.error("❌ Azure Search fehlgeschlagen:")
        logger.error(traceback.format_exc())
        return "Fehler bei der Azure Search."

# === GPT Chat Endpoint mit Kontext ===
@app.route("/chat", methods=["POST"])
def chat():
    try:
        user_input = request.json.get("message", "")
        logger.info(f"👤 Benutzer: {user_input}")

        context = search_azure(user_input)
        prompt = f"Nutze diesen Kontext zur Beantwortung der Frage:\n{context}\n\nFrage: {user_input}\nAntwort:"

        response = client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2
        )

        answer = response.choices[0].message.content
        logger.info(f"✅ GPT-Antwort: {answer[:100]}...")

        return jsonify({
            "response": answer,
            "reply_html": markdown2.markdown(answer)
        })

    except Exception:
        logger.error("❌ Fehler im Chat-Endpunkt:")
        logger.error(traceback.format_exc())
        return jsonify({"error": "Fehler bei Verarbeitung"}), 500

# === Root Health Check ===
@app.route("/")
def root():
    return "✅ LandKI GPT-4o Bot läuft!"

# === ENV-Debug-Rückgabe (nur temporär verwenden!) ===
@app.route("/env-debug")
def env_debug():
    return jsonify({
        "AZURE_OPENAI_API_KEY": os.getenv("AZURE_OPENAI_API_KEY"),
        "AZURE_OPENAI_ENDPOINT": os.getenv("AZURE_OPENAI_ENDPOINT"),
        "AZURE_OPENAI_DEPLOYMENT": os.getenv("AZURE_OPENAI_DEPLOYMENT"),
        "AZURE_SEARCH_KEY": os.getenv("AZURE_SEARCH_KEY"),
    })

# === MSAL Auth & Kalenderintegration ===
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
        return "❌ Sicherheitsüberprüfung fehlgeschlagen", 400

    code = request.args.get('code')
    token_result = _get_token_by_code(code)

    if "access_token" not in token_result:
        return jsonify({
            "error": "Token konnte nicht geholt werden",
            "details": token_result.get("error_description")
        }), 500

    session["access_token"] = token_result["access_token"]
    logger.info("🔑 Outlook-Zugriffstoken gespeichert.")
    return "✅ Kalenderzugriff erfolgreich."

# === Terminbuchung via GPT (Name, Symptom, Datum) ===
@app.route("/book-appointment", methods=["POST"])
def book_appointment():
    try:
        data = request.get_json()
        user_message = data.get("message", "")
        logger.info(f"📩 Buchungsanfrage: {user_message}")

        gpt_response = client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,
            messages=[
                {"role": "system", "content": (
                    "Du bist ein Praxisassistent. Extrahiere Name, Symptom, Datum im Format YYYY-MM-DD. "
                    "Antworte nur mit: {\"name\": \"\", \"symptom\": \"\", \"date\": \"YYYY-MM-DD\"}"
                )},
                {"role": "user", "content": user_message}
            ],
            temperature=0.2
        )

        extracted = json.loads(gpt_response.choices[0].message.content)
        name = extracted.get("name")
        symptom = extracted.get("symptom")
        date_str = extracted.get("date")

        logger.info(f"🤖 GPT-Daten: {extracted}")

        if not name or not date_str:
            return jsonify({"error": "Name oder Datum fehlt."}), 400

        start = datetime.fromisoformat(date_str + "T09:00:00+02:00")
        end = start + timedelta(hours=1)

        access_token = session.get("access_token")
        if not access_token:
            return redirect("/calendar")

        headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
        event = {
            "subject": f"Termin: {name} – {symptom}",
            "start": {"dateTime": start.isoformat(), "timeZone": "Europe/Berlin"},
            "end": {"dateTime": end.isoformat(), "timeZone": "Europe/Berlin"},
            "body": {"contentType": "Text", "content": f"Symptom: {symptom}"},
            "location": {"displayName": "LandKI Online"},
            "attendees": []
        }

        response = requests.post("https://graph.microsoft.com/v1.0/me/events", headers=headers, json=event)

        if response.status_code == 201:
            logger.info(f"✅ Termin gebucht: {name} am {date_str}")
            return jsonify({"status": "success", "message": f"Termin für {name} am {date_str} um 09:00 Uhr gebucht."})
        else:
            logger.error(f"❌ Fehler bei Terminbuchung: {response.text}")
            return jsonify({"status": "error", "message": "Termin konnte nicht gebucht werden."}), 500

    except Exception:
        logger.error("💥 Fehler bei Terminbuchung:")
        logger.error(traceback.format_exc())
        return jsonify({"error": "Fehler bei der Terminverarbeitung"}), 500
