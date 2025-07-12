from flask import Flask

app = Flask(__name__)

@app.route("/")
def home():
    return "✅ LandKI Bot läuft erfolgreich!"

# Hinweis:
# KEIN `if __name__ == '__main__':` Block notwendig!
# Azure verwendet Gunicorn (über startup command)
