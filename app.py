from flask import Flask, request, jsonify
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
import pyodbc
from landki_utils.outlook_service import delete_event, send_mail
from landki_utils.sql_config import get_sql_connection

app = Flask(__name__)

# Logging konfigurieren
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logger.info("/cancel route ready")

@app.route("/cancel", methods=["POST"])
def cancel_appointment():
    try:
        data = request.get_json()
        logger.info(f"Empfangene Stornierungsdaten: {data}")

        first_name = data.get("first_name")
        last_name = data.get("last_name")
        birthday = data.get("birthday")

        # Verbindung zur SQL-Datenbank herstellen
        conn = get_sql_connection()
        cursor = conn.cursor()

        # Termin anhand Vorname, Nachname, Geburtstag suchen
        select_query = """
        SELECT id, email_patient, email_praxis, calendar_event_id FROM appointments
        WHERE first_name = ? AND last_name = ? AND birthday = ?
        """
        cursor.execute(select_query, (first_name, last_name, birthday))
        row = cursor.fetchone()

        if not row:
            logger.warning("Kein passender Termin gefunden")
            return jsonify({"success": False, "message": "Kein passender Termin gefunden."}), 404

        appointment_id, email_patient, email_praxis, calendar_event_id = row
        logger.info(f"Gefundener Termin ID {appointment_id} mit Event-ID: {calendar_event_id}")

        # Kalender-Event löschen
        if calendar_event_id:
            delete_event(calendar_event_id)
            logger.info(f"Kalender-Event {calendar_event_id} gelöscht")

        # Termin aus SQL löschen
        delete_query = "DELETE FROM appointments WHERE id = ?"
        cursor.execute(delete_query, (appointment_id,))
        conn.commit()
        logger.info(f"Termin ID {appointment_id} aus SQL gelöscht")

        # E-Mail an Patient und Praxis
        subject = "Termin wurde erfolgreich storniert"
        content = f"Der Termin von {first_name} {last_name} wurde storniert."

        send_mail(email_patient, subject, content)
        send_mail(email_praxis, subject, content)
        logger.info("Stornierungsbestätigungen per E-Mail gesendet")

        return jsonify({"success": True, "message": "Termin erfolgreich storniert."})

    except Exception as e:
        logger.exception("Fehler beim Stornieren des Termins")
        return jsonify({"success": False, "message": str(e)}), 500
