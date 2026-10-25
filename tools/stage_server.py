#!/usr/bin/env python3
"""Local server for the show screen.

    .venv/bin/python tools/stage_server.py          # then open http://localhost:8765/

Serves stage/ (the page), data/debates/ (debate JSON + audio), and two small APIs:
    /api/debates     voiced debates, newest first
    /api/characters  name, title, colour and emoji for every character
Listens on localhost only.
"""
import json
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

import yaml

ROOT = Path(__file__).resolve().parent.parent
ALLOWED = ("stage/", "data/debates/", "scripture/stage/", "scripture/data/answers/")
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8765


def list_debates() -> list[dict]:
    out = []
    for f in (ROOT / "data" / "debates").glob("*.json"):
        try:
            d = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if not d.get("audio_full"):
            continue
        last = d["turns"][-1] if d.get("turns") else {}
        out.append({
            "id": f.stem,
            "topic": d.get("topic", ""),
            "created_at": d.get("created_at", ""),
            "format": d.get("format", "classic"),
            "speakers": list(d.get("sides", {}).keys()),
            "seconds": round(last.get("start_s", 0) + last.get("audio_seconds", 0)),
        })
    return sorted(out, key=lambda x: x["created_at"], reverse=True)


def list_answers() -> list[dict]:
    """Voiced Ask the Gita answers, newest first."""
    out = []
    for f in (ROOT / "scripture" / "data" / "answers").glob("*.json"):
        try:
            d = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if not d.get("audio_full"):
            continue
        last = d["turns"][-1]
        out.append({"id": f.stem, "question": d["question"], "asker": d.get("asker", ""),
                    "verses": d.get("verses", []), "created_at": d.get("created_at", ""),
                    "seconds": round(last.get("start_s", 0) + last.get("audio_seconds", 0))})
    return sorted(out, key=lambda x: x["created_at"], reverse=True)


def list_characters() -> dict:
    out = {}
    for f in sorted((ROOT / "config" / "characters").glob("*.yaml")):
        d = yaml.safe_load(f.read_text()) or {}
        out[f.stem] = {k: d.get(k, "") for k in ("name", "title", "color", "emoji")}
        out[f.stem]["jokes"] = d.get("jokes") or []
    return out


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            self.send_response(302)
            self.send_header("Location", "/stage/")
            self.end_headers()
            return
        if path == "/api/debates":
            return self._json(list_debates())
        if path == "/api/characters":
            return self._json(list_characters())
        if path == "/api/answers":
            return self._json(list_answers())
        if path in ("/gita", "/gita/"):
            self.send_response(302)
            self.send_header("Location", "/scripture/stage/")
            self.end_headers()
            return
        rel = unquote(path).lstrip("/")
        if not rel.startswith(ALLOWED) or ".." in rel.split("/"):
            self.send_error(404)
            return
        super().do_GET()

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")  # always show the latest edits
        super().end_headers()

    def _json(self, data):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    print(f"Show screen: http://localhost:{PORT}/   (Ctrl+C to stop)")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
