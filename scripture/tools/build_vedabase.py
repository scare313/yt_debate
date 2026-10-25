#!/usr/bin/env python3
"""Build a verse library from vedabase.io (Bhaktivedanta Book Trust texts, used with BBT's permission).

    .venv/bin/python scripture/tools/build_vedabase.py --book bg      # Bhagavad-gita As It Is (~2 h)
    .venv/bin/python scripture/tools/build_vedabase.py --book sb      # Srimad-Bhagavatam (days)
    .venv/bin/python scripture/tools/build_vedabase.py --book bg --limit 3   # quick test

Polite by design: follows robots.txt (10-second crawl delay, only /library/ pages), caches every
page in scripture/.cache/vedabase/ so it can be stopped and resumed at any time, and never
re-downloads a cached page.

Output: scripture/library/vedabase/<book>.jsonl, one verse (or verse group) per line with
devanagari, transliteration, synonyms, translation and purport. Kept out of git: it's BBT's text.
"""
import argparse
import hashlib
import json
import re
import sys
import time
import urllib.request
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
CACHE = HERE / ".cache" / "vedabase"
OUT_DIR = HERE / "library" / "vedabase"
BASE = "https://vedabase.io"
DELAY = 10.0  # robots.txt: Crawl-delay: 10
UA = "dangal-scripture-library/0.1 (personal project; respects robots.txt)"
BOOK_NAMES = {"bg": "Bhagavad-gita As It Is", "sb": "Srimad-Bhagavatam", "cc": "Sri Caitanya-caritamrta",
              "iso": "Sri Isopanisad", "noi": "The Nectar of Instruction"}
PARTS = ("devanagari", "verse_text", "synonyms", "translation", "purport")

_last_request = 0.0
OFFLINE = False


def get(path: str) -> str | None:
    """Fetch a vedabase page (cached; at most one network request every DELAY seconds)."""
    global _last_request
    cache = CACHE / (hashlib.sha1(path.encode()).hexdigest() + ".html")
    if cache.exists():
        return cache.read_text()
    if OFFLINE:
        return None
    wait = DELAY - (time.time() - _last_request)
    if wait > 0:
        time.sleep(wait)
    req = urllib.request.Request(BASE + path, headers={"User-Agent": UA})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                html = r.read().decode("utf-8")
            break
        except Exception as e:
            _last_request = time.time()
            if attempt == 2:
                raise RuntimeError(f"{path}: {e}")
            time.sleep(DELAY * (attempt + 2))
    _last_request = time.time()
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(html)
    return html


class VerseParser(HTMLParser):
    """Collects the text inside <div class="av-devanagari|av-verse_text|..."> blocks."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = {p: [] for p in PARTS}
        self.current, self.depth = None, 0

    def handle_starttag(self, tag, attrs):
        cls = dict(attrs).get("class", "") or ""
        if self.current is None and tag == "div":
            for p in PARTS:
                if f"av-{p}" in cls.split():
                    self.current, self.depth = p, 1
                    return
        elif self.current:
            if tag == "div":
                self.depth += 1
            if tag in ("br", "p", "div"):
                self.parts[self.current].append("\n")

    def handle_endtag(self, tag):
        if self.current and tag == "div":
            self.depth -= 1
            if self.depth == 0:
                self.current = None
        elif self.current and tag == "p":
            self.parts[self.current].append("\n")

    def handle_data(self, data):
        if self.current:
            self.parts[self.current].append(data)


def parse_verse(html: str) -> dict:
    p = VerseParser()
    p.feed(html)
    out = {}
    for name, chunks in p.parts.items():
        text = unescape("".join(chunks))
        # Drop the block's own heading ("Translation", "Purport", ...).
        text = re.sub(r"^\s*(Devanagari|Verse text|Synonyms|Translation|Purport)\s*", "", text)
        lines = [re.sub(r"[ \t]+", " ", l).strip() for l in text.splitlines()]
        out[name] = [l for l in lines if l]
    return {
        "devanagari": "\n".join(out["devanagari"]),
        "transliteration": "\n".join(out["verse_text"]),
        "synonyms": " ".join(out["synonyms"]),
        "translation": " ".join(out["translation"]),
        "purport": out["purport"],           # list of paragraphs
    }


def links_under(html: str, prefix: str) -> list[str]:
    """Child pages directly below `prefix` (e.g. /en/library/bg/2/ -> /en/library/bg/2/47/)."""
    found = []
    for href in re.findall(r'href="(/en/library/[^"#?]+/)"', html):
        if href.startswith(prefix) and href != prefix and href.count("/") == prefix.count("/") + 1:
            if href not in found:
                found.append(href)
    return found


def natural_key(path: str):
    return [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", path)]


def main():
    ap = argparse.ArgumentParser(description="Build a verse library from vedabase.io")
    ap.add_argument("--book", default="bg", help="bg, sb, cc, iso, noi, ...")
    ap.add_argument("--limit", type=int, default=0, help="stop after N verse pages (for testing)")
    ap.add_argument("--offline", action="store_true",
                    help="no downloads: build the library from pages already cached (e.g. while a download runs)")
    args = ap.parse_args()
    global OFFLINE
    OFFLINE = args.offline

    root = f"/en/library/{args.book}/"
    out_path = OUT_DIR / f"{args.book}{'.partial' if args.offline else ''}.jsonl"
    rows, queue, seen = [], [root], set()
    start = time.time()

    while queue:
        path = queue.pop(0)
        if path in seen:
            continue
        seen.add(path)
        html = get(path)
        if html is None:
            continue
        if "av-translation" in html:                     # a verse page
            v = parse_verse(html)
            ref = path[len(root):].strip("/").split("/")  # e.g. ["2", "47"] or ["1", "16-18"] or ["1", "1", "1"]
            rows.append({
                "id": f"{args.book.upper()} {'.'.join(ref)}",
                "book": BOOK_NAMES.get(args.book, args.book),
                "ref": ref,
                "url": BASE + path,
                **v,
                "source": "Bhaktivedanta Book Trust (vedabase.io), used with permission",
            })
            n = len(rows)
            if n % 10 == 0 or n <= 3:
                print(f"  {n} verses · last {rows[-1]['id']} · {int(time.time() - start)}s", flush=True)
            if args.limit and n >= args.limit:
                break
        else:                                            # book / canto / chapter index
            children = sorted(links_under(html, path), key=natural_key)
            queue = children + queue                     # depth-first keeps the book order

    rows.sort(key=lambda r: natural_key(".".join(r["ref"])))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    empty = [r["id"] for r in rows if not r["translation"]]
    print(f"\nWrote {len(rows)} entries to {out_path.relative_to(HERE.parent)}"
          f" ({len(empty)} without a translation{': ' + ', '.join(empty[:10]) if empty else ''})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
