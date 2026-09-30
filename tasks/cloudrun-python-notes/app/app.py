import logging
import os
import time

from flask import Flask, jsonify, request

os.makedirs("logs", exist_ok=True)
logging.basicConfig(filename="logs/app.log", level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("notes")

app = Flask(__name__)
NOTES = [{"id": 1, "text": "ship it"}]


@app.before_request
def log_request():
    log.info("request %s %s", request.method, request.path)


@app.get("/health")
def health():
    return "ok", 200, {"Content-Type": "text/plain"}


@app.get("/notes")
def notes():
    return jsonify(NOTES)


@app.get("/report")
def report():
    # Builds a slow report; clients wait for it.
    time.sleep(3)
    return jsonify({"notes": len(NOTES)})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000)
