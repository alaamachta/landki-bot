from flask import Flask, request, jsonify, redirect, session
from flask_cors import CORS
import os, logging, traceback, requests
from colorlog import ColoredFormatter
from openai import AzureOpenAI
import markdown2
import msal

# — Logging Setup —
formatter = ColoredFormatter(
    "%(log_color)s[%(levelname)s]%(reset)s %(message)s",
    log_colors={'DEBUG': 'cyan','INFO': 'green','WARNING': 'yellow','ERROR': 'red','CRITICAL': 'bold_red'}
)
handler = logging.StreamHandler()
handler.setFormatter(formatter)
logger = logging.getLogger()
logger.addHandler(handler)
logger.setLevel(logging.DEBUG)  # DEBUG für Development

# — Flask App —
app = Flask(__name__)
CORS(app)

# — ENV-Variablen laden & prüfen —
def get_env(name, required=True):
    val = os.getenv(name)
    logger.debug(f"ENV {name} = {val!r}")
    if required and not val:
        logger.error(f"🚨 Fehlende Umgebungsvariable: {name}")
    return val

AZURE_OPENAI_API_KEY = get_env("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_ENDPOINT = get_env("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_DEPLOYMENT = get_env("AZURE_OPENAI_DEPLOYMENT")
OPENAI_API_VERSION = get_env("OPENAI_API_VERSION", required=False) or "2024-07-18"

# weitere ENV
AZURE_SEARCH_ENDPOINT = get_env("AZURE_SEARCH_ENDPOINT")
AZURE_SEARCH_KEY = get_env("AZURE_SEARCH_KEY")
AZURE_SEARCH_INDEX = get_env("AZURE_SEARCH_INDEX")
MS_CLIENT_ID = get_env("MS_CLIENT_ID")
MS_CLIENT_SECRET = get_env("MS_CLIENT_SECRET")
MS_TENANT_ID = get_env("MS_TENANT_ID")
MS_REDIRECT_URI = get_env("MS_REDIRECT_URI")
app.secret_key = get_env("SECRET_KEY")

# — Azure OpenAI Client Initialisierung —
try:
    client = AzureOpenAI(
        api_key=AZURE_OPENAI_API_KEY,
        api_version=OPENAI_API_VERSION,
        azure_endpoint=AZURE_OPENAI_ENDPOINT
    )
    logger.info("✅ AzureOpenAI-Client erfolgreich initialisiert!")
except Exception as e:
    logger.exception("❌ Fehler beim Initialisieren von AzureOpenAI-Client:")

# — Azure Search Funktion ---
def search_azure(query):
    try:
        headers = {"Content-Type":"application/json","api-key":AZURE_SEARCH_KEY}
        url = f"{AZURE_SEARCH_ENDPOINT}/indexes/{AZURE_SEARCH_INDEX}/docs/search?api-version=2023-07-01-Preview"
        response = requests.post(url, headers=headers, json={"search": query, "top": 5})
        response.raise_for_status()
        return "\n---\n".join(doc.get('content','') for doc in response.json().get('value', []))
    except Exception:
        logger.error("❌ Azure Search Error:", exc_info=True)
        return ""

# — Chat Endpoint —
@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json()
    user_input = data.get("message","")
    logger.info(f"👤 User fragt: {user_input!r}")
    context = search_azure(user_input)
    prompt = f"Nutze Kontext:\n{context}\nFrage: {user_input}\nAntwort:"
    try:
        resp = client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,
            messages=[{"role":"user","content":prompt}],
            temperature=0.2
        )
        answer = resp.choices[0].message.content
        logger.info(f"✅ Antwort empfangen ({len(answer)} Zeichen)")
        return jsonify(response=answer, reply_html=markdown2.markdown(answer))
    except Exception:
        logger.error("❌ Chatfehlers:", exc_info=True)
        return jsonify(error="Chat-Fehler aufgetreten"), 500

# — Health Check —
@app.route("/")
def root():
    return "✅ LandKI GPT-4o Bot läuft!"

# — MS OAuth für Kalenderanbindung —
MS_SCOPES = ["Calendars.Read","Calendars.ReadWrite"]
MS_AUTHORITY = f"https://login.microsoftonline.com/{MS_TENANT_ID}"

def _build_msal_app():
    return msal.ConfidentialClientApplication(MS_CLIENT_ID, authority=MS_AUTHORITY, client_credential=MS_CLIENT_SECRET)

@app.route("/calendar")
def calendar_login():
    session["state"] = os.urandom(24).hex()
    auth_url = _build_msal_app().get_authorization_request_url(
        scopes=MS_SCOPES, state=session["state"], redirect_uri=MS_REDIRECT_URI)
    return redirect(auth_url)

@app.route("/callback")
def calendar_callback():
    if request.args.get("state") != session.get("state"):
        return "❌ State mismatch", 400
    result = _build_msal_app().acquire_token_by_authorization_code(
        request.args.get("code"), scopes=MS_SCOPES, redirect_uri=MS_REDIRECT_URI)
    if "access_token" not in result:
        logger.error("Token Error: %r", result)
        return jsonify(error="Token-Fehler", details=result), 500
    events = requests.get("https://graph.microsoft.com/v1.0/me/calendar/events",
                          headers={"Authorization": f"Bearer {result['access_token']}"})
    return jsonify(events.json())

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
