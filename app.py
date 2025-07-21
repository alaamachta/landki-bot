
from flask import Flask, request, jsonify
from flask_cors import CORS
import os, requests, datetime
from msal import ConfidentialClientApplication
from dateutil import parser
import pytz
import openai

app = Flask(__name__)
CORS(app)

# Azure + Microsoft Konfiguration
TENANT_ID = os.getenv("MS_TENANT_ID")
CLIENT_ID = os.getenv("MS_CLIENT_ID")
CLIENT_SECRET = os.getenv("MS_CLIENT_SECRET")
EMAIL_SENDER = os.getenv("EMAIL_SENDER")

AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
SCOPES = ["https://graph.microsoft.com/.default"]
GRAPH_API = "https://graph.microsoft.com/v1.0"

# OpenAI (GPT-4o)
openai.api_key = os.getenv("AZURE_OPENAI_API_KEY")
openai.api_base = os.getenv("AZURE_OPENAI_ENDPOINT")
openai.api_type = "azure"
openai.api_version = os.getenv("OPENAI_API_VERSION")
DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")

# Token-Funktion für MS Graph
def get_graph_token():
    app = ConfidentialClientApplication(
        CLIENT_ID, authority=AUTHORITY, client_credential=CLIENT_SECRET
    )
    result = app.acquire_token_silent(SCOPES, account=None)
    if not result:
        result = app.acquire_token_for_client(scopes=SCOPES)
    return result["access_token"]

# Outlook: freie Slots (werktags, 15-min-Takt, max. 2h)
def get_free_time_slots():
    token = get_graph_token()
    tz = "Europe/Berlin"
    now = datetime.datetime.utcnow().replace(tzinfo=pytz.UTC)
    end = now + datetime.timedelta(days=7)

    url = f"{GRAPH_API}/users/{EMAIL_SENDER}/calendarView?startDateTime={now.isoformat()}&endDateTime={end.isoformat()}&$orderby=start/dateTime"
    res = requests.get(url, headers={"Authorization": f"Bearer {token}"})
    busy = [ (parser.parse(e["start"]["dateTime"]), parser.parse(e["end"]["dateTime"])) for e in res.json().get("value", []) ]

    # Zeitraum zwischen 09:00–17:00 Uhr
    slots = []
    current = now.astimezone(pytz.timezone(tz)).replace(hour=9, minute=0, second=0, microsecond=0)
    day_end = current.replace(hour=17)
    while current < end:
        start = current
        endtime = current + datetime.timedelta(minutes=30)
        if start.weekday() < 5 and all(not (start < b[1] and endtime > b[0]) for b in busy):
            slots.append((start.isoformat(), endtime.isoformat()))
        current += datetime.timedelta(minutes=15)
        if current.hour >= 17:
            current = (current + datetime.timedelta(days=1)).replace(hour=9)
    return slots[:3]

@app.route("/chat", methods=["POST"])
def chat():
    user_input = request.json.get("message", "")
    slots = get_free_time_slots()
    system = "Du bist ein Terminassistent. Erstelle aus diesen freien Slots eine HTML-Antwort mit <button onclick='bookSelected(...)'>Buchen</button> pro Termin.
"
    for i, (start, end) in enumerate(slots):
        start_dt = parser.parse(start)
        end_dt = parser.parse(end)
        tag = start_dt.strftime("%d.%m.%Y")
        uhrzeit = f"{start_dt.strftime('%H:%M')} – {end_dt.strftime('%H:%M')}"
        onclick = f"bookSelected('{start}', '{end}')"
        system += f"<li>🕒 {tag} {uhrzeit} <button onclick=\"{onclick}\">Buchen</button></li>\n"

    response = openai.ChatCompletion.create(
        engine=DEPLOYMENT,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_input}
        ],
        temperature=0.3
    )
    answer = response["choices"][0]["message"]["content"]
    return jsonify({"reply_html": f"<ul>{answer}</ul>"})
