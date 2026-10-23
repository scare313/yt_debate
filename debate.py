#!/usr/bin/env python3
"""AI debate in the terminal, with voices.

    python debate.py "क्या जीएसटी ने छोटे व्यापारियों की ज़िंदगी आसान बनाई?"   # one debate, spoken
    python debate.py                                # interactive: keep entering topics
    python debate.py --no-voice --language english "Tea vs coffee"     # text only
    python debate.py --silent "..."                 # save audio without playing it
    python debate.py --comment "Rohit_from_Pune: तिवारी जी कुछ बोलिए!" "..."   # viewer comment on air
"""
import argparse
import os
import sys
from pathlib import Path

import openai
import yaml
from rich.console import Console

from engine.characters import load_character
from engine.chat import build_chat
from engine.llm import LLM
from engine.orchestrator import LANGUAGE_RULES, Debate
from engine.safety import Blocklist
from engine.storage import Scoreboard, new_debate_id, save_debate
from engine.voice import VoiceSession

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "config"
DATA = ROOT / "data"

console = Console()


class TerminalPrinter:
    def header(self, char, label):
        console.print()
        console.print(f"{char.emoji} [bold {char.color}]{char.name.upper()}[/] [dim]({label})[/]")
        self._color = char.color

    def token(self, text):
        console.print(text, end="", style=self._color, markup=False, highlight=False)

    def end(self, seconds):
        console.print(f"  [dim]({seconds}s)[/]")

    def info(self, text):
        console.print(f"\n[dim]{text}[/]")


def load_settings(args) -> dict:
    cfg = yaml.safe_load((CONFIG / "settings.yaml").read_text())
    if args.model:
        cfg["llm"]["model"] = args.model
    if args.rounds is not None:
        cfg["debate"]["rebuttal_rounds"] = args.rounds   # classic
        cfg["debate"]["exchanges"] = args.rounds         # news
    if args.format:
        cfg["debate"]["format"] = args.format
    if args.words:
        cfg["debate"]["max_words_per_turn"] = args.words
    if args.language:
        cfg["debate"]["language"] = args.language
    if args.cast:
        keys = [k.strip() for k in args.cast.split(",") if k.strip()]
        if len(keys) != 2:
            sys.exit("--cast needs exactly two characters, e.g. --cast rahul,amit")
        missing = [k for k in keys if not (CONFIG / "characters" / f"{k}.yaml").exists()]
        if missing:
            sys.exit(f"No character file for: {', '.join(missing)} (see config/characters/)")
        cfg["cast"]["debaters"] = keys
    if args.for_side and args.for_side not in cfg["cast"]["debaters"]:
        sys.exit(f"--for must be one of: {', '.join(cfg['cast']['debaters'])}")
    cfg["for_side"] = args.for_side
    if args.no_voice:
        cfg["voice"]["enabled"] = False
    cfg["voice"]["play"] = not args.silent
    return cfg


def make_tts(cfg: dict):
    """Load the TTS engine once and reuse it across debates (keeps voices in memory)."""
    if not cfg["voice"]["enabled"]:
        return None
    keys = [cfg["cast"]["host"], *cfg["cast"]["debaters"]]
    no_voice = [k for k in keys if not load_character(CONFIG, k).voice.get("model")]
    if no_voice:
        sys.exit(f"No voice set for: {', '.join(no_voice)}. Add a 'voice:' block to their file "
                 f"in config/characters/, or run with --no-voice.")
    try:
        from engine.tts import PiperTTS
        return PiperTTS(ROOT / cfg["voice"]["models_dir"])
    except ImportError:
        sys.exit("Piper is not installed. Run: .venv/bin/pip install -r requirements.txt  (or use --no-voice)")


def load_chat_lines(args) -> list[str]:
    """Raw viewer messages, one 'Name: message' per line. Only real comments: never invent viewers."""
    lines = list(args.comment or [])
    if args.comments_file:
        lines += [l for l in Path(args.comments_file).read_text().splitlines() if l.strip() and not l.startswith("#")]
    return lines


def run_one(topic: str, cfg: dict, blocklist: Blocklist, tts=None, chat_lines: list[str] | None = None) -> bool:
    topic = topic.strip()
    if not topic:
        return True
    blocked = blocklist.check(topic)
    if blocked:
        console.print(f"[red]Topic rejected (blocked term: '{blocked}'). Try another.[/]")
        return True

    llm = LLM(cfg["llm"]["base_url"], cfg["llm"]["api_key"], cfg["llm"]["model"])
    host = load_character(CONFIG, cfg["cast"]["host"])
    debaters = [load_character(CONFIG, k) for k in cfg["cast"]["debaters"]]
    chat = build_chat(chat_lines or [], debaters, blocklist)
    if chat_lines:
        r = chat.to_record()
        console.print(f"[dim]Chat: {len(r['messages'])} shown · {len(r['greeters'])} greetings · "
                      f"{len(chat.questions())} questions · {sum(r['emoji_counts'].values())} emojis · "
                      f"votes {r['votes'] or '-'} · {r['blocked']} blocked[/]")
    settings = {**cfg["debate"],
                "temperature": cfg["llm"]["temperature"],
                "judge_temperature": cfg["llm"]["judge_temperature"]}
    debate_id = new_debate_id(topic)
    printer = TerminalPrinter()
    voice = (VoiceSession(tts, cfg["voice"], DATA / "debates" / debate_id, printer, play=cfg["voice"]["play"])
             if tts else None)
    debate = Debate(llm, host, debaters, settings, Scoreboard(DATA / "scoreboard.json"), printer, voice=voice)

    console.rule(f"[bold]DEBATE: {topic}[/]")
    try:
        record = debate.run(topic, for_side=cfg["for_side"], chat=chat)
        if voice:
            full = voice.finish()  # waits until the last turn has been played
            if full:
                record["audio_full"] = f"{debate_id}/{full.name}"
    except KeyboardInterrupt:
        if voice:
            voice.stop()
        debate.record["status"] = "interrupted"
        path = save_debate(DATA, debate.record, debate_id)
        console.print(f"\n[yellow]Stopped. Partial debate saved: {os.path.relpath(path, ROOT)}[/]")
        return False
    except openai.APIConnectionError:
        if voice:
            voice.stop()
        console.print(f"\n[red]Can't reach the LLM at {cfg['llm']['base_url']}.[/] "
                      "Is Ollama running? Try: [bold]systemctl status ollama[/]")
        return False
    except openai.NotFoundError:
        if voice:
            voice.stop()
        console.print(f"\n[red]Model '{cfg['llm']['model']}' not found.[/] "
                      f"Download it with: [bold]ollama pull {cfg['llm']['model']}[/]")
        return False

    path = save_debate(DATA, record, debate_id)
    console.rule()
    v = record["verdict"]
    console.print(f"[bold]Winner:[/] {v['winner']}  [bold]Score:[/] {v['score']}  "
                  f"[dim]| generated in {record['total_seconds']}s | saved {os.path.relpath(path, ROOT)}[/]")
    if record.get("audio_full"):
        console.print(f"[dim]Audio: data/debates/{record['audio_full']}[/]")
    return True


def main():
    p = argparse.ArgumentParser(description="AI debate in your terminal")
    p.add_argument("topic", nargs="*", help="debate topic (leave empty for interactive mode)")
    p.add_argument("--model", help="override LLM model, e.g. llama3.2:3b")
    p.add_argument("--rounds", type=int, help="number of rebuttal rounds")
    p.add_argument("--words", type=int, help="max words per turn")
    p.add_argument("--language", choices=list(LANGUAGE_RULES), help="debate language")
    p.add_argument("--cast", help="two debaters from config/characters, e.g. rahul,amit")
    p.add_argument("--for", dest="for_side", help="which debater argues FOR (default: random)")
    p.add_argument("--format", choices=["news", "classic"], help="news: anchor-led show (default); classic: fixed rounds")
    p.add_argument("--comment", action="append", metavar='"NAME: TEXT"', help="viewer message (repeatable)")
    p.add_argument("--comments-file", help="viewer messages, one 'Name: message' per line (greetings, emojis, "
                                           "votes and questions are all handled)")
    p.add_argument("--no-voice", action="store_true", help="text only, no TTS")
    p.add_argument("--silent", action="store_true", help="generate and save audio, but don't play it")
    args = p.parse_args()

    cfg = load_settings(args)
    blocklist = Blocklist(CONFIG / "blocklist.txt")
    tts = make_tts(cfg)
    chat_lines = load_chat_lines(args)
    console.print(f"[dim]Model: {cfg['llm']['model']} · Language: {cfg['debate']['language']} · "
                  f"Format: {cfg['debate'].get('format', 'news')} · Chat messages: {len(chat_lines)} · "
                  f"Voice: {'off' if not tts else ('on' if cfg['voice']['play'] else 'save only')}[/]")

    if args.topic:
        sys.exit(0 if run_one(" ".join(args.topic), cfg, blocklist, tts, chat_lines) else 1)

    console.print("[bold]Interactive mode.[/] Type a topic and press Enter. 'q' to quit.")
    while True:
        try:
            topic = console.input("\n[bold green]Topic > [/]")
        except (EOFError, KeyboardInterrupt):
            break
        if topic.strip().lower() in {"q", "quit", "exit"}:
            break
        if not run_one(topic, cfg, blocklist, tts, chat_lines):
            break


if __name__ == "__main__":
    main()
