# app.py – LandKI Bot v1.0011 mit conversation_state und GPT-Chat ohne Azure Search

from flask import Flask, request, jsonify, session, redirect
from flask_cors import CORS
from openai import AzureOpenAI
import os
import logging
from datetime import datetime
import pytz
import uuid

# === Flask Setup ===
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)
app.secret_key = os.getenv("SECRET_KEY", os.urandom(24).hex())

# === Logging Setup ===
logging.basicConfig(
    level=os.environ.get("WEBSITE_LOGGING_LEVEL", "INFO"),
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler()]
)

# === OpenAI Setup ===
client = AzureOpenAI(
    api_key=os.environ["AZURE_OPENAI_KEY"],
    api_version=os.environ.get("OPENAI_API_VERSION", "2024-10-21"),
    azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"]
)
AZURE_DEPLOYMENT = os.environ["AZURE_OPENAI_DEPLOYMENT"]
TZ = pytz.timezone("Europe/Berlin")

# === In-Memory Conversation State ===
conversation_state = {}

# === System Prompt ===
system_prompt = """
Du bist ein professioneller Terminassistent einer Firma (kein Arzt). Du hilfst Kunden beim Buchen eines Termins.
Sprich freundlich, präzise, direkt und in **einfach verständlichem Deutsch**.

Frage nach folgenden Daten – du darfst sie kombinieren, aber NICHT überspringen:
1. Vorname (first_name)
2. Nachname (last_name)
3. E-Mail-Adresse (email)
4. Wunschtermin (selected_time) – erkenne natürliche Sprache wie "morgen 15 Uhr" oder "Freitag vormittags"
5. Grund / Nachricht (user_message) – z. B. „Möchten Sie uns noch etwas mitteilen?“

Wenn der Kunde einen Wunschtermin nennt, formatiere das Datum wie 2025-07-29T15:00 (UTC ISO Format).
Wenn ein Termin belegt oder ungültig ist, schlage Alternativen vor.
Wenn alle Daten vorliegen, fasse sie zusammen und leite die Buchung automatisch ein.
"""

# === Routes ===
@app.route("/")
def index():
    return "✅ LandKI Terminassistent v1.0011 läuft"

@app.route("/chat", methods=["POST"])
def chat():
    try:
        user_input = request.get_json().get("message", "")
        user_id = session.get("user_id")
        if not user_id:
            user_id = str(uuid.uuid4())
            session["user_id"] = user_id
            conversation_state[user_id] = []

        logging.info(f"👤 [{user_id}] Frage: {user_input}")

        conversation = conversation_state.get(user_id, [])
        conversation.append({"role": "user", "content": user_input})

        messages = [{"role": "system", "content": system_prompt}] + conversation

        response = client.chat.completions.create(
            model=AZURE_DEPLOYMENT,
            messages=messages,
            temperature=0.3
        )

        reply = response.choices[0].message.content
        conversation.append({"role": "assistant", "content": reply})
        conversation_state[user_id] = conversation[-20:]  # nur letzte 20 Messages merken

        logging.info(f"🤖 [{user_id}] Antwort: {reply[:80]}...")

        return jsonify({"response": reply})

    except Exception as e:
        logging.exception("Fehler im /chat")
        return jsonify({"error": str(e)}), 500
