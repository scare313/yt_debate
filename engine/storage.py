"""Debate transcripts (one JSON per debate) and the persistent scoreboard."""
import json
import re
from datetime import datetime
from pathlib import Path


def slugify(text: str, max_len: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9\u0900-\u097F]+", "-", text.lower()).strip("-")
    return slug[:max_len].strip("-") or "debate"


def new_debate_id(topic: str) -> str:
    """e.g. 2026-10-20_193200_kya-gst-ne — names both the JSON and the audio folder."""
    return f"{datetime.now().strftime('%Y-%m-%d_%H%M%S')}_{slugify(topic)}"


def save_debate(data_dir: Path, debate: dict, debate_id: str) -> Path:
    out_dir = data_dir / "debates"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{debate_id}.json"
    path.write_text(json.dumps(debate, ensure_ascii=False, indent=2))
    return path


def write_script(data_dir: Path, debate: dict, debate_id: str) -> Path:
    """An easy-to-edit text version of the debate. Edit it, then voice it with tools/voice_script.py."""
    path = data_dir / "debates" / f"{debate_id}.script.txt"
    v = debate.get("verdict") or {}
    lines = [
        "# DANGAL 24x7 script. Edit the text after each \"name:\" and save. You can:",
        "#   - rewrite any line (keep it in Hindi script for the best voice)",
        "#   - delete a line you don't like",
        "#   - add a new line by starting it with \"+ name:\" where you want it, e.g. \"+ imran: ...\"",
        "#   - change WINNER below if you change who wins (then fix Ritika's verdict line too)",
        f"# Then voice it:  .venv/bin/python tools/voice_script.py \"data/debates/{debate_id}.script.txt\"",
        "#",
        f"# Topic: {debate.get('topic', '')}",
        "# Sides: " + ", ".join(f"{k} = {side}" for k, side in (debate.get("sides") or {}).items()),
        "",
        f"WINNER: {v.get('winner', 'draw')}",
        "",
    ]
    for i, t in enumerate(debate.get("turns", []), 1):
        tag = t.get("kind", "")
        if t.get("to"):
            tag += f" → {t['to']}"
        if t.get("comment"):
            tag += f" · {t['comment']['name']}"
        lines.append(f"{i:02d} {t['speaker']} [{tag}]: {' '.join(t['text'].split())}")
    path.write_text("\n".join(lines) + "\n")
    return path


class Scoreboard:
    """Wins/losses/draws and streak per character. streak > 0 = winning run, < 0 = losing run."""

    def __init__(self, path: Path):
        self.path = path
        self.data = json.loads(path.read_text()) if path.exists() else {}

    def get(self, key: str) -> dict:
        return self.data.setdefault(key, {"wins": 0, "losses": 0, "draws": 0, "streak": 0})

    def describe(self, key: str, name: str) -> str:
        s = self.get(key)
        line = f"{name}: {s['wins']} wins, {s['losses']} losses, {s['draws']} draws"
        if s["streak"] >= 2:
            line += f", on a {s['streak']}-debate winning streak"
        elif s["streak"] <= -2:
            line += f", on a {-s['streak']}-debate losing streak"
        return line

    def record(self, debaters: list[str], winner: str | None):
        for key in debaters:
            s = self.get(key)
            if winner is None:
                s["draws"] += 1
                s["streak"] = 0
            elif key == winner:
                s["wins"] += 1
                s["streak"] = s["streak"] + 1 if s["streak"] > 0 else 1
            else:
                s["losses"] += 1
                s["streak"] = s["streak"] - 1 if s["streak"] < 0 else -1
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2))
