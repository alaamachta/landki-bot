# ==========================================
# Minimaler Flask-Test zur Fehlersuche
# ==========================================
# Ziel: Sicherstellen, dass der Bot/Container grundsätzlich startet
# ohne SQL, Outlook, E-Mail, GPT oder andere Bibliotheken

import logging
from flask import Flask

# Einfache Konfiguration des Loggings
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] : %(message)s"
)

app = Flask(__name__)

@app.route("/")
def root():
    logging.debug("Bot-Start-Route wurde aufgerufen")
    return "OK – Minimalversion aktiv"

if __name__ == "__main__":
    app.run(debug=True)

# ==========================================
# Deployment-Hinweis:
# Nach Pushen an GitHub wird der Container neu gebaut
# Wenn diese Version funktioniert, gehen wir Schritt für Schritt weiter
# ==========================================
