# app.py – LandKI Bot mit Termin-Stornierung inkl. SQL-Löschung & E-Mail-Bestätigung

import os
import logging
import pyodbc
import smtplib
from email.mime.text import MIMEText
from flask import Flask, request, jsonify
from datetime import datetime

# === Konfiguration ===
SQL_CONNECTION_STRING = os.getenv("SQL_CONNECTION_STRING")  # z. B. DSN oder direkter String
SMTP_USER = os.getenv("SMTP_USER")  # z. B. AlaaMashta@LandKI.onmicrosoft.com
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")  # falls App-Passwort oder OAuth-Token
SMTP_SERVER = "smtp.office365.com"
SMTP_PORT = 587

# === Flask App ===
app = Flask(__name__)

# === Logging ===
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# === Termin stornieren ===
def cancel_appointment(first_name, last_name, birthday):
    try:
        logging.info(f"🟠 Stornierungsanfrage für {first_name} {last_name}, {birthday}")

        conn = pyodbc.connect(SQL_CONNECTION_STRING)
        cursor = conn.cursor()

        # Patientendaten auslesen (E-Mail aus Tabelle holen)
        select_query = """
        SELECT email, appointment_time FROM appointments
        WHERE first_name = ? AND last_name = ? AND birthday = ?
        """
        cursor.execute(select_query, (first_name, last_name, birthday))
        row = cursor.fetchone()

        if not row:
            logging.warning("⚠️ Kein Eintrag gefunden für Stornierung")
            return f"❌ Kein Termin gefunden für {first_name} {last_name} ({birthday})"

        patient_email, appointment_time = row

        # Termin löschen
        delete_query = """
        DELETE FROM appointments
        WHERE first_name = ? AND last_name = ? AND birthday = ?
        """
        cursor.execute(delete_query, (first_name, last_name, birthday))
        conn.commit()
        conn.close()

        # Bestätigungs-E-Mail an Patient
        subject = "Terminabsage bestätigt"
        body = f"""
Hallo {first_name} {last_name},

Ihr Termin am {appointment_time} wurde erfolgreich storniert.

Mit freundlichen Grüßen
LandKI Terminassistent
"""
        send_email(patient_email, subject, body)

        # Benachrichtigung an Praxis
        praxis_body = f"Termin von {first_name} {last_name} ({birthday}) wurde storniert."
        send_email("praxis@landki.com", subject, praxis_body)

        logging.info("✅ Termin erfolgreich storniert & E-Mails gesendet")
        return f"✅ Termin erfolgreich storniert. Bestätigungen wurden per E-Mail versendet."

    except Exception as e:
        logging.error(f"❌ Fehler bei Termin-Stornierung: {e}")
        return f"❌ Fehler: {str(e)}"

# === E-Mail-Versand ===
def send_email(to, subject, body):
    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = SMTP_USER
        msg["To"] = to

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, to, msg.as_string())
        logging.info(f"📧 E-Mail gesendet an: {to}")

    except Exception as e:
        logging.error(f"❌ Fehler beim E-Mail-Versand an {to}: {e}")

# === Beispiel-Endpunkt zum Testen ===
@app.route("/cancel", methods=["POST"])
def api_cancel():
    data = request.get_json()
    first_name = data.get("first_name")
    last_name = data.get("last_name")
    birthday = data.get("birthday")  # Format: YYYY-MM-DD

    if not all([first_name, last_name, birthday]):
        return jsonify({"error": "first_name, last_name und birthday erforderlich"}), 400

    result = cancel_appointment(first_name, last_name, birthday)
    return jsonify({"reply": result})

# === Haupt-Chat-Endpunkt Dummy ===
@app.route("/chat", methods=["POST"])
def chat():
    return jsonify({"reply": "Noch nicht implementiert"})

# === Start ===
if __name__ == "__main__":
    app.run(debug=True)
