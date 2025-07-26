# ✅ Sichere Zwischenversion von app.py (GPT + Kalender + E-Mail + Search + Logging + Markdown)

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

# === Logging Setup mit Absicherung ===
formatter = ColoredFormatter(
    "%(log_color)s[%(levelname)s]%(reset)s %(message)s",
    log_colors={
        'DEBUG': 'cyan', 'INFO': 'green', 'WARNING': 'yellow', 'ERROR': 'red', 'CRITICAL': 'bold_red'
    }
)
handler = logging.StreamHandler()
handler.setFormatter(formatter)
logger = logging.getLogger()
logger.addHandler(handler)
log_level = os.getenv("WEBSITE_LOGGING_LEVEL", "INFO").upper()
logger.setLevel(getattr(logging, log_level, logging.INFO))
logger.info(f"🔧 LogLevel: {log_level}")

# === Flask Setup ===
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)
app.secret_key = os.getenv("SECRET_KEY", os.urandom(24).hex())

# === ENV Hilfsfunktion ===
def get_env_var(name, required=True):
    value = os.getenv(name)
    if not value and required:
        logger.error(f"❌ ENV fehlt: {name}")
        raise EnvironmentError(f"Missing env var: {name}")
    return value

# === ENV ===
AZURE_OPENAI_API_KEY    = get_env_var("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_ENDPOINT   = get_env_var("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_DEPLOYMENT = get_env_var("AZURE_OPENAI_DEPLOYMENT")
AZURE_SEARCH_ENDPOINT   = get_env_var("AZURE_SEARCH_ENDPOINT")
AZURE_SEARCH_KEY        = get_env_var("AZURE_SEARCH_KEY")
AZURE_SEARCH_INDEX      = get_env_var("AZURE_SEARCH_INDEX")
OPENAI_API_VERSION      = get_env_var("OPENAI_API_VERSION", False) or "2024-07-01-preview"

MS_CLIENT_ID      = get_env_var("MS_CLIENT_ID")
MS_CLIENT_SECRET  = get_env_var("MS_CLIENT_SECRET")
MS_TENANT_ID      = get_env_var("MS_TENANT_ID")
MS_REDIRECT_URI   = get_env_var("MS_REDIRECT_URI")
MS_SCOPES         = ["Calendars.Read", "Calendars.ReadWrite", "Mail.Send"]
MS_AUTHORITY      = f"https://login.microsoftonline.com/{MS_TENANT_ID}"

# === GPT Client ===
client = AzureOpenAI(
    api_key=AZURE_OPENAI_API_KEY,
    api_version=OPENAI_API_VERSION,
    azure_endpoint=AZURE_OPENAI_ENDPOINT
)

# === Azure Search ===
def search_azure(query):
    try:
        url = f"{AZURE_SEARCH_ENDPOINT}/indexes/{AZURE_SEARCH_INDEX}/docs/search?api-version=2023-07-01-Preview"
        headers = {
            "Content-Type": "application/json",
            "api-key": AZURE_SEARCH_KEY,
            "Accept": "application/json;odata.metadata=none"
        }
        body = {"search": query, "top": 5}
        logger.info(f"🔍 Suche: {query}")
        res = requests.post(url, headers=headers, json=body)
        res.raise_for_status()
        docs = res.json().get("value", [])
        return "\n---\n".join(d.get("content", "") for d in docs if "content" in d)
    except Exception:
        logger.error("❌ Azure Search Fehler:")
        logger.error(traceback.format_exc())
        return "Fehler bei Azure Search."

# === MSAL ===
def _build_msal():
    return msal.ConfidentialClientApplication(
        MS_CLIENT_ID, authority=MS_AUTHORITY, client_credential=MS_CLIENT_SECRET
    )

def _get_token_by_code(code):
    return _build_msal().acquire_token_by_authorization_code(
        code, scopes=MS_SCOPES, redirect_uri=MS_REDIRECT_URI
    )

# === Routen ===
@app.route("/")
def root():
    return "✅ LandKI GPT-Terminal aktiv"

@app.route("/chat", methods=["POST"])
def chat():
    try:
        if not request.json:
            return jsonify({"error": "Kein JSON erhalten."}), 400

        user_input = request.json.get("message", "")
        logger.info(f"👤 Frage: {user_input}")
        context = search_azure(user_input)
        prompt = f"Nutze diesen Kontext zur Beantwortung:\n{context}\n\nFrage: {user_input}\nAntwort:"

        res = client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3
        )
        answer = res.choices[0].message.content
        logger.info(f"✅ GPT-Antwort: {answer[:100]}")
        return jsonify({"response": answer, "reply_html": markdown2.markdown(answer)})

    except Exception:
        logger.error("❌ Fehler im Chat:")
        logger.error(traceback.format_exc())
        return jsonify({"error": "Fehler beim Chat"}), 500

@app.route("/calendar")
def calendar_login():
    session["state"] = os.urandom(24).hex()
    url = _build_msal().get_authorization_request_url(
        scopes=MS_SCOPES, state=session["state"], redirect_uri=MS_REDIRECT_URI
    )
    return redirect(url)

@app.route("/callback")
def calendar_callback():
    if request.args.get("state") != session.get("state"):
        return "❌ Ungültiger State", 400
    code = request.args.get("code")
    token_result = _get_token_by_code(code)
    if "access_token" not in token_result:
        return jsonify({"error": "Kein Token", "details": token_result.get("error_description")}), 500
    session["access_token"] = token_result["access_token"]
    return "✅ Kalenderzugriff gespeichert."

@app.route("/send-mail", methods=["POST"])
def send_mail():
    try:
        token = session.get("access_token")
        if not token:
            return redirect("/calendar")

        data = request.json
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        payload = {
            "message": {
                "subject": data.get("subject"),
                "body": {"contentType": "Text", "content": data.get("body")},
                "toRecipients": [{"emailAddress": {"address": data.get("to")}}]
            },
            "saveToSentItems": "true"
        }
        res = requests.post("https://graph.microsoft.com/v1.0/me/sendMail", headers=headers, json=payload)
        if res.status_code == 202:
            return jsonify({"status": "success", "message": "E-Mail gesendet."})
        else:
            logger.error(f"❌ E-Mail-Fehler: {res.text}")
            return jsonify({"status": "error", "details": res.text}), 500

    except Exception:
        logger.error("❌ E-Mail-Versand fehlgeschlagen:")
        logger.error(traceback.format_exc())
        return jsonify({"error": "Fehler beim Mailversand"}), 500
