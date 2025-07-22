from flask import Flask, request, jsonify, session
from flask_cors import CORS
import openai
import logging
from datetime import datetime, timedelta
import requests
import pytz
import pyodbc

app = Flask(__name__)
app.secret_key = "supersecret"
CORS(app)

# 🔐 GPT-Config (Azure)
openai.api_base = "https://alaam-mcn1tubi-eastus2.openai.azure.com/"
openai.api_key = "DEIN_AZURE_KEY"
openai.api_type = "azure"
openai.api_version = "2024-05-01-preview"
deployment_id = "gpt-4o"

# 🧠 Systemprompt
system_prompt = """
Du bist ein Terminassistent. Wenn der Nutzer einen Termin buchen möchte, frage nacheinander:
1. Terminwahl (zeige Buttons)
2. Name
3. Geburtsdatum
4. Telefonnummer
5. E-Mail
6. Beschwerden
Dann fasse alles zusammen und frage nach Bestätigung: „Ja, Termin buchen“. Antworte freundlich, klar, menschlich.
"""

def get_free_time_slots(duration_minutes=30):
    timezone = pytz.timezone("Europe/Berlin")
    now = datetime.now(timezone)
    end = now + timedelta(days=2)

    fake_appointments = []  # Simuliere: keine Kollision

    slots = []
    for day in range(3):
        date = now + timedelta(days=day)
        if date.weekday() >= 5:
            continue
        start = date.replace(hour=9, minute=0)
        end_of_day = date.replace(hour=17, minute=0)
        while start + timedelta(minutes=duration_minutes) <= end_of_day:
            conflict = False
            for ev in fake_appointments:
                if start < ev["end"] and start + timedelta(minutes=duration_minutes) > ev["start"]:
                    conflict = True
                    break
            if not conflict:
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

def book_appointment(data):
    print("📅 Buche Termin:", data)  # Nur zur Demo
    # TODO: create_outlook_event(), save_to_sql(), send_email()
    return True

@app.route("/chat", methods=["POST"])
def chat():
    user_input = request.json.get("message")

    if "appointment_draft" not in session:
        session["appointment_draft"] = {}

    draft = session["appointment_draft"]
    reply = ""

    if not draft.get("start") and "termin" in user_input.lower():
        slots = get_free_time_slots()
        draft["suggested_slots"] = slots
        reply = "Bitte wähle einen Termin:<br><br>" + "".join([
            f"<button class='appointment-btn' onclick='sendPredefined(\"{slot['start']} – {slot['end']}\")'>{slot['start']} – {slot['end']}</button> "
            for slot in slots[:3]
        ])

    elif not draft.get("start") and any(x in user_input for x in ["–", ":"]):
        for s in draft.get("suggested_slots", []):
            if s["start"] in user_input:
                dt_start = parse_time(s["start"])
                dt_end = parse_time(s["start"].split("–")[0] + "–" + s["end"])
                draft["start"] = dt_start.isoformat()
                draft["end"] = dt_end.isoformat()
                break
        reply = "Wie ist dein vollständiger Name?"

    elif draft.get("start") and not draft.get("name"):
        draft["name"] = user_input
        reply = "Geburtsdatum bitte (z. B. 1990-01-01):"

    elif draft.get("name") and not draft.get("dob"):
        draft["dob"] = user_input
        reply = "Deine Telefonnummer?"

    elif draft.get("dob") and not draft.get("phone"):
        draft["phone"] = user_input
        reply = "Deine E-Mail-Adresse?"

    elif draft.get("phone") and not draft.get("email"):
        draft["email"] = user_input
        reply = "Kurz: Worum geht es?"

    elif draft.get("email") and not draft.get("symptom"):
        draft["symptom"] = user_input
        reply = f"""
<b>Bitte bestätige die Buchung:</b><br><br>
🗓 <b>Termin:</b> {draft['start']} – {draft['end']}<br>
👤 <b>Name:</b> {draft['name']}<br>
🎂 <b>Geburtsdatum:</b> {draft['dob']}<br>
📞 <b>Telefon:</b> {draft['phone']}<br>
📧 <b>E-Mail:</b> {draft['email']}<br>
💬 <b>Beschwerden:</b> {draft['symptom']}<br><br>
Mit deiner Bestätigung stimmst du der DSGVO-konformen Verarbeitung zu.<br><br>
➡️ Schreibe: <b>Ja, Termin buchen</b> oder <b>Abbrechen</b>
        """

    elif "ja" in user_input.lower() and "buchen" in user_input.lower():
        success = book_appointment(draft)
        if success:
            reply = "✅ Termin erfolgreich gebucht. Du erhältst eine Bestätigung per E-Mail."
        else:
            reply = "❌ Fehler bei der Buchung. Bitte versuch es später erneut."
        session.pop("appointment_draft", None)

    elif "abbrechen" in user_input.lower():
        session.pop("appointment_draft", None)
        reply = "⛔️ Buchung abgebrochen. Sag Bescheid, wenn du es dir anders überlegst."

    else:
        reply = "Ich bin dein Terminassistent. Möchtest du einen Termin buchen?"

    return jsonify({"reply": reply})
