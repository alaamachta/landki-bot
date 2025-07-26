from flask import Flask, request, jsonify
import openai
import os
import logging
from flask_cors import CORS
from datetime import datetime
import pytz
from openai import AzureOpenAI, OpenAIError
import pyodbc  # SQL-Unterstützung

# === Flask App Setup ===
app = Flask(__name__)
CORS(app, resources={r"/chat": {"origins": "https://it-land.net"}}, methods=["POST"], allow_headers=["Content-Type"])

# === Logging Setup ===
LOG_LEVEL = os.environ.get("WEBSITE_LOGGING_LEVEL", "DEBUG")
logging.basicConfig(
    level=LOG_LEVEL,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler()]
)
tz = pytz.timezone("Europe/Berlin")
logging.Formatter.converter = lambda *args: datetime.now(tz).timetuple()

# === GPT Setup ===
client = AzureOpenAI(
    api_key=os.environ.get("AZURE_OPENAI_KEY"),
    azure_endpoint=os.environ.get("AZURE_OPENAI_ENDPOINT"),
    api_version=os.environ.get("OPENAI_API_VERSION", "2024-10-21")
)
MODEL_NAME = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")

# === SQL Setup ===
sql_server = os.environ.get("SQL_SERVER")
sql_db = os.environ.get("SQL_DATABASE")
sql_user = os.environ.get("SQL_USER")
sql_pwd = os.environ.get("SQL_PASSWORD")
conn_str = f"DRIVER={{ODBC Driver 18 for SQL Server}};SERVER={sql_server};DATABASE={sql_db};UID={sql_user};PWD={sql_pwd};Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"

def check_appointment(first_name, last_name, birthday):
    try:
        with pyodbc.connect(conn_str) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT appointment_date, appointment_time, symptoms, address
                FROM appointments
                WHERE first_name = ? AND last_name = ? AND birthday = ?
            """, first_name, last_name, birthday)
            row = cursor.fetchone()
            if row:
                return {
                    "date": row[0],
                    "time": row[1],
                    "symptoms": row[2],
                    "address": row[3]
                }
            else:
                return None
    except Exception as e:
        logging.error("SQL-Fehler: %s", e)
        return None

# === /chat Endpoint ===
@app.route("/chat", methods=["POST"])
def chat():
    try:
        logging.info("POST /chat aufgerufen")
        data = request.get_json()
        if not data or "message" not in data:
            logging.warning("Ungültiger Request Body: %s", data)
            return jsonify({"error": "Fehlender Parameter: 'message'"}), 400

        message = data["message"]
        logging.debug(f"Eingabe: {message}")

        # GPT-Request
        response = client.chat.completions.create(
            model=MODEL_NAME,
            temperature=0.3,
            max_tokens=1000,
            messages=[
                {"role": "system", "content": """
                    Du bist ein medizinischer KI-Assistent.
                    Wenn der Nutzer nach seinem Termin fragt, fordere ihn auf,
                    Vorname, Nachname und Geburtstag anzugeben.
                    Sobald du alle 3 hast, formatiere sie wie folgt:
                    /check_status|Vorname|Nachname|YYYY-MM-DD
                """},
                {"role": "user", "content": message}
            ]
        )

        gpt_answer = response.choices[0].message.content.strip()
        logging.info(f"Antwort: {gpt_answer}")

        if gpt_answer.startswith("/check_status"):
            _, first, last, bday = gpt_answer.split("|")
            result = check_appointment(first.strip(), last.strip(), bday.strip())
            if result:
                antwort = f"📅 Ihr Termin ist am <b>{result['date']} um {result['time']}</b> wegen <b>{result['symptoms']}</b>, Adresse: <b>{result['address']}</b>."
            else:
                antwort = "⚠️ Kein Termin gefunden. Bitte prüfen Sie Ihre Eingaben."
            return jsonify({"reply_html": antwort})

        return jsonify({"response": gpt_answer})

    except OpenAIError as e:
        logging.error("OpenAI API Fehler: %s", e)
        return jsonify({"error": "Fehler bei der Anfrage an GPT."}), 500

    except Exception as e:
        logging.exception("Unerwarteter Fehler:")
        return jsonify({"error": "Fehler beim Verarbeiten der Anfrage."}), 500

# === Healthcheck ===
@app.route("/", methods=["GET"])
def index():
    return "LandKI Bot ist online 🟢"

# === Lokaler Startpunkt ===
if __name__ == "__main__":
    app.run(debug=True, port=8000)
