# app.py – GPT-gestützter LandKI-Terminassistent mit Outlook + SQL + DSGVO-konformer E-Mail

from flask import Flask, request, jsonify, session
import openai
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

# === Flask Setup ===
app = Flask(__name__)
CORS(app)

# === Logging ===
LOG_LEVEL = os.environ.get("WEBSITE_LOGGING_LEVEL", "DEBUG")
logging.basicConfig(
    level=LOG_LEVEL,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler()]
)

# === Konfiguration ===
TZ = pytz.timezone("Europe/Berlin")
SQL_SERVER = 'landki-sql-server.database.windows.net'
SQL_DB = 'landki-db'
SQL_USER = 'landki.sql.server'
SQL_PASSWORD = os.environ.get('SQL_PASSWORD')
SMTP_SENDER = "AlaaMashta@LandKI.onmicrosoft.com"
SMTP_RECIPIENT = "info@landki.com"

# === GPT-Chat Endpoint ===
@app.route("/chat", methods=["POST"])
def chat():
    try:
        user_input = request.get_json()["message"]

        system_prompt = """
Du bist ein professioneller, freundlicher Terminassistent im Namen von LandKI.
Du hilfst Nutzern dabei, Termine zu buchen, Daten korrekt zu erfassen und eine Bestätigung zu verschicken.
Sprich klar, hilfsbereit und direkt. Gib keine medizinischen Empfehlungen. Du bist kein Arzt – du bist ein digitaler Assistent.

Sammle folgende Daten Schritt für Schritt im Gespräch (du darfst mehrere Felder in einer Frage kombinieren, wenn sinnvoll):
1. Vorname (`first_name`)
2. Nachname (`last_name`)
3. Geburtstag im Format JJJJ-MM-TT (`birthday`) → zur eindeutigen Identifikation
4. Telefonnummer (optional, `phone`)
5. Adresse (optional, `address`)
6. Gewünschte Uhrzeit oder Zeitraum für Termin → verwende 15-Minuten-Takt zwischen 09:00 und 17:00 Uhr (`selected_time`)
7. E-Mail-Adresse des Patienten (`email`)
8. Optionale Nachricht (`user_message`), z. B.:
   – „Ich komme mit meinem Sohn“
   – „Ich hätte gerne ein Beratungsgespräch“
   – „Bitte bestätigen Sie den Termin per E-Mail“

Sage dazu:
„Möchten Sie uns noch etwas mitteilen?“ oder
„Gibt es einen Grund für den Termin, den wir berücksichtigen sollten?“

Wenn der Nutzer keine Nachricht mitteilen möchte, lasse `user_message` leer.

Sobald alle Pflichtfelder vorhanden sind, übergib die Daten gesammelt zur Buchung und gib eine Vorschau:
„Ich habe alle Angaben erhalten. Ich buche den Termin am 28.07. um 10:00 Uhr für Alaa Mashta. Sie erhalten in Kürze eine Bestätigung per E-Mail.“

Die Daten werden DSGVO-konform verarbeitet, im Outlook-Kalender eingetragen, in einer Azure-Datenbank gespeichert und eine automatische E-Mail wird an beide Seiten gesendet.

Sprich immer in höflichem, einfachem Deutsch.
Falls etwas unklar ist, frage nach.
Wenn ein Feld wie Geburtstag im falschen Format kommt, gib ein Beispiel (JJJJ-MM-TT).
Wenn kein Termin genannt wurde, frage nach einem freien Zeitraum.
        """

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input}
        ]

        response = openai.ChatCompletion.create(
            api_version="2024-10-21",
            base_url=os.environ["AZURE_OPENAI_ENDPOINT"],
            api_key=os.environ["AZURE_OPENAI_KEY"],
            engine="gpt-4o",
            messages=messages,
            temperature=0.3
        )

        answer = response["choices"][0]["message"]["content"]
        return jsonify({"response": answer})

    except Exception as e:
        logging.exception("Fehler im /chat-Endpunkt")
        return jsonify({"error": str(e)}), 500

# === Terminbuchung (/book) bleibt unverändert ===
@app.route("/book", methods=["POST"])
def book():
    data = request.get_json()
    access_token = session.get("access_token")
    if not access_token:
        return jsonify({"error": "Nicht authentifiziert."}), 401

    try:
        # === Zeiten umwandeln ===
        start_time_utc = datetime.fromisoformat(data['selected_time'])
        start_local = start_time_utc.astimezone(TZ)
        end_local = start_local + timedelta(minutes=30)

        logging.info(f"Starte Terminbuchung für {data['first_name']} {data['last_name']}")

        # === Outlook-Kalendereintrag ===
        outlook_body = f"Neuer Termin mit {data['first_name']} {data['last_name']} ({data['birthday']})<br>Adresse: {data.get('address')}"
        if data.get('user_message'):
            outlook_body += f"<br><br><strong>Nachricht:</strong><br>{data['user_message']}"

        event = {
            "subject": f"Termin: {data['first_name']} {data['last_name']}",
            "start": {"dateTime": start_local.isoformat(), "timeZone": "Europe/Berlin"},
            "end": {"dateTime": end_local.isoformat(), "timeZone": "Europe/Berlin"},
            "body": {"contentType": "HTML", "content": outlook_body},
            "location": {"displayName": "Praxis LandKI"},
            "attendees": []
        }
        graph_resp = requests.post(
            'https://graph.microsoft.com/v1.0/me/events',
            headers={'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json'},
            json=event
        )
        if graph_resp.status_code != 201:
            logging.error(f"Outlook Fehler: {graph_resp.text}")
            return jsonify({"error": "Fehler beim Kalender-Eintrag."}), 500
        logging.info("Outlook-Termin eingetragen")

        # === SQL INSERT ===
        conn = pyodbc.connect(
            f'DRIVER={{ODBC Driver 18 for SQL Server}};SERVER={SQL_SERVER};DATABASE={SQL_DB};'
            f'UID={SQL_USER};PWD={SQL_PASSWORD};Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;')
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

        # === DSGVO-konforme E-Mails ===
        subject = "Ihre Terminbestätigung bei LandKI"
        html = f"""
        <p>Sehr geehrte*r {data['first_name']} {data['last_name']},</p>
        <p>Ihr Termin ist gebucht:</p>
        <ul>
            <li><strong>Datum:</strong> {start_local.strftime('%d.%m.%Y')}</li>
            <li><strong>Uhrzeit:</strong> {start_local.strftime('%H:%M')} Uhr</li>
        </ul>
        {f'<p><strong>Ihre Nachricht:</strong><br>{data["user_message"]}</p>' if data.get('user_message') else ''}
        <p>Dies ist eine automatische Terminbestätigung von LandKI.<br>Ihre Daten wurden gemäß DSGVO verarbeitet.</p>
        <p>Mit freundlichen Grüßen<br>Ihr LandKI-Team</p>
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
