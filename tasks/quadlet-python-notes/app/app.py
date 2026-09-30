import json
import os
import pathlib

from flask import Flask, jsonify, request

if not os.environ.get("DB_PASSWORD"):
    raise SystemExit("DB_PASSWORD is required")

DATA = pathlib.Path(os.environ.get("DATA_DIR", "/var/lib/notes")) / "notes.json"
app = Flask(__name__)


def load():
    return json.loads(DATA.read_text()) if DATA.exists() else []


@app.get("/health")
def health():
    return "ok"


@app.route("/notes", methods=["GET", "POST"])
def notes():
    items = load()
    if request.method == "POST":
        items.append({"text": str((request.get_json(silent=True) or {}).get("text", ""))})
        DATA.parent.mkdir(parents=True, exist_ok=True)
        DATA.write_text(json.dumps(items))
    return jsonify(items)
