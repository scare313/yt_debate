"""Voice an answer: narrator speech for every line, saved per line plus full.wav with timings."""
import json
import re
from pathlib import Path

from engine.characters import Character
from engine.tts import PiperTTS
from engine.voice import VoiceSession

from .speech import english_speech

ROOT = Path(__file__).resolve().parent.parent.parent
LINE = re.compile(r"^(\d+|\+)\s*\[\s*([a-z]+)(?:\s+([A-Z]+ [\d.\-]+))?\s*\]\s*:\s*(.+)$")


class QuietPrinter:
    def header(self, char, label): print(f"  🎙️ {label}: ", end="", flush=True)
    def token(self, text): print(text[:90] + ("…" if len(text) > 90 else ""), end="")
    def end(self, seconds): print(f"  ({seconds}s)")
    def info(self, text): print(text)


def narrator_character(narrator: dict) -> Character:
    return Character(key="narrator", name=narrator.get("narrator_name", "Narrator"), emoji="🪔",
                     color="bright_yellow", persona="", voice=narrator["voice"])


def turns_from_script(script: Path, record: dict) -> list[dict]:
    """Read an edited .script.txt back into turns (keeps each line's kind and verse)."""
    turns = []
    for n, raw in enumerate(script.read_text().splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = LINE.match(line)
        if not m:
            raise ValueError(f"Line {n} should look like '03 [explanation]: text' or '+ [practice]: text':\n  {raw}")
        _, kind, verse, text = m.groups()
        t = {"kind": kind, "text": text.strip()}
        if verse:
            t["verse"] = verse
        turns.append(t)
    # The book's words must stay the book's words.
    for t in turns:
        if t["kind"] in ("verse", "quote") and t.get("verse") in record.get("verse_texts", {}):
            book = record["verse_texts"][t["verse"]]["translation"]
            if t["kind"] == "verse" and _norm(book) not in _norm(t["text"]):
                print(f"⚠️  The [verse {t['verse']}] line no longer matches the book's translation. "
                      f"Keep the book's exact words on that line.")
    return turns


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def voice_answer(record: dict, json_path: Path, narrator: dict, play: bool = False) -> dict:
    cfg_voice = {"gap_seconds": 0.6, "call_filter": False}      # calm pacing, studio sound
    models_dir = ROOT / "models" / "piper"
    audio_dir = json_path.with_suffix("")                        # .../<id>/
    if audio_dir.exists():
        for f in audio_dir.glob("*.wav"):
            f.unlink()
    session = VoiceSession(PiperTTS(models_dir), cfg_voice, audio_dir, QuietPrinter(), play=play,
                           speech_fn=english_speech)
    char = narrator_character(narrator)
    for t in record["turns"]:
        session.turn(char, t["kind"], t["text"], t)
    full = session.finish()
    record["audio_full"] = f"{audio_dir.name}/{full.name}" if full else None
    json_path.write_text(json.dumps(record, ensure_ascii=False, indent=2))
    return record
