import os

from flask import Flask, jsonify

app = Flask(__name__)

NOTES = [{"id": 1, "text": "buy milk"}, {"id": 2, "text": "ship v2"}]


@app.get("/health")
def health():
    return "ok", 200, {"Content-Type": "text/plain"}


@app.get("/notes")
def notes():
    return jsonify(NOTES)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
