# ✅ Vollständige app.py (Szenario 3 – Termin stornieren)

from flask import Flask, request, jsonify, session
import pyodbc
import logging
import msal
import smtplib
from email.mime.text import MIMEText
from datetime import datetime
import pytz
import os

# 🌍 Flask Setup
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "geheim")

# 🧠 GPT-Systemprompt (vereinfacht)
SYSTEM_PROMPT = """
Du bist LandKI, ein smarter Terminassistent.
Der Nutzer nennt dir Name + Geburtsdatum im Format YYYY-MM-DD.
Wenn er "stornieren" oder "Termin absagen" sagt, rufe cancel_appointment(...) auf.

Führe danach automatisch Folgendes aus:
1. Lösche SQL-Eintrag
2. Sende E-Mail-Bestätigung an Patient + Praxis
3. Gib klare Rückmeldung wie: "Ihr Termin wurde erfolgreich storniert."

Wenn kein Termin vorhanden ist, gib Rückmeldung wie: "Es liegt kein Termin für Sie vor."
"""

# 🗂️ SQL-Verbindung
SQL_SERVER = "landki-sql-server.database.windows.net"
SQL_DATABASE = "landki-db"
SQL_USERNAME = "landki.sql.server"
SQL_PASSWORD = os.environ.get("SQL_PASSWORD")  # In GitHub Secret speichern

def get_sql_connection():
    conn_str = f"DRIVER={{ODBC Driver 18 for SQL Server}};SERVER={SQL_SERVER};DATABASE={SQL_DATABASE};UID={SQL_USERNAME};PWD={SQL_PASSWORD};Encrypt=yes;TrustServerCertificate=no;"
    return pyodbc.connect(conn_str)

# 📧 E-Mail-Versand
SMTP_SERVER = "smtp.office365.com"
SMTP_PORT = 587
SMTP_USERNAME = "AlaaMashta@LandKI.onmicrosoft.com"
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD")
SENDER_NAME = "LandKI Praxis"
PRAXIS_EMAIL = "info@landki.com"

def send_email(to_address, subject, body):
    msg = MIMEText(body, "plain")
    msg["Subject"] = subject
    msg["From"] = f"{SENDER_NAME} <{SMTP_USERNAME}>"
    msg["To"] = to_address

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.sendmail(SMTP_USERNAME, [to_address], msg.as_string())

# 📦 Termin-Stornierung

def cancel_appointment(first_name, last_name, birthday):
    logging.info(f"[🧩 Cancel Request] {first_name} {last_name}, {birthday}")
    conn = get_sql_connection()
    cursor = conn.cursor()
    query = "SELECT * FROM appointments WHERE first_name = ? AND last_name = ? AND birthday = ?"
    cursor.execute(query, (first_name, last_name, birthday))
    row = cursor.fetchone()

    if row:
        delete_query = "DELETE FROM appointments WHERE first_name = ? AND last_name = ? AND birthday = ?"
        cursor.execute(delete_query, (first_name, last_name, birthday))
        conn.commit()
        logging.info("[✅ Termin gelöscht]")

        # 📧 E-Mail senden
        patient_email = row.email if hasattr(row, 'email') and row.email else None
        subject = "Terminabsage bestätigt"
        body = f"Sehr geehrte/r {first_name} {last_name},\n\nIhr Termin am {row.date} um {row.time} wurde erfolgreich storniert.\n\nViele Grüße\nIhr LandKI-Team"

        if patient_email:
            send_email(patient_email, subject, body)
        send_email(PRAXIS_EMAIL, f"Termin storniert: {first_name} {last_name}", body)

        return f"✅ Der Termin von {first_name} {last_name} wurde erfolgreich storniert."
    else:
        logging.warning("[❌ Kein passender Termin gefunden]")
        return f"❌ Es wurde kein Termin für {first_name} {last_name} mit Geburtsdatum {birthday} gefunden."

# 🌐 Endpunkt für GPT-Kommunikation
@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json()
    user_message = data.get("message", "")

    # Hier kommt deine GPT-Logik hin (nicht im Beispiel enthalten)
    return jsonify({"reply": "Noch nicht implementiert"})

# 🧪 Test-Route (nur temporär zum Testen)
@app.route("/cancel_test", methods=["POST"])
def cancel_test():
    data = request.get_json()
    first_name = data.get("first_name")
    last_name = data.get("last_name")
    birthday = data.get("birthday")
    return cancel_appointment(first_name, last_name, birthday)

# 🛠️ Logging Setup
logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S", handlers=[logging.StreamHandler()])

# Zeitzone auf Berlin setzen
os.environ["TZ"] = "Europe/Berlin"

if __name__ == "__main__":
    app.run(debug=True)
