import os
import logging
import json
import uuid
import requests
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, session, redirect, url_for
from flask_cors import CORS
import msal
import pyodbc

# Initialisiere Flask
app = Flask(__name__)
CORS(app)
app.secret_key = os.environ.get("SECRET_KEY", str(uuid.uuid4()))

# Logging-Konfiguration
logging.basicConfig(
    level=os.getenv("WEBSITE_LOGGING_LEVEL", "INFO"),
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# SQL-Konfiguration
SQL_CONNECTION_STRING = os.environ.get("AZURE_SQL_CONNECTION_STRING")

# E-Mail-Konfiguration (später)
EMAIL_SENDER = os.environ.get("EMAIL_SENDER")

@app.route("/book-appointment", methods=["POST"])
def book_appointment():
    try:
        data = request.get_json()
        logger.info("📥 Buchungsanfrage empfangen: %s", data)

        # Schritt 1: Patientendaten auslesen
        first_name = data.get("first_name")
        last_name = data.get("last_name")
        phone = data.get("phone")
        email = data.get("email")
        birthday = data.get("birthday")
        symptoms = data.get("symptoms")
        duration = data.get("duration")
        address = data.get("address")
        appointment_start = data.get("appointment_start")
        appointment_end = data.get("appointment_end")

        # Schritt 2: In SQL speichern
        try:
            conn = pyodbc.connect(SQL_CONNECTION_STRING)
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS appointments (
                    id INT IDENTITY(1,1) PRIMARY KEY,
                    first_name NVARCHAR(100),
                    last_name NVARCHAR(100),
                    phone NVARCHAR(50),
                    email NVARCHAR(255),
                    birthday NVARCHAR(50),
                    symptoms NVARCHAR(MAX),
                    duration NVARCHAR(50),
                    address NVARCHAR(255),
                    appointment_start NVARCHAR(100),
                    appointment_end NVARCHAR(100),
                    created_at DATETIME DEFAULT GETDATE()
                )
            """)
            cursor.execute("""
                INSERT INTO appointments (
                    first_name, last_name, phone, email, birthday,
                    symptoms, duration, address,
                    appointment_start, appointment_end
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                first_name, last_name, phone, email, birthday,
                symptoms, duration, address,
                appointment_start, appointment_end
            ))
            conn.commit()
            conn.close()
            logger.info("✅ Termin in SQL gespeichert")
        except Exception as sql_error:
            logger.error(f"❌ Fehler beim SQL-Speichern: {sql_error}")

        # Schritt 3: Outlook-Termin eintragen
        try:
            authority = f"https://login.microsoftonline.com/{os.environ['MS_TENANT_ID']}"
            app_msal = msal.ConfidentialClientApplication(
                client_id=os.environ['MS_CLIENT_ID'],
                client_credential=os.environ['MS_CLIENT_SECRET'],
                authority=authority
            )
            scopes = ["https://graph.microsoft.com/.default"]
            result = app_msal.acquire_token_for_client(scopes=scopes)

            if "access_token" in result:
                access_token = result["access_token"]
                event_payload = {
                    "subject": f"Termin: {first_name} {last_name}",
                    "body": {
                        "contentType": "Text",
                        "content": f"Symptome: {symptoms}\nDauer: {duration}\nTelefon: {phone}\nAdresse: {address}"
                    },
                    "start": {
                        "dateTime": appointment_start,
                        "timeZone": "Europe/Berlin"
                    },
                    "end": {
                        "dateTime": appointment_end,
                        "timeZone": "Europe/Berlin"
                    },
                    "location": {
                        "displayName": "LandKI Praxis"
                    },
                    "attendees": [
                        {
                            "emailAddress": {
                                "address": email,
                                "name": f"{first_name} {last_name}"
                            },
                            "type": "required"
                        }
                    ]
                }
                graph_url = "https://graph.microsoft.com/v1.0/me/events"
                headers = {
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json"
                }
                response = requests.post(graph_url, headers=headers, json=event_payload)

                if response.status_code == 201:
                    logger.info("📆 Outlook-Termin erfolgreich erstellt")
                else:
                    logger.warning(f"⚠️ Outlook-Termin konnte nicht erstellt werden: {response.status_code}, {response.text}")
            else:
                logger.error(f"❌ Kein Access Token: {result.get('error_description')}")
        except Exception as outlook_error:
            logger.error(f"❌ Fehler bei Outlook-Termin: {outlook_error}")

        return jsonify({"status": "success", "message": "Termin gebucht"})

    except Exception as e:
        logger.error(f"❌ Fehler in book_appointment(): {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8000)
