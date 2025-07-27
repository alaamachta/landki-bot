# app.py – LandKI-Terminassistent mit Outlook + SQL + E-Mail-Versand – Version v1.0004

from flask import Flask, request, jsonify, session
from openai import AzureOpenAI  # Azure SDK ab v1.0+
import os
import logging
from flask_cors import CORS
from datetime import datetime, timedelta
import pytz
import pyodbc
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import requests

# === Flask App Setup ===
app = Flask(__name__)
CORS(app)

# === Logging Setup ===
LOG_LEVEL = os.environ.get("WEBSITE_LOGGING_LEVEL", "DEBUG")
logging.basicConfig(
    level=LOG_LEVEL,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler()]
)

# === Konfiguration ===
TZ = pytz.timezone("Europe/Berlin")
SQL_SERVER = os.environ.get("SQL_SERVER")
SQL_DB = os.environ.get("SQL_DATABASE")
SQL_USER = os.environ.get("SQL_USERNAME")
SQL_PASSWORD = os.environ.get("SQL_PASSWORD")
SMTP_SENDER = os.environ.get("EMAIL_SENDER")
SMTP_RECIPIENT = "info@landki.com"

# === GPT-Chat-Endpunkt ===
@app.route("/chat", methods=["POST"])
def chat():
    try:
        user_input = request.get_json()["message"]

        system_prompt = """
Du bist ein professioneller, freundlicher Terminassistent im Namen einer Firma.
Du hilfst Kunden dabei, Termine zu buchen, Daten korrekt zu erfassen und eine Bestätigung zu verschicken.
Sprich klar, hilfsbereit und direkt. Gib keine medizinischen Empfehlungen. Du bist kein Arzt – du bist ein digitaler Assistent.

Sammle folgende Daten Schritt für Schritt (du darfst mehrere Felder in einer Frage kombinieren):
1. Vorname (`first_name`)
2. Nachname (`last_name`)
3. Geburtstag im Format JJJJ-MM-TT (`birthday`)
4. Telefonnummer (optional, `phone`)
5. Adresse (optional, `address`)
6. Terminzeit im 15-Minuten-Takt zwischen 09:00–17:00 Uhr (`selected_time`)
7. E-Mail-Adresse (`email`)
8. Optionale Nachricht (`user_message`)

Frage: „Möchten Sie uns noch etwas mitteilen?“ oder „Gibt es einen Grund für den Termin?“
Wenn keine Nachricht: `user_message` leer lassen.

Sobald alle Pflichtfelder vorhanden sind, übergib die Daten gesammelt zur Buchung und sage:
„Ich habe alle Angaben erhalten. Ich buche den Termin am 28.07. um 10:00 Uhr für Max Mustermann. Sie erhalten in Kürze eine Bestätigung per E-Mail.“

Sprich in höflichem, einfachem Deutsch. Falls etwas unklar ist, frage nach. Gib Format-Beispiel für Geburtsdatum.
        """

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input}
        ]

        client = AzureOpenAI(
            api_key=os.environ["AZURE_OPENAI_KEY"],
            api_version=os.environ.get("OPENAI_API_VERSION", "2024-10-21"),
            azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"]
        )

        response = client.chat.completions.create(
            model=os.environ["AZURE_OPENAI_DEPLOYMENT"],
            messages=messages,
            temperature=0.3  # empfohlen für kurze, präzise Antworten
        )

        return jsonify({"response": response.choices[0].message.content})

    except Exception as e:
        logging.exception("Fehler im /chat-Endpunkt")
        return jsonify({"error": str(e)}), 500


# === Terminbuchung: Outlook + SQL + E-Mail ===
@app.route("/book", methods=["POST"])
def book():
    data = request.get_json()
    access_token = session.get("access_token")
    if not access_token:
        return jsonify({"error": "Nicht authentifiziert."}), 401

    try:
        start_time_utc = datetime.fromisoformat(data['selected_time'])
        start_local = start_time_utc.astimezone(TZ)
        end_local = start_local + timedelta(minutes=30)

        logging.info(f"Starte Terminbuchung für {data['first_name']} {data['last_name']}")

        # === Outlook-Termin ===
        outlook_body = f"Neuer Termin mit {data['first_name']} {data['last_name']}<br>Geburtsdatum: {data['birthday']}<br>Adresse: {data.get('address')}"
        if data.get('user_message'):
            outlook_body += f"<br><br><strong>Nachricht:</strong><br>{data['user_message']}"

        event = {
            "subject": f"Termin: {data['first_name']} {data['last_name']}",
            "start": {"dateTime": start_local.isoformat(), "timeZone": "Europe/Berlin"},
            "end": {"dateTime": end_local.isoformat(), "timeZone": "Europe/Berlin"},
            "body": {"contentType": "HTML", "content": outlook_body},
            "location": {"displayName": "LandKI Kalender"},
            "attendees": []
        }

        graph_resp = requests.post(
            'https://graph.microsoft.com/v1.0/me/events',
            headers={
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json'
            },
            json=event
        )
        if graph_resp.status_code != 201:
            logging.error(f"Outlook Fehler: {graph_resp.text}")
            return jsonify({"error": "Fehler beim Kalender-Eintrag."}), 500
        logging.info("Outlook-Termin eingetragen")

        # === SQL speichern ===
        conn = pyodbc.connect(
            f"DRIVER={{ODBC Driver 18 for SQL Server}};SERVER={SQL_SERVER};DATABASE={SQL_DB};"
            f"UID={SQL_USER};PWD={SQL_PASSWORD};Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;")
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO dbo.appointments (
                first_name, last_name, birthdate, phone, email, address,
                appointment_start, appointment_end, created_at,
                company_code, bot_origin, service_type, note_internal, user_message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, SYSDATETIMEOFFSET(), ?, ?, ?, ?, ?)
        """, (
            data['first_name'],
            data['last_name'],
            data['birthday'],
            data.get('phone'),
            data['email'],
            data.get('address'),
            start_local,
            end_local,
            "LANDKI", "GPT-ASSIST", "Standard", "Termin gebucht via Bot",
            data.get('user_message')
        ))
        conn.commit()
        cur.close()
        conn.close()
        logging.info("SQL-Termin gespeichert")

        # === E-Mail-Bestätigung ===
        subject = "Ihre Terminbestätigung"
        html = f"""
        <p>Sehr geehrte*r {data['first_name']} {data['last_name']},</p>
        <p>Ihr Termin ist gebucht:</p>
        <ul>
            <li><strong>Datum:</strong> {start_local.strftime('%d.%m.%Y')}</li>
            <li><strong>Uhrzeit:</strong> {start_local.strftime('%H:%M')} Uhr</li>
        </ul>
        {f'<p><strong>Ihre Nachricht:</strong><br>{data["user_message"]}</p>' if data.get('user_message') else ''}
        <p>Dies ist eine automatische Terminbestätigung.<br>Ihre Daten wurden gemäß DSGVO verarbeitet.</p>
        <p>Mit freundlichen Grüßen<br>Ihr Team</p>
        """

        for rcp in [data['email'], SMTP_RECIPIENT]:
            msg = MIMEMultipart()
            msg['From'] = SMTP_SENDER
            msg['To'] = rcp
            msg['Subject'] = subject
            msg.attach(MIMEText(html, 'html'))
            with smtplib.SMTP('smtp.office365.com', 587) as s:
                s.starttls()
                s.login(SMTP_SENDER, os.environ.get("SMTP_PASSWORD"))
                s.sendmail(SMTP_SENDER, rcp, msg.as_string())
        logging.info("Bestätigungs-Mails versendet")

        return jsonify({"status": "success", "message": "Termin gebucht."})

    except Exception as e:
        logging.exception("Fehler bei Terminbuchung")
        return jsonify({"error": str(e)}), 500
