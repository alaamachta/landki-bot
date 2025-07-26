from flask import Flask, request, jsonify, session
from flask_cors import CORS
import openai
import logging
import os
import datetime
import pytz
import pyodbc
import msal
import requests
import uuid
from dateutil import parser

# Flask App Setup
app = Flask(__name__)
CORS(app)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "1234")

# GPT Setup (Azure OpenAI)
openai.api_type = "azure"
openai.api_base = os.environ["AZURE_OPENAI_ENDPOINT"]  # angepasst
openai.api_version = os.environ.get("OPENAI_API_VERSION", "2024-05-01-preview")
openai.api_key = os.environ["AZURE_OPENAI_KEY"]  # angepasst
GPT_DEPLOYMENT = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")

# SQL Setup
SQL_CONNECTION_STRING = os.environ["AZURE_SQL_CONNECTION_STRING"]  # vereinfacht, da gesamte Verbindungszeichenfolge vorhanden ist

# Logging Setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("LandKI-Bot")

# Timezone
TIMEZONE = pytz.timezone("Europe/Berlin")

# Route: book appointment
@app.route("/book-appointment", methods=["POST"])
def book_appointment():
    try:
        data = request.json

        # Extract patient data
        first_name = data.get("first_name")
        last_name = data.get("last_name")
        birthday = data.get("birthday")
        phone = data.get("phone")
        email = data.get("email")
        symptoms = data.get("symptoms")
        duration = data.get("duration")
        address = data.get("address")
        appointment_start = data.get("appointment_start")
        appointment_end = data.get("appointment_end")

        logger.info(f"📅 Buche Termin für {first_name} {last_name} am {appointment_start}")

        # SQL Insert
        with pyodbc.connect(SQL_CONNECTION_STRING) as conn:
            cursor = conn.cursor()
            insert_query = """
                INSERT INTO appointments (first_name, last_name, birthday, phone, email, symptoms, duration, address, appointment_start, appointment_end)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            cursor.execute(insert_query, (
                first_name, last_name, birthday, phone, email,
                symptoms, duration, address, appointment_start, appointment_end
            ))
            conn.commit()
            logger.info("✅ Patientendaten erfolgreich in SQL gespeichert")

        return jsonify({"status": "success", "message": "Termin gebucht und gespeichert."})

    except Exception as e:
        logger.error(f"❌ Fehler bei Terminbuchung: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# Health check
@app.route("/", methods=["GET"])
def health_check():
    return "LandKI Bot läuft."

if __name__ == "__main__":
    app.run(debug=True)
