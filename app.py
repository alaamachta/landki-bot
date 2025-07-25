# app.py
from flask import Flask, request, jsonify
import logging
import os
from datetime import datetime

timezone = os.getenv("TIMEZONE", "Europe/Berlin")  # Optional: für Logging

app = Flask(__name__)

# --------------------------------------------------
# Logging konfigurieren
# --------------------------------------------------
logging.basicConfig(
    level=logging.DEBUG,
    format='[%(asctime)s] %(levelname)s in %(module)s: %(message)s',
)
logger = logging.getLogger(__name__)

logger.info("🚀 LandKI Bot gestartet")

# --------------------------------------------------
# Test-Endpoints
# --------------------------------------------------

@app.route("/")
def home():
    logger.info("Home-Route aufgerufen")
    return "✅ LandKI Bot läuft!"

@app.route("/calendar")
def calendar():
    logger.info("Kalender-Route aufgerufen")
    return "📅 Kalenderroute erreichbar."

@app.route("/book-test")
def book_test():
    logger.info("Buchungs-Test-Route aufgerufen")
    return "📘 Buchungsroute erreichbar."

# --------------------------------------------------
# Start App (nicht bei Azure notwendig)
# --------------------------------------------------
if __name__ == "__main__":
    app.run(debug=True)
