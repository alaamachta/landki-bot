# app.py
import os
import logging
import pytz
import openai
import markdown2
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, session
from flask_cors import CORS
from msal import ConfidentialClientApplication
from azure.identity import DefaultAzureCredential
from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential
from bot_intent_router import detect_intent_with_gpt
from utils_outlook import get_free_time_slots, book_appointment
from utils_sql import save_patient_data
from utils_mail import send_confirmation_emails

# Initialisierung
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "secret")
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

# Logging (Europe/Berlin)
tz = pytz.timezone("Europe/Berlin")
logging.basicConfig(level=os.environ.get("WEBSITE_LOGGING_LEVEL", "INFO"))
logger = logging.getLogger("landki-bot")
logger.info("Bot gestartet um %s", datetime.now(tz).isoformat())

# OpenAI Konfiguration
openai.api_key = os.environ.get("OPENAI_API_KEY")
openai.api_base = os.environ.get("OPENAI_API_BASE")
openai.api_type = "azure"
openai.api_version = os.environ.get("OPENAI_API_VERSION", "2024-05-01-preview")
MODEL_NAME = os.environ.get("OPENAI_DEPLOYMENT_NAME", "gpt-4o")

# Speicher für Konversationsverlauf (minimal)
chat_sessions = {}

@app.route("/chat", methods=["POST"])
def chat():
    user_input = request.json.get("message", "")
    session_id = request.remote_addr  # alternativ: eigene session-ID
    logger.info("Neue Anfrage von %s: %s", session_id, user_input)

    if session_id not in chat_sessions:
        chat_sessions[session_id] = []

    # Intent erkennen
    intent = detect_intent_with_gpt(user_input)
    logger.info("Intent erkannt: %s", intent)

    # Einfache Routing-Logik
    if intent == "greeting":
        reply = "Hallo! Ich bin dein digitaler Assistent. Wie kann ich helfen?"
    elif intent == "book_appointment":
        reply = "📅 Du möchtest einen Termin buchen. Wie lautet dein **Vorname**?"
    elif intent == "status_request":
        reply = "🔍 Du möchtest deinen Terminstatus prüfen. Bitte nenne mir deinen **Vornamen**."
    elif intent == "cancel_appointment":
        reply = "❌ Du möchtest einen Termin stornieren. Wie lautet dein **Vorname**?"
    elif intent == "change_appointment":
        reply = "🔄 Du möchtest einen Termin ändern. Wie lautet dein **Vorname**?"
    elif intent == "smalltalk":
        reply = "🙂 Ich bin hier, um dir bei Terminen zu helfen. Wie kann ich dir helfen?"
    else:
        reply = "🤖 Ich habe das leider nicht verstanden. Möchtest du einen Termin **buchen**, **verschieben**, **absagen** oder **Status prüfen**?"

    chat_sessions[session_id].append({"role": "user", "content": user_input})
    chat_sessions[session_id].append({"role": "assistant", "content": reply})

    return jsonify({"reply": reply})

if __name__ == "__main__":
    app.run(debug=True)
