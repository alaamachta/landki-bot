from flask import Flask, request, jsonify
from flask_cors import CORS
import os

app = Flask(__name__)
CORS(app)  # CORS aktivieren für Web-Chat aus Elementor

@app.route("/", methods=["GET"])
def home():
    return "✅ LandKI Bot läuft erfolgreich!"

@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json()
    user_message = data.get("message", "").strip()

    if not user_message:
        return jsonify({"reply": "❗Bitte gib eine gültige Nachricht ein."}), 400

    # TEST-ANTWORT – Hier später GPT + Azure Search einbauen
    return jsonify({
        "reply": f"🧠 KI-Antwort: Du hast gesagt: \"{user_message}\""
    })
