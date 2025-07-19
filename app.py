
from flask import Flask, request, jsonify
import openai
import os

app = Flask(__name__)

openai.api_type = "azure"
openai.api_key = os.getenv("OPENAI_API_KEY")
openai.api_base = os.getenv("OPENAI_API_BASE")  # z. B. https://landki-foundry.openai.azure.com/
openai.api_version = "2024-05-01-preview"
deployment_name = os.getenv("OPENAI_DEPLOYMENT")  # z. B. gpt-4o

@app.route("/", methods=["GET"])
def home():
    return "LandKI GPT-4o Bot ist online."

@app.route("/ask", methods=["POST"])
def ask():
    user_input = request.json.get("question", "")
    response = openai.ChatCompletion.create(
        engine=deployment_name,
        messages=[{"role": "user", "content": user_input}],
        temperature=0.3,
        max_tokens=500
    )
    answer = response["choices"][0]["message"]["content"]
    return jsonify({"answer": answer})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
