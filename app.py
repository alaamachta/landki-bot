# ================================
# LandKI Terminassistent – Vollständige app.py mit Slot-ID Terminwahl
# ================================

import os
import logging
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, session
from flask_cors import CORS
import openai
import pyodbc
import pytz
import smtplib
from email.mime.text import MIMEText
from opencensus.ext.azure.log_exporter import AzureLogHandler
from opencensus.ext.azure.trace_exporter import AzureExporter
from opencensus.trace.tracer import Tracer
from opencensus.trace.samplers import ProbabilitySampler

# ================================
# Logging mit deutscher Zeitzone + Application Insights
# ================================

class TZFormatter(logging.Formatter):
    def converter(self, timestamp):
        dt = datetime.fromtimestamp(timestamp, pytz.timezone('Europe/Berlin'))
        return dt

    def formatTime(self, record, datefmt=None):
        dt = self.converter(record.created)
        return dt.strftime(datefmt or "%Y-%m-%d %H:%M:%S")

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
handler = AzureLogHandler(connection_string=os.getenv("APPINSIGHTS_LOG_CONN"))
formatter = TZFormatter('%(asctime)s | %(levelname)s | %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

# ================================
# Flask Setup
# ================================

app = Flask(__name__)
CORS(app)

# ================================
# Termin-Slots generieren (mit ID)
# ================================

def get_free_time_slots(duration_minutes=30):
    timezone = pytz.timezone("Europe/Berlin")
    now = datetime.now(timezone)
    slots = []
    slot_id = 0
    for day in range(3):
        date = now + timedelta(days=day)
        if date.weekday() >= 5:
            continue
        start = date.replace(hour=9, minute=0, second=0, microsecond=0)
        end = date.replace(hour=17, minute=0, second=0, microsecond=0)
        while start + timedelta(minutes=duration_minutes) <= end:
            slots.append({
                "id": f"slot_{slot_id}",
                "start": start.strftime("%d.%m. – %H:%M"),
                "end": (start + timedelta(minutes=duration_minutes)).strftime("%H:%M")
            })
            start += timedelta(minutes=15)
            slot_id += 1
    return slots

# ================================
# Routen
# ================================

@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json()
    user_input = data.get("message", "")

    # Slot-Erkennung aus Button (z. B. slot_3)
    if user_input.startswith("slot_"):
        try:
            slot_index = int(user_input.split("_")[1])
            slots = get_free_time_slots()
            if 0 <= slot_index < len(slots):
                selected = slots[slot_index]
                logger.info(f"✅ Slot gewählt: {selected['start']} – {selected['end']}")
                return jsonify({"response": f"Termin gebucht: {selected['start']} – {selected['end']}", "end": True})
        except:
            logger.warning("❌ Ungültige Slot-ID empfangen")
            return jsonify({"response": "Ungültiger Termin-Link."})

    # Normaler Start-Dialog
    slots = get_free_time_slots()
    buttons = [{"label": f"{s['start']} – {s['end']}", "value": s['id']} for s in slots[:3]]
    logger.info("🤖 Terminvorschläge gesendet")
    return jsonify({
        "response": "Bitte wähle einen Termin durch Klick auf einen Button.",
        "buttons": buttons
    })

# ================================
# Start
# ================================

if __name__ == "__main__":
    app.run(debug=True)
