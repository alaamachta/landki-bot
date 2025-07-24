# =============================================================
# LandKI Bot - Terminbuchung mit SQL, Outlook & E-Mail Versand
# =============================================================

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
from openai import AzureOpenAI
from msal import ConfidentialClientApplication

# =============================================================
# Logging mit deutscher Zeitzone + Application Insights
# =============================================================
class TZFormatter(logging.Formatter):
    def converter(self, timestamp):
        tz = pytz.timezone("Europe/Berlin")
        return datetime.fromtimestamp(timestamp, tz)

    def formatTime(self, record, datefmt=None):
        dt = self.converter(record.created)
        if datefmt:
            return dt.strftime(datefmt)
        return dt.isoformat()

logger = logging.getLogger()
log_level = os.environ.get("WEBSITE_LOGGING_LEVEL", "INFO")
logger.setLevel(log_level)
handler = logging.StreamHandler()
formatter = TZFormatter("[%(asctime)s] [%(levelname)s] %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)

# =============================================================
# Flask App Setup
# =============================================================
app = Flask(__name__)
CORS(app)
app.secret_key = os.getenv("SECRET_KEY", "default")

# =============================================================
# Azure OpenAI Setup
# =============================================================
openai.api_key = os.environ["AZURE_OPENAI_API_KEY"]
openai.api_type = "azure"
openai.api_base = os.environ["AZURE_OPENAI_ENDPOINT"]
openai.api_version = os.environ["OPENAI_API_VERSION"]
model = os.environ["AZURE_OPENAI_DEPLOYMENT"]

# =============================================================
# Azure SQL Setup
# =============================================================
sql_conn_str = os.environ["AZURE_SQL_CONNECTION_STRING"]

def save_to_sql(data):
    try:
        conn = pyodbc.connect(sql_conn_str)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS appointments (
                id INT IDENTITY(1,1) PRIMARY KEY,
                name NVARCHAR(255),
                birthday NVARCHAR(50),
                phone NVARCHAR(50),
                email NVARCHAR(255),
                symptom NVARCHAR(255),
                note NVARCHAR(500),
                slot_start NVARCHAR(50),
                slot_end NVARCHAR(50),
                created_at DATETIME DEFAULT GETDATE()
            )
        """)
        cursor.execute("""
            INSERT INTO appointments (name, birthday, phone, email, symptom, note, slot_start, slot_end)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data.get("name"), data.get("birthday"), data.get("phone"), data.get("email"),
            data.get("symptom"), data.get("note"), data.get("start"), data.get("end")
        ))
        conn.commit()
        conn.close()
        logger.info("✔ Daten erfolgreich in Azure SQL gespeichert")
    except Exception as e:
        logger.error(f"❌ SQL-Fehler: {e}")

# =============================================================
# E-Mail-Versand (SMTP mit OAuth2 oder einfacher Login)
# =============================================================
SMTP_SERVER = "smtp.office365.com"
SMTP_PORT = 587
EMAIL_SENDER = os.environ.get("EMAIL_SENDER")

# Nur bei einfachem Login verwenden:
# EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")

# Optional: OAuth2 vorbereiten mit MSAL
CLIENT_ID = os.environ.get("MS_CLIENT_ID")
CLIENT_SECRET = os.environ.get("MS_CLIENT_SECRET")
TENANT_ID = os.environ.get("MS_TENANT_ID")
REDIRECT_URI = os.environ.get("MS_REDIRECT_URI")

MS_SCOPE = ["https://outlook.office365.com/.default"]

def send_email(recipient, subject, body):
    try:
        msg = MIMEText(body, "plain")
        msg["Subject"] = subject
        msg["From"] = EMAIL_SENDER
        msg["To"] = recipient

        app_msal = ConfidentialClientApplication(CLIENT_ID, authority=f"https://login.microsoftonline.com/{TENANT_ID}", client_credential=CLIENT_SECRET)
        token = app_msal.acquire_token_for_client(scopes=MS_SCOPE)
        access_token = token["access_token"]

        import smtplib, base64, ssl
        smtp = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        smtp.starttls(context=ssl.create_default_context())
        smtp.ehlo()
        auth_string = f"user={EMAIL_SENDER}\x01auth=Bearer {access_token}\x01\x01"
        smtp.docmd("AUTH", "XOAUTH2 " + base64.b64encode(auth_string.encode()).decode())
        smtp.sendmail(EMAIL_SENDER, recipient, msg.as_string())
        smtp.quit()
        logger.info("📧 E-Mail erfolgreich gesendet")
    except Exception as e:
        logger.error(f"❌ E-Mail Fehler: {e}")

# =============================================================
# Weitere Routen & GPT-Logik folgen im nächsten Schritt…
# =============================================================

@app.route("/")
def index():
    return "LandKI Terminassistent aktiv."

# app.run() entfällt – Azure Web App übernimmt den Start
