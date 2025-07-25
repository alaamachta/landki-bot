from flask import Flask, request, jsonify
from flask_cors import CORS
import os, pyodbc, requests
from datetime import datetime
from msal import ConfidentialClientApplication

app = Flask(__name__)
CORS(app)

# ENV Variablen
SQL_CONNECTION_STRING = os.getenv("AZURE_SQL_CONNECTION_STRING")
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
CLIENT_ID = os.getenv("MS_CLIENT_ID")
CLIENT_SECRET = os.getenv("MS_CLIENT_SECRET")
TENANT_ID = os.getenv("MS_TENANT_ID")
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
SCOPE = ["https://graph.microsoft.com/.default"]

# Auth-Client
msal_app = ConfidentialClientApplication(CLIENT_ID, client_credential=CLIENT_SECRET, authority=AUTHORITY)

def get_token():
    token = msal_app.acquire_token_silent(SCOPE, account=None)
    if not token:
        token = msal_app.acquire_token_for_client(scopes=SCOPE)
    return token["access_token"]

def send_email(to, subject, html):
    token = get_token()
    requests.post(
        f"https://graph.microsoft.com/v1.0/users/{EMAIL_SENDER}/sendMail",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        },
        json={
            "message": {
                "subject": subject,
                "body": {"contentType": "HTML", "content": html},
                "toRecipients": [{"emailAddress": {"address": to}}]
            }
        }
    )

@app.route("/book", methods=["POST"])
def book():
    d = request.json
    with pyodbc.connect(SQL_CONNECTION_STRING) as conn:
        c = conn.cursor()
        c.execute("INSERT INTO appointment (name, birthdate, phone, email, symptom, notes, start_time, end_time, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                  d["name"], d["birthdate"], d["phone"], d["email"], d["symptom"], d.get("notes", ""), d["start_time"], d["end_time"], datetime.utcnow())
        conn.commit()

    send_email(d["email"], "Terminbestätigung", f"<h3>Hallo {d['name']}</h3><p>Ihr Termin wurde gebucht.</p>")
    send_email(EMAIL_SENDER, "Neue Terminbuchung", f"<b>Neuer Termin für {d['name']}</b>")
    return jsonify({"status": "success"})
