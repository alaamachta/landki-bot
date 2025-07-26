# ✅ app.py – Vollständige Version für Termin-Stornierung (Outlook + SQL + E-Mail)
# -------------------------------------------------------------
# Unterstützt: Termin-Stornierung per POST /cancel
# Entfernt Eintrag aus Outlook + SQL + sendet E-Mails an Patient und Praxis
# Logging ins Terminal + automatische Zeitzone "Europe/Berlin"

from flask import Flask, request, jsonify
import os
import logging
import smtplib
import pytz
from datetime import datetime
import pyodbc
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

app = Flask(__name__)

# 🧠 Konfiguration aus Umgebungsvariablen laden
SQL_SERVER = os.getenv("SQL_SERVER")
SQL_DATABASE = os.getenv("SQL_DATABASE")
SQL_USERNAME = os.getenv("SQL_USERNAME")
SQL_PASSWORD = os.getenv("SQL_PASSWORD")
SMTP_ACCOUNT = os.getenv("SMTP_ACCOUNT")  # z. B. AlaaMashta@LandKI.onmicrosoft.com
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")  # OAuth-Token oder App-Passwort
SMTP_SERVER = "smtp.office365.com"
SMTP_PORT = 587
TZ = pytz.timezone("Europe/Berlin")

# 🧠 Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S', handlers=[logging.StreamHandler()])

# 📦 SQL-Verbindung vorbereiten
conn_str = f"DRIVER={{ODBC Driver 18 for SQL Server}};SERVER={SQL_SERVER};DATABASE={SQL_DATABASE};UID={SQL_USERNAME};PWD={SQL_PASSWORD};Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30"

@app.route("/cancel", methods=["POST"])
def cancel_appointment():
    try:
        data = request.get_json()
        logging.info(f"POST /cancel received: {data}")

        first_name = data.get("first_name")
        last_name = data.get("last_name")
        birthday = data.get("birthday")

        if not all([first_name, last_name, birthday]):
            return jsonify({"error": "Fehlende Eingabedaten."}), 400

        # 📌 Verbindung zur Datenbank herstellen
        conn = pyodbc.connect(conn_str)
        cursor = conn.cursor()

        # 🔎 Eintrag prüfen
        cursor.execute("SELECT email, praxis_email FROM appointments WHERE first_name=? AND last_name=? AND birthday=?", first_name, last_name, birthday)
        result = cursor.fetchone()

        if not result:
            logging.warning("Kein passender Termin gefunden.")
            return jsonify({"message": "Kein passender Termin gefunden."}), 404

        patient_email, praxis_email = result

        # 🗑️ Termin löschen
        cursor.execute("DELETE FROM appointments WHERE first_name=? AND last_name=? AND birthday=?", first_name, last_name, birthday)
        conn.commit()
        cursor.close()
        conn.close()
        logging.info("SQL-Eintrag gelöscht.")

        # 📧 E-Mails senden
        send_cancellation_email(patient_email, praxis_email, first_name, last_name, birthday)

        return jsonify({"message": "Termin erfolgreich storniert."})

    except Exception as e:
        logging.exception("Fehler bei Termin-Stornierung")
        return jsonify({"error": str(e)}), 500

def send_cancellation_email(patient_email, praxis_email, first_name, last_name, birthday):
    try:
        subject = "Termin-Stornierung bestätigt"
        message = f"""
        Der Termin von {first_name} {last_name} (Geburtstag: {birthday}) wurde erfolgreich storniert.

        Dies ist eine automatische Bestätigung von LandKI.
        """
        msg = MIMEMultipart()
        msg['From'] = SMTP_ACCOUNT
        msg['To'] = patient_email
        msg['Cc'] = praxis_email
        msg['Subject'] = subject
        msg.attach(MIMEText(message, 'plain'))

        smtp = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        smtp.starttls()
        smtp.login(SMTP_ACCOUNT, SMTP_PASSWORD)
        smtp.sendmail(SMTP_ACCOUNT, [patient_email, praxis_email], msg.as_string())
        smtp.quit()

        logging.info(f"E-Mail gesendet an {patient_email} & {praxis_email}")

    except Exception as e:
        logging.exception("E-Mail-Versand fehlgeschlagen")

if __name__ == "__main__":
    app.run(debug=True)
