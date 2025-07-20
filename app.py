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
CORS(app)  # Wichtig für Verbindung zu WordPress / Elementor

# === ENV-Variablen ===
AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
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

# === Debug: ENV-Check ===
logger.info(f"🔐 AZURE_OPENAI_API_KEY gesetzt: {'JA' if AZURE_OPENAI_API_KEY else 'NEIN'}")
logger.info(f"🌍 AZURE_OPENAI_ENDPOINT: {AZURE_OPENAI_ENDPOINT}")
logger.info(f"🧠 AZURE_OPENAI_DEPLOYMENT: {AZURE_OPENAI_DEPLOYMENT}")
logger.info(f"🔎 AZURE_SEARCH_INDEX: {AZURE_SEARCH_INDEX}")
logger.info(f"🔑 SECRET_KEY gesetzt: {'JA' if app.secret_key else 'NEIN'}")

# === OpenAI Client ===
try:
    client = AzureOpenAI(
        api_key=AZURE_OPENAI_API_KEY,
        api_version=OPENAI_API_VERSION,
        azure_endpoint=AZURE_OPENAI_ENDPOINT
    )
except Exception:
    logger.error("❌ Fehler bei AzureOpenAI-Initialisierung:")
    logger.error(traceback.format_exc())
    raise

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
        logger.info(f"📦 {len(contents)} Dokumente aus Index gefunden")
        return "\n---\n".join(contents)
    except Exception:
        logger.error("❌ Fehler bei Azure Search:")
        logger.error(traceback.format_exc())
        return "Fehler bei der Azure Search."

# === Chat Endpoint ===
@app.route("/chat", methods=["POST"])
def chat():
    try:
        user_input = request.json.get("message", "")
        logger.info(f"👤 Eingabe vom User: {user_input}")

        context = search_azure(user_input)
        logger.info(f"📚 Kontext geladen ({len(context)} Zeichen)")

        prompt = f"Nutze diesen Kontext zur Beantwortung der Frage:\n{context}\n\nFrage: {user_input}\nAntwort:"

        response = client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2
        )

        answer = response.choices[0].message.content
        logger.info(f"✅ Antwort: {answer[:100]}...")

        return jsonify({
            "response": answer,
            "reply_html": markdown2.markdown(answer)
        })

    except Exception:
        logger.error("❌ Fehler im Chat-Endpunkt:")
        logger.error(traceback.format_exc())
        return jsonify({"error": "Fehler bei Verarbeitung"}), 500

# === Health Check ===
@app.route("/")
def root():
    return "✅ LandKI GPT-4o Bot läuft!"

# === OAuth: MS-Kalenderanbindung ===
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

    access_token = token_result["access_token"]
    headers = {'Authorization': f'Bearer {access_token}'}
    calendar_response = requests.get("https://graph.microsoft.com/v1.0/me/calendar/events", headers=headers)

    if calendar_response.status_code != 200:
        return jsonify({
            "error": "Kalenderdaten konnten nicht geladen werden",
            "details": calendar_response.text
        }), 500

    return jsonify(calendar_response.json())
