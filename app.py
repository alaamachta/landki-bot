import os
import logging
import pytz
from flask import Flask, request, jsonify, session, redirect
from flask_cors import CORS
from datetime import datetime
import pyodbc

# Initialisiere Flask
app = Flask(__name__)
CORS(app)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "default_secret")

# Logging mit Zeitzone
berlin_tz = pytz.timezone("Europe/Berlin")
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logging.Formatter.converter = lambda *args: datetime.now(berlin_tz).timetuple()

# SQL-Verbindungsaufbau
SQL_SERVER = os.environ.get("SQL_SERVER")
SQL_DATABASE = os.environ.get("SQL_DATABASE")
SQL_USERNAME = os.environ.get("SQL_USERNAME")
SQL_PASSWORD = os.environ.get("SQL_PASSWORD")

# Verbindungs-String direkt zusammenbauen (wenn kein Full-Connection-String gesetzt)
SQL_DRIVER = "ODBC Driver 18 for SQL Server"

# Falls vorhanden, nutze vollen Verbindungsstring
SQL_CONN_STRING = os.environ.get("AZURE_SQL_CONNECTION_STRING") or (
    f"DRIVER={{{SQL_DRIVER}}};SERVER={SQL_SERVER};DATABASE={SQL_DATABASE};"
    f"UID={SQL_USERNAME};PWD={SQL_PASSWORD};Encrypt=yes;TrustServerCertificate=no;"
    f"Connection Timeout=30;"
)

def get_sql_connection():
    return pyodbc.connect(SQL_CONN_STRING)

@app.route("/")
def home():
    return "LandKI Bot is running."

@app.route("/book", methods=["POST"])
def book_appointment():
    try:
        data = request.get_json()

        # birthdate verarbeiten (z. B. "1990-01-01")
        birthdate = None
        if "birthdate" in data:
            try:
                birthdate = datetime.strptime(data["birthdate"], "%Y-%m-%d").date()
            except ValueError:
                logging.warning(f"❗ Ungültiges birthdate-Format: {data['birthdate']}")

        appointment_data = (
            data.get("first_name"),
            data.get("last_name"),
            birthdate,
            data.get("phone"),
            data.get("email"),
            data.get("symptom"),
            data.get("symptom_duration"),
            data.get("address"),
            data.get("appointment_start"),
            data.get("appointment_end"),
            datetime.now(pytz.timezone("Europe/Berlin")),
            data.get("company_code"),
            data.get("bot_origin"),
            data.get("service_type"),
            data.get("note_internal"),
        )

        conn = get_sql_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO appointments (
                first_name, last_name, birthdate, phone, email, symptom, symptom_duration,
                address, appointment_start, appointment_end, created_at,
                company_code, bot_origin, service_type, note_internal
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, appointment_data)

        conn.commit()
        cursor.close()
        conn.close()

        logging.info("✅ Termin erfolgreich eingetragen.")
        return jsonify({"status": "success"}), 200

    except Exception as e:
        logging.error(f"❌ Fehler bei Terminbuchung: {str(e)}")
        return jsonify({"error": "❌ Serverfehler"}), 500

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
