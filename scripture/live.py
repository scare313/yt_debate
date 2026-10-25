#!/usr/bin/env python3
"""Ask the Gita — live console. You pick questions from the YouTube live chat; nothing airs unreviewed.

    .venv/bin/python scripture/live.py

Type a viewer's question as   Name: question   (or just the question). The answer is written in
a few seconds and shown here. Then:
    a  air it      (voices it; the live screen plays it next)
    e  edit a line, then choose again
    s  skip it     (nothing airs)
Other commands at the prompt:  r = refresh the verse library (the download keeps growing),  q = quit.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402
from rich.console import Console  # noqa: E402

from engine.llm import LLM  # noqa: E402
from engine.safety import Blocklist  # noqa: E402
from scripture.ask import OUT, save_answer, write_script_file  # noqa: E402
from scripture.qa.answer import Screen, write_answer  # noqa: E402
from scripture.qa.library import Library  # noqa: E402
from scripture.qa.voicing import voice_answer  # noqa: E402

console = Console()
EDITABLE = {"opening", "explanation", "practice", "reflection", "question"}   # never the book's own words


def load_library() -> Library:
    # Pull in whatever the background download has fetched so far, then load the biggest library.
    subprocess.run([sys.executable, str(ROOT / "scripture/tools/build_vedabase.py"), "--book", "bg", "--offline"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    lib = Library()
    console.print(f"[dim]Library: {len(lib.verses)} verses ({lib.path.name})[/]")
    return lib


def parse(line: str) -> tuple[str, str]:
    name, sep, text = line.partition(":")
    if sep and 0 < len(name.strip()) <= 40 and len(text.strip()) > 5:
        return re.sub(r"[_.@]+", " ", name).strip(), text.strip()
    return "", line.strip()


def show(record: dict):
    console.rule(f"[bold]{record['question']}[/]")
    for i, t in enumerate(record["turns"], 1):
        color = {"verse": "bright_yellow", "quote": "bright_cyan"}.get(t["kind"], "white")
        lock = "" if t["kind"] in EDITABLE else " 🔒"
        console.print(f"[dim]{i}. {t['kind']:>11}{lock}[/]  [{color}]{t['text']}[/]")
    console.rule()


def main():
    cfg = yaml.safe_load((ROOT / "config" / "settings.yaml").read_text())
    narrator = yaml.safe_load((ROOT / "scripture" / "config" / "narrator.yaml").read_text())
    llm = LLM(cfg["llm"]["base_url"], cfg["llm"]["api_key"], cfg["llm"]["model"])
    blocklist = Blocklist(ROOT / "config" / "blocklist.txt")
    lib = load_library()
    console.print("[bold]Live console.[/] Type  [cyan]Name: question[/]  from the chat.  "
                  "[dim](r = refresh library, q = quit)[/]")

    while True:
        try:
            line = console.input("\n[bold green]question > [/]").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            continue
        if line.lower() in ("q", "quit", "exit"):
            break
        if line.lower() == "r":
            lib = load_library()
            continue

        name, question = parse(line)
        if blocklist.check(name) or blocklist.check(question):
            console.print("[red]Blocked words in the name or question. Skipped.[/]")
            continue
        with console.status("Writing the answer..."):
            try:
                result = write_answer(llm, lib, narrator["persona"], question, name)
            except ValueError as e:
                console.print(f"[red]Couldn't write a grounded answer: {e}[/]")
                continue
        if isinstance(result, Screen):
            console.print(f"[yellow]Not for the show ({result.reason}).[/] Reply in chat yourself if needed:\n{result.message}")
            continue

        record, rid = save_answer(result, lib, narrator, llm.model)
        json_path = OUT / f"{rid}.json"
        while True:
            show(record)
            choice = console.input("[bold]a[/]ir / [bold]e[/]dit a line / [bold]s[/]kip > ").strip().lower()
            if choice == "e":
                try:
                    n = int(console.input("line number > ")) - 1
                    t = record["turns"][n]
                except (ValueError, IndexError):
                    console.print("[red]No such line.[/]")
                    continue
                if t["kind"] not in EDITABLE:
                    console.print("[red]That line is the book's own words (🔒); it can't be edited.[/]")
                    continue
                new = console.input("new text > ").strip()
                if new:
                    t["text"] = new
                    json_path.write_text(json.dumps(record, ensure_ascii=False, indent=2))
                    write_script_file(OUT / f"{rid}.script.txt", record)
                continue
            if choice == "a":
                with console.status("Voicing..."):
                    voice_answer(record, json_path, narrator)
                last = record["turns"][-1]
                console.print(f"[green]✓ On air next[/] ({last['start_s'] + last['audio_seconds']:.0f}s). "
                              f"Verse {', '.join(record['verses'])}.")
                break
            if choice == "s":
                for f in (json_path, OUT / f"{rid}.script.txt"):
                    f.unlink(missing_ok=True)
                console.print("[dim]Skipped; nothing will air.[/]")
                break


if __name__ == "__main__":
    main()
