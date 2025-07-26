from flask import Flask, request, jsonify
import openai
import os
import logging
from flask_cors import CORS
from datetime import datetime
import pytz
import pyodbc
from openai import AzureOpenAI, OpenAIError

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

# === SQL-Funktion: Terminstatus prüfen ===
def get_appointment_status(first_name, last_name, birthday):
    try:
        conn = pyodbc.connect(
            f'DRIVER={{ODBC Driver 18 for SQL Server}};SERVER=landki-sql-server.database.windows.net;DATABASE=landki-db;UID=landki.sql.server;PWD={os.environ.get("SQL_PASSWORD")}',
            timeout=5
        )
        cursor = conn.cursor()
        query = """
            SELECT appointment_start, address
            FROM dbo.appointments
            WHERE first_name = ? AND last_name = ? AND birthday = ?
        """
        cursor.execute(query, (first_name, last_name, birthday))
        row = cursor.fetchone()
        cursor.close()
        conn.close()

        if row:
            date_time, address = row
            date_str = date_time.strftime("%d.%m.%Y")
            time_str = date_time.strftime("%H:%M")
            return f"Ihr Termin ist am {date_str} um {time_str} Uhr in {address}."
        else:
            return "Es liegt aktuell kein Termin unter diesem Namen vor."

    except Exception as e:
        logging.exception("SQL-Abfragefehler:")
        return "Es gab ein Problem beim Abrufen des Termins. Bitte versuchen Sie es später erneut."

# === SQL-Funktion: Terminstatus stornieren ===
def cancel_appointment(first_name, last_name, birthday):
    try:
        conn = pyodbc.connect(
            f'DRIVER={{ODBC Driver 18 for SQL Server}};SERVER=landki-sql-server.database.windows.net;DATABASE=landki-db;UID=landki.sql.server;PWD={os.environ.get("SQL_PASSWORD")}',
            timeout=5
        )
        cursor = conn.cursor()
        
        # Prüfen ob Termin vorhanden ist
        check_query = """
            SELECT appointment_start FROM dbo.appointments
            WHERE first_name = ? AND last_name = ? AND birthday = ?
        """
        cursor.execute(check_query, (first_name, last_name, birthday))
        row = cursor.fetchone()
        
        if not row:
            return "Es liegt kein Termin unter diesem Namen vor."

        # Termin löschen
        delete_query = """
            DELETE FROM dbo.appointments
            WHERE first_name = ? AND last_name = ? AND birthday = ?
        """
        cursor.execute(delete_query, (first_name, last_name, birthday))
        conn.commit()

        date_str = row[0].strftime("%d.%m.%Y %H:%M")
        return f"Ihr Termin am {date_str} wurde erfolgreich storniert."

    except Exception as e:
        logging.exception("SQL-Stornierungsfehler:")
        return "Es gab ein Problem beim Stornieren des Termins. Bitte versuchen Sie es später erneut."


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

        response = client.chat.completions.create(
            model=MODEL_NAME,
            temperature=0.3,
            max_tokens=1000,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Du bist ein Terminassistent für die Firma LandKI.\n"
                        "Wenn der Nutzer seinen Vor- und Nachnamen sowie das Geburtsdatum nennt (z. B. 'Ali Muster 1990-01-01'), "
                        "extrahiere alle drei Angaben – auch dann korrekt, wenn sie in einem Satz oder nebeneinander genannt werden.\n\n"
    
                        "Beispiel:\n"
                        "Eingabe: Ali Muster 1990-01-01\n"
                        "→ Vorname = Ali, Nachname = Muster, Geburtstag = 1990-01-01\n\n"

                        "Reagiere nur dann mit Nachfragen, wenn eine dieser Informationen wirklich fehlt.\n\n"

                        "🟦 Wenn der Nutzer den **Status prüfen** will, darfst du folgende Python-Funktion verwenden:\n"
                        "→ `get_appointment_status(Vorname, Nachname, Geburtstag)`\n\n"

                        "🟥 Wenn der Nutzer einen **Termin stornieren** möchte, verwende:\n"
                        "→ `cancel_appointment(Vorname, Nachname, Geburtstag)`\n\n"

                        "Antworten immer freundlich und im Stil eines professionellen Assistenten. "
                        "Gib den Ergebnistext der Funktion direkt als Antwort aus."
                    )

                },
                {"role": "user", "content": message}
            ]
        )

        gpt_answer = response.choices[0].message.content
        logging.info(f"Antwort: {gpt_answer}")
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
