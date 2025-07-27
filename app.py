# app.py – LandKI-Terminassistent v1.0009 mit smarter Datumserkennung, optionalem Geburtstag und Grundabfrage

from flask import Flask, request, jsonify, session
from openai import AzureOpenAI
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
import dateparser  # für natürlichsprachliche Zeitangaben

# === Flask Setup ===
app = Flask(__name__)
CORS(app)

# === Logging Setup ===
logging.basicConfig(
    level=os.environ.get("WEBSITE_LOGGING_LEVEL", "INFO"),
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

# === Steuerung: Geburtstagsfeld aktiv? ===
BIRTHDAY_REQUIRED = False  # Für Praxen True, sonst False

# === GPT-Chat-Endpunkt ===
@app.route("/chat", methods=["POST"])
def chat():
    try:
        user_input = request.get_json()["message"]

        system_prompt = f"""
Du bist ein professioneller Terminassistent einer Firma (kein Arzt). Du hilfst Kunden beim Buchen eines Termins.

Sprich freundlich, präzise, direkt und in **einfach verständlichem Deutsch**.

Frage nach folgenden Daten – du darfst sie kombinieren, aber NICHT überspringen:
1. Vorname (`first_name`)
2. Nachname (`last_name`)
{'3. Geburtstag im Format JJJJ-MM-TT (`birthday`)\n' if BIRTHDAY_REQUIRED else ''}3. E-Mail-Adresse (`email`)
4. Wunschtermin (`selected_time`) – erkenne auch natürliche Sprache wie "morgen", "am Freitag um 10 Uhr", "übermorgen 15 Uhr"
5. Grund / Nachricht (`user_message`) – Frage IMMER danach, z. B.: „Möchten Sie uns noch etwas mitteilen?“

Wunschtermin: Falls der Kunde ein Datum wie „Montag 15 Uhr“ nennt, versuche es zu erkennen (Beispiel: 2025-07-29T15:00). 
Wenn der Termin nicht verfügbar ist oder fehlt, schlage andere Zeiten vor: 
„Der gewünschte Termin ist leider belegt. Ich kann folgende Alternativen anbieten: 29.07 um 16:00 oder 30.07 vormittags. Wählen Sie bitte einen davon.“

Sobald alle Daten vorhanden sind, fasse sie in einer kurzen Liste zusammen und leite die Buchung automatisch ein.
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
            temperature=0.3
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

        outlook_body = f"Neuer Termin mit {data['first_name']} {data['last_name']}<br>E-Mail: {data['email']}"
        if BIRTHDAY_REQUIRED:
            outlook_body += f"<br>Geburtstag: {data['birthday']}"
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
            data.get('birthday') if BIRTHDAY_REQUIRED else None,
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
