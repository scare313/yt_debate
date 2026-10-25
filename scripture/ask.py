#!/usr/bin/env python3
"""Ask the Gita: answer a viewer's question from the verse library.

    .venv/bin/python scripture/ask.py "How do I stop worrying about results?" --name Rohit
    .venv/bin/python scripture/ask.py --search "anger"          # just show the matching verses

Saves scripture/data/answers/<id>.json and an editable <id>.script.txt (the same edit-then-voice
workflow as the debate show). Uses the same LLM settings as config/settings.yaml.
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402
from rich.console import Console  # noqa: E402

from engine.llm import LLM  # noqa: E402
from engine.storage import slugify  # noqa: E402
from scripture.qa.answer import Screen, write_answer  # noqa: E402
from scripture.qa.library import Library  # noqa: E402

HERE = ROOT / "scripture"
OUT = HERE / "data" / "answers"
console = Console()


def chapter_verse(vid: str) -> str:
    _, ref = vid.split(" ", 1)
    ch, v = ref.split(".", 1)
    return f"chapter {ch}, verse {v}" if "-" not in v else f"chapter {ch}, verses {v.replace('-', ' to ')}"


def build_script(ans, lib, narrator: dict) -> list[dict]:
    """The spoken order of a Short. Verse and purport text come straight from the library."""
    turns = [{"kind": "question", "text": (f"{ans.asker} asks: " if ans.asker else "Today's question: ") + ans.question}]
    turns.append({"kind": "opening", "text": ans.opening})
    for vid in ans.verses:
        v = lib.by_id[vid]
        turns.append({"kind": "verse", "verse": vid,
                      "text": f"The Bhagavad-gita, {chapter_verse(vid)}, says: {v.translation}"})
    turns.append({"kind": "explanation", "text": ans.explanation})
    if ans.purport_quote:
        turns.append({"kind": "quote", "verse": ans.quote_verse,
                      "text": f"Srila Prabhupada explains in his purport: {ans.purport_quote}"})
    turns.append({"kind": "practice", "text": ans.practice})
    if ans.reflection:
        turns.append({"kind": "reflection", "text": ans.reflection})
    # No spoken call to action: the end card asks for questions, and it keeps the Short short.
    return [t for t in turns if t["text"].strip()]


def write_script_file(path: Path, record: dict):
    lines = [
        f"# {record['show']} script. Edit the text after each \"kind:\" and save.",
        "# Lines marked [verse] and [quote] are the book's exact words: don't change those.",
        "# You can rewrite the other lines, delete a line, or add one as \"+ kind: text\".",
        f"# Question: {record['question']}",
        f"# Verses: {', '.join(record['verses'])}",
        "",
    ]
    for i, t in enumerate(record["turns"], 1):
        tag = t["kind"] + (f" {t['verse']}" if t.get("verse") else "")
        lines.append(f"{i:02d} [{tag}]: {t['text']}")
    path.write_text("\n".join(lines) + "\n")


def save_answer(result, lib, narrator: dict, model: str) -> tuple[dict, str]:
    """Write <id>.json and the editable <id>.script.txt for a written (not yet voiced) answer."""
    record = {
        "show": narrator["show_name"],
        "question": result.question, "asker": result.asker,
        "verses": result.verses, "candidates": result.candidates,
        "screen": result.screen, "attempts": result.attempts,
        "model": model,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "attribution": narrator["attribution"].strip(),
        "disclaimer": narrator["disclaimer"].strip(),
        "verse_texts": {vid: {"devanagari": lib.by_id[vid].devanagari,
                              "transliteration": lib.by_id[vid].transliteration,
                              "translation": lib.by_id[vid].translation,
                              "url": lib.by_id[vid].url} for vid in result.verses},
        "turns": build_script(result, lib, narrator),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    rid = f"{datetime.now():%Y-%m-%d_%H%M%S}_{slugify(result.question)}"
    (OUT / f"{rid}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2))
    write_script_file(OUT / f"{rid}.script.txt", record)
    return record, rid


def main():
    ap = argparse.ArgumentParser(description="Answer a viewer's question from the Bhagavad-gita")
    ap.add_argument("question", nargs="?", help="the viewer's question (English)")
    ap.add_argument("--name", default="", help="viewer's name, read out on air")
    ap.add_argument("--search", metavar="TEXT", help="only show which verses match TEXT")
    ap.add_argument("--model", help="override the LLM model")
    ap.add_argument("--library", help="verse library file (default: the full Bhagavad-gita library)")
    ap.add_argument("--voice", action="store_true", help="also voice it right away (narrator + timings)")
    ap.add_argument("--verses", type=int, default=1, help="how many verses to use (default 1, keeps Shorts short)")
    args = ap.parse_args()

    cfg = yaml.safe_load((ROOT / "config" / "settings.yaml").read_text())
    narrator = yaml.safe_load((HERE / "config" / "narrator.yaml").read_text())
    lib = Library(Path(args.library).resolve() if args.library else None)
    console.print(f"[dim]Library: {lib.path.relative_to(ROOT)} · {len(lib.verses)} verses[/]")

    if args.search:
        for h in lib.search(args.search, k=8):
            console.print(f"[bold]{h.verse.id}[/] [dim]({h.score:.2f})[/] {h.verse.translation[:150]}")
        return 0
    if not args.question:
        ap.error("give a question, or --search TEXT")

    llm = LLM(cfg["llm"]["base_url"], cfg["llm"]["api_key"], args.model or cfg["llm"]["model"])
    result = write_answer(llm, lib, narrator["persona"], args.question, args.name, max_verses=args.verses)
    if isinstance(result, Screen):
        console.print(f"[yellow]Not answered on the show ({result.reason}).[/] {result.message}")
        return 2

    record, rid = save_answer(result, lib, narrator, llm.model)

    console.rule(f"[bold]{result.question}[/]")
    for t in record["turns"]:
        color = {"verse": "bright_yellow", "quote": "bright_cyan"}.get(t["kind"], "white")
        console.print(f"[dim]{t['kind']:>11}[/]  [{color}]{t['text']}[/]")
    console.rule()
    if args.voice:
        from scripture.qa.voicing import voice_answer
        console.print("[dim]Voicing...[/]")
        voice_answer(record, OUT / f"{rid}.json", narrator)
        last = record["turns"][-1]
        console.print(f"[dim]Voiced: {last['start_s'] + last['audio_seconds']:.0f}s[/]")
    console.print(f"[dim]Verses {', '.join(result.verses)} (from {len(result.candidates)} candidates, "
                  f"{result.attempts} attempt{'s' if result.attempts > 1 else ''}) · "
                  f"saved scripture/data/answers/{rid}.script.txt[/]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
