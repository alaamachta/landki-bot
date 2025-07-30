from flask import Flask
import logging
import sys

# 🛠️ Logging-Setup
logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logging.info("🚀 app.py gestartet")

# 🌐 Flask-App
app = Flask(__name__)

# ✅ Test-Route
@app.route("/ping")
def ping():
    logging.info("📶 /ping wurde aufgerufen")
    return "pong", 200

# 🔁 Lokaler Start (wird in Azure ignoriert, ist aber gut für lokalen Test)
if __name__ == "__main__":
    logging.info("👀 Starte Flask lokal")
    app.run(debug=True, host="0.0.0.0", port=8000)
