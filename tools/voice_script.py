#!/usr/bin/env python3
"""Voice an edited debate script.

    .venv/bin/python debate.py --script-only --short "..."          # 1. write the script
    (edit data/debates/<id>.script.txt in any text editor)          # 2. punch it up
    .venv/bin/python tools/voice_script.py "data/debates/<id>.script.txt"   # 3. voice it

Keeps each line's role (question, answer, interruption, viewer comment...) from the original
debate, re-voices every line, and saves the result as the newest debate, so the show screen
(and OBS) plays it next. Old audio for this debate is replaced.
"""
import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402
from rich.console import Console  # noqa: E402

from engine.characters import load_character  # noqa: E402
from engine.orchestrator import unspeakable_words  # noqa: E402
from engine.storage import write_script  # noqa: E402
from engine.tts import PiperTTS  # noqa: E402
from engine.voice import VoiceSession  # noqa: E402

LINE = re.compile(r"^(\d+|\+)\s+([a-z0-9_]+)\s*(?:\[[^\]]*\])?\s*:\s*(.+)$")
console = Console()


class Printer:
    def header(self, char, label):
        console.print(f"\n{char.emoji} [bold]{char.name}[/] [dim]({label})[/]")

    def token(self, text):
        console.print(text, markup=False, highlight=False, end="")

    def end(self, seconds):
        console.print(f"  [dim]({seconds}s)[/]")

    def info(self, text):
        console.print(f"[dim]{text}[/]")


def main():
    ap = argparse.ArgumentParser(description="Voice an edited debate script")
    ap.add_argument("script", help="data/debates/<id>.script.txt")
    ap.add_argument("--play", action="store_true", help="also play it while voicing")
    args = ap.parse_args()

    script = Path(args.script).resolve()
    debate_id = script.name.removesuffix(".script.txt")
    json_path = script.with_name(f"{debate_id}.json")
    if not json_path.exists():
        sys.exit(f"Can't find the debate file next to the script: {json_path.name}")
    record = json.loads(json_path.read_text())
    cfg = yaml.safe_load((ROOT / "config" / "settings.yaml").read_text())
    host = next((t["speaker"] for t in record["turns"] if t["speaker"] not in record["sides"]), "ritika")
    old_highlight = record["turns"][record["highlight"]] if record.get("highlight") is not None else None

    # Parse the edited script.
    turns, winner = [], None
    for n, raw in enumerate(script.read_text().splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.upper().startswith("WINNER:"):
            winner = line.split(":", 1)[1].strip().lower()
            continue
        m = LINE.match(line)
        if not m:
            sys.exit(f"Line {n} isn't in the form '07 name: text' or '+ name: text':\n  {raw}")
        num, speaker, text = m.groups()
        if not (ROOT / "config" / "characters" / f"{speaker}.yaml").exists():
            sys.exit(f"Line {n}: no character called '{speaker}' (see config/characters/)")
        if num == "+":
            base = {"kind": "question" if speaker == host else "answer"}
        else:
            i = int(num) - 1
            if not 0 <= i < len(record["turns"]):
                sys.exit(f"Line {n}: there is no line {num} in the original debate. Use '+ {speaker}: ...' to add one.")
            base = {k: v for k, v in record["turns"][i].items()
                    if k not in ("audio", "audio_seconds", "start_s", "spoken_text", "raw_text", "gen_seconds")}
            base["_orig"] = i
        char = load_character(ROOT / "config", speaker)
        turns.append({**base, "speaker": speaker, "name": char.name,
                      "side": record["sides"].get(speaker), "text": text.strip()})
    if not turns:
        sys.exit("The script has no lines.")

    # Warn about English-letter words the Hindi voice will stumble on (doesn't stop voicing).
    warned = False
    for k, t in enumerate(turns, 1):
        bad = unspeakable_words(t["text"])
        if bad:
            if not warned:
                console.print("[yellow]Heads-up: these English-letter words will sound wrong. "
                              "Write them in Hindi script for a better voice:[/]")
                warned = True
            console.print(f"[yellow]  line {k:02d} ({t['speaker']}): {', '.join(bad)}[/]")

    # Re-voice everything, replacing this debate's old audio.
    audio_dir = json_path.parent / debate_id
    if audio_dir.exists():
        for f in audio_dir.glob("*.wav"):
            f.unlink()
    tts = PiperTTS(ROOT / cfg["voice"]["models_dir"])
    session = VoiceSession(tts, cfg["voice"], audio_dir, Printer(), play=args.play)
    console.rule(f"[bold]Voicing: {record['topic']}[/]")
    for t in turns:
        char = load_character(ROOT / "config", t["speaker"])
        session.turn(char, t.get("kind", ""), t["text"], t)
    full = session.finish()

    # Keep the cold-open line if it survived the edit.
    record["highlight"] = next((k for k, t in enumerate(turns)
                                if old_highlight is not None and t.get("_orig") == record["highlight"]), None)
    for t in turns:
        t.pop("_orig", None)
    record["turns"] = turns
    if winner and winner != (record.get("verdict") or {}).get("winner"):
        record["verdict"] = {**(record.get("verdict") or {}), "winner": winner, "scores": None, "score": "",
                             "reason": "Edited by hand."}
    record["audio_full"] = f"{debate_id}/{full.name}" if full else None
    record["edited_at"] = record["created_at"] = datetime.now().isoformat(timespec="seconds")  # newest = plays next
    json_path.write_text(json.dumps(record, ensure_ascii=False, indent=2))
    write_script(json_path.parent.parent, record, debate_id)  # renumbered, ready for another round of edits

    last = turns[-1]
    secs = last["start_s"] + last["audio_seconds"]
    console.rule()
    console.print(f"[bold]Done:[/] {len(turns)} lines, {int(secs // 60)}:{int(secs % 60):02d} long. "
                  f"It's now the newest debate, so the show screen plays it next.")


if __name__ == "__main__":
    main()
