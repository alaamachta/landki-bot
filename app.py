import os
from flask import Flask, request, jsonify, session
from flask_cors import CORS
from datetime import datetime, timedelta
import openai
import pyodbc
import pytz
import smtplib
from email.mime.text import MIMEText
import logging

# =============================
# 🔍 Logging mit deutscher Zeitzone (für Azure Log Stream)
# =============================
class TZFormatter(logging.Formatter):
    def converter(self, timestamp):
        berlin = pytz.timezone("Europe/Berlin")
        return datetime.fromtimestamp(timestamp, tz=berlin)

    def formatTime(self, record, datefmt=None):
        dt = self.converter(record.created)
        return dt.strftime(datefmt or "%Y-%m-%d %H:%M:%S")

formatter = TZFormatter("[%(asctime)s] [%(levelname)s] %(message)s")
handler = logging.StreamHandler()
handler.setFormatter(formatter)

logger = logging.getLogger()
logger.setLevel(logging.DEBUG if os.environ.get("WEBSITE_LOGGING_LEVEL") == "DEBUG" else logging.INFO)
logger.addHandler(handler)
logger.info("✅ Logging mit deutscher Zeitzone aktiviert")

# =============================
# 🌐 Flask-App Grundkonfiguration
# =============================
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "fallback-secret")
CORS(app)

# =============================
# 🔑 Azure OpenAI-Konfiguration
# =============================
openai.api_base = os.getenv("AZURE_OPENAI_ENDPOINT")
openai.api_key = os.getenv("AZURE_OPENAI_API_KEY")
openai.api_type = "azure"
openai.api_version = os.getenv("OPENAI_API_VERSION")
deployment_id = os.getenv("AZURE_OPENAI_DEPLOYMENT")

# =============================
# 🗄️ Azure SQL-Verbindung
# =============================
SQL_CONNECTION_STRING = os.getenv("AZURE_SQL_CONNECTION_STRING")

# =============================
# 📧 Microsoft 365 SMTP-Konfiguration
# =============================
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
MS_CLIENT_ID = os.getenv("MS_CLIENT_ID")
MS_CLIENT_SECRET = os.getenv("MS_CLIENT_SECRET")
MS_TENANT_ID = os.getenv("MS_TENANT_ID")
MS_REDIRECT_URI = os.getenv("MS_REDIRECT_URI")

# =============================
# 📅 Freie Zeitfenster berechnen
# =============================
def get_free_time_slots(duration_minutes=30):
    timezone = pytz.timezone("Europe/Berlin")
    now = datetime.now(timezone)
    slots = []

    for day in range(3):
        date = now + timedelta(days=day)
        if date.weekday() >= 5:
            continue  # Wochenende überspringen
        start = date.replace(hour=9, minute=0, second=0, microsecond=0)
        end = date.replace(hour=17, minute=0, second=0, microsecond=0)

        while start + timedelta(minutes=duration_minutes) <= end:
            slots.append({
                "start": start.strftime("%d.%m. – %H:%M"),
                "end": (start + timedelta(minutes=duration_minutes)).strftime("%H:%M")
            })
            start += timedelta(minutes=15)

    return slots

def parse_time(time_str):
    try:
        return datetime.strptime(time_str.strip(), "%d.%m. – %H:%M")
    except:
        return datetime.now()

def create_outlook_event(draft):
    logger.info("📅 Outlook-Ereignis vorbereiten (Platzhalter)")
    # TODO: Später Microsoft Graph API hinzufügen
    return True  # Platzhalterwert

# =============================
# 💾 Speichern in Azure SQL
# =============================
def save_to_sql(draft):
    try:
        conn = pyodbc.connect(SQL_CONNECTION_STRING)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO appointments (start_time, end_time, name, dob, phone, email, symptom)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            draft['start'], draft['end'], draft['name'], draft['dob'], draft['phone'], draft['email'], draft['symptom']
        ))
        conn.commit()
        cursor.close()
        conn.close()
        logger.info("✅ Termin in SQL gespeichert")
        return True
    except Exception as e:
        logger.error(f"❌ SQL-Fehler: {e}")
        return False

# =============================
# 📤 E-Mail senden via Microsoft 365
# =============================
def send_email(to, subject, body):
    try:
        msg = MIMEText(body, "html")
        msg["Subject"] = subject
        msg["From"] = EMAIL_SENDER
        msg["To"] = to

        with smtplib.SMTP("smtp.office365.com", 587) as server:
            server.starttls()
            server.login(EMAIL_SENDER, os.getenv("EMAIL_PASSWORD", ""))
            server.send_message(msg)

        logger.info(f"✅ E-Mail gesendet an: {to}")
        return True
    except Exception as e:
        logger.error(f"❌ Mail-Fehler: {e}")
        return False

# =============================
# 📌 Termin vollständig buchen
# =============================
def book_appointment(draft):
    logger.info(f"📅 Buche Termin: {draft}")

    outlook_ok = create_outlook_event(draft)
    sql_ok = save_to_sql(draft)
    email_ok = send_email(
        draft['email'],
        "Dein Termin bei LandKI",
        f"""
<b>Terminbestätigung</b><br><br>
🗓 Termin: {draft['start']} – {draft['end']}<br>
👤 Name: {draft['name']}<br>
🎂 Geburtsdatum: {draft['dob']}<br>
📞 Telefon: {draft['phone']}<br>
📧 E-Mail: {draft['email']}<br>
💬 Grund: {draft['symptom']}<br><br>
Vielen Dank! Wir sehen uns bald.
        """
    )
    praxis_ok = send_email(
        EMAIL_SENDER,
        f"Neuer Termin: {draft['name']}",
        f"""
<b>Neuer Patiententermin:</b><br><br>
🗓 Termin: {draft['start']} – {draft['end']}<br>
👤 Name: {draft['name']}<br>
🎂 Geburtsdatum: {draft['dob']}<br>
📞 Telefon: {draft['phone']}<br>
📧 E-Mail: {draft['email']}<br>
💬 Grund: {draft['symptom']}
        """
    )

    return outlook_ok and sql_ok and email_ok and praxis_ok

# =============================
# 🤖 Haupt-Route für Chat
# =============================
@app.route("/chat", methods=["POST"])
def chat():
    user_input = request.json.get("message", "").strip()
    if "appointment_draft" not in session:
        session["appointment_draft"] = {}

    draft = session["appointment_draft"]
    reply = ""

    try:
        if not draft.get("start") and "termin" in user_input.lower():
            slots = get_free_time_slots()
            draft["suggested_slots"] = slots
            reply = "<div class='terminauswahl'><p>Bitte wähle einen Termin:</p><div class='termin-buttons'>" + "".join([
                f"<button onclick='sendPredefined(\"{s['start']} – {s['end']}\")'>{s['start']} – {s['end']}</button>"
                for s in slots[:3]
            ]) + "</div></div>"

        elif not draft.get("start"):
            matched = next((s for s in draft.get("suggested_slots", []) if f"{s['start']} – {s['end']}".lower() == user_input.lower()), None)
            if matched:
                dt_start = parse_time(matched['start'])
                dt_end = dt_start + timedelta(minutes=30)
                draft['start'] = dt_start.isoformat()
                draft['end'] = dt_end.isoformat()
                reply = "Wie ist dein vollständiger Name?"
            else:
                reply = "Bitte wähle einen Termin durch Klick auf einen Button."

        elif draft.get("start") and not draft.get("name"):
            draft["name"] = user_input
            reply = "Wie lautet dein Geburtsdatum? (z. B. 1990-05-15)"

        elif draft.get("name") and not draft.get("dob"):
            draft["dob"] = user_input
            reply = "Wie lautet deine Telefonnummer?"

        elif draft.get("dob") and not draft.get("phone"):
            draft["phone"] = user_input
            reply = "Wie lautet deine E-Mail-Adresse?"

        elif draft.get("phone") and not draft.get("email"):
            draft["email"] = user_input
            reply = "Was ist der Grund deines Besuchs?"

        elif draft.get("email") and not draft.get("symptom"):
            draft["symptom"] = user_input
            reply = f"""
<b>Bitte bestätige deinen Termin:</b><br><br>
🗓 <b>Termin:</b> {draft['start']} – {draft['end']}<br>
👤 <b>Name:</b> {draft['name']}<br>
🎂 <b>Geburtsdatum:</b> {draft['dob']}<br>
📞 <b>Telefon:</b> {draft['phone']}<br>
📧 <b>E-Mail:</b> {draft['email']}<br>
💬 <b>Grund:</b> {draft['symptom']}<br><br>
Mit deiner Bestätigung stimmst du der DSGVO-konformen Verarbeitung zu.<br><br>
<button onclick='sendPredefined("Ja, Termin buchen")'>✅ Ja, Termin buchen</button>
<button onclick='sendPredefined("Abbrechen")'>❌ Abbrechen</button>
            """

        elif "ja" in user_input.lower() and "buchen" in user_input.lower():
            success = book_appointment(draft)
            reply = "✅ Termin gebucht. Eine Bestätigung wurde gesendet." if success else "❌ Fehler beim Buchen."
            session.pop("appointment_draft", None)

        elif "abbrechen" in user_input.lower():
            session.pop("appointment_draft", None)
            reply = "❌ Terminbuchung wurde abgebrochen."

        else:
            reply = "Ich bin dein Terminassistent. Möchtest du einen Termin buchen?"
    except Exception as e:
        logger.error(f"❌ Interner Fehler im Chatablauf: {e}")
        reply = "⚠️ Es ist ein Fehler aufgetreten. Bitte versuche es erneut."

    return jsonify({"reply": reply})

# =============================
# 🔧 Startpunkt für lokale Tests
# =============================
if __name__ == "__main__":
    app.run(debug=True)
