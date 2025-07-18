from flask import Flask, request, jsonify
from flask_cors import CORS
from flask import redirect, session, url_for
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
CORS(app)  # ⚠️ Wichtig für WordPress-Frontend-Zugriff

# === ENV Variablen laden ===
AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_KEY")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")
AZURE_SEARCH_ENDPOINT = os.getenv("AZURE_SEARCH_ENDPOINT")
AZURE_SEARCH_KEY = os.getenv("AZURE_SEARCH_KEY")
AZURE_SEARCH_INDEX = os.getenv("AZURE_SEARCH_INDEX")
OPENAI_API_VERSION = os.getenv("OPENAI_API_VERSION", "2024-07-18")
# 🔐 ENV Variablen für MS OAuth
MS_CLIENT_ID = os.getenv("MS_CLIENT_ID")
MS_CLIENT_SECRET = os.getenv("MS_CLIENT_SECRET")
MS_TENANT_ID = os.getenv("MS_TENANT_ID")
MS_REDIRECT_URI = os.getenv("MS_REDIRECT_URI")  # Azure-URL
MS_SCOPES = ["Calendars.Read"]
MS_AUTHORITY = f"https://login.microsoftonline.com/{MS_TENANT_ID}"
app.secret_key = os.getenv("SECRET_KEY")


# === ENV-Check-Tool ===
def check_env_vars(required_vars):
    all_ok = True
    for var in required_vars:
        value = os.getenv(var)
        if value:
            logger.info(f"[ENV] ✅ {var} gesetzt")
        else:
            logger.error(f"[ENV] ❌ {var} fehlt!")
            all_ok = False

    if not all_ok:
        logger.critical("🚫 Eine oder mehrere benötigte Umgebungsvariablen fehlen. Bot wird gestoppt.")
        exit(1)


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
        body = { "search": query, "top": 5 }

        logger.info(f"🔍 Azure Search mit: {query}")
        response = requests.post(url, headers=headers, json=body)
        response.raise_for_status()
        results = response.json()
        contents = [doc['content'] for doc in results.get('value', []) if 'content' in doc]
        logger.info(f"📦 {len(contents)} Dokumente aus Index gefunden")
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
        logger.info(f"👤 Eingabe vom User: {user_input}")

        context = search_azure(user_input)
        logger.info(f"📚 Kontext geladen ({len(context)} Zeichen)")

        prompt = f"Use the following context to answer the question:\n{context}\n\nQuestion: {user_input}\nAnswer:"

        response = client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2  # Geringe Kreativität, präzisere Antworten
        )

        answer = response.choices[0].message.content
        logger.info(f"✅ Antwort: {answer[:100]}...")

        return jsonify({
            "response": answer,
            "reply_html": markdown2.markdown(answer)
        })

    except Exception as e:
        logger.error("❌ Fehler im Chat-Endpunkt:")
        logger.error(traceback.format_exc())
        return jsonify({"error": "Fehler bei Verarbeitung", "details": str(e)}), 500

# === Health Check ===
@app.route("/")
def root():
    return "✅ LandKI ohne Übersetzungslogik läuft!"

# 🧠 Funktion: MSAL OAuth App initialisieren
def _build_msal_app():
    return msal.ConfidentialClientApplication(
        MS_CLIENT_ID,
        authority=MS_AUTHORITY,
        client_credential=MS_CLIENT_SECRET
    )

# 🧠 Funktion: Zugriffstoken holen
def _get_token_by_code(auth_code):
    return _build_msal_app().acquire_token_by_authorization_code(
        auth_code,
        scopes=MS_SCOPES,
        redirect_uri=MS_REDIRECT_URI
    )

# === OAuth Startpunkt: Login anstoßen ===
@app.route("/calendar")
def calendar_login():
    session["state"] = os.urandom(24).hex()
    auth_url = _build_msal_app().get_authorization_request_url(
        scopes=MS_SCOPES,
        state=session["state"],
        redirect_uri=MS_REDIRECT_URI
    )
    return redirect(auth_url)

# === OAuth Callback: Token empfangen, Kalender laden ===
@app.route("/callback")
def calendar_callback():
    if request.args.get('state') != session.get('state'):
        return "❌ Sicherheitsüberprüfung fehlgeschlagen", 400

    code = request.args.get('code')
    token_result = _get_token_by_code(code)

    if "access_token" not in token_result:
        return jsonify({"error": "Token konnte nicht geholt werden", "details": token_result.get("error_description")}), 500

    access_token = token_result["access_token"]
    headers = {'Authorization': f'Bearer {access_token}'}
    calendar_response = requests.get("https://graph.microsoft.com/v1.0/me/calendar/events", headers=headers)

    if calendar_response.status_code != 200:
        return jsonify({"error": "Kalenderdaten konnten nicht geladen werden", "details": calendar_response.text}), 500

    return jsonify(calendar_response.json())
