#!/usr/bin/env python3
"""Build the Bhagavad Gita verse library: scripture/library/gita.jsonl (one verse per line).

    .venv/bin/python scripture/tools/build_gita.py

Sources (and what we take from each):
  Sanskrit + transliteration
      github.com/vedicscriptures/bhagavad-gita  ("slok" and "transliteration" fields only).
      The verses themselves are ancient, public-domain text. That repo also bundles modern
      translations and commentaries (Prabhupada/BBT, Chinmayananda, Gita Press, ...) that remain
      under their publishers' copyright: we never read or store those fields.
  English translation
      Annie Besant, "The Bhagavad-Gita", 4th edition (1922), via English Wikisource.
      Public domain (published before 1929; Besant died 1933).

Downloads are cached in scripture/.cache/ so re-runs don't hit the network again.
"""
import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
CACHE = HERE / ".cache"
OUT = HERE / "library" / "gita.jsonl"

SLOK_LIST = "https://api.github.com/repos/vedicscriptures/bhagavad-gita/contents/slok"
SLOK_RAW = "https://raw.githubusercontent.com/vedicscriptures/bhagavad-gita/main/slok/{name}"
BESANT_PAGE = "Bhagavad-Gita_(Besant_4th)/Discourse_{n}"
WIKI_API = "https://en.wikisource.org/w/api.php?action=parse&page={page}&prop=text&format=json"
UA = {"User-Agent": "dangal-scripture-library/0.1 (personal project)"}


def fetch(url: str, cache_name: str) -> str:
    path = CACHE / cache_name
    if path.exists():
        return path.read_text()
    req = urllib.request.Request(url, headers=UA)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                text = r.read().decode("utf-8")
            break
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return text


# ---------------- Sanskrit ----------------

def load_sanskrit() -> dict[tuple[int, int], dict]:
    names = [x["name"] for x in json.loads(fetch(SLOK_LIST, "slok_list.json"))]
    out = {}
    for n, name in enumerate(sorted(names), 1):
        m = re.match(r"bhagavadgita_chapter_(\d+)_slok_(\d+)\.json$", name)
        if not m:
            continue
        d = json.loads(fetch(SLOK_RAW.format(name=name), f"slok/{name}"))
        # Keep ONLY the public-domain verse text; drop every bundled translation/commentary.
        out[(int(m[1]), int(m[2]))] = {
            "sanskrit": clean_sanskrit(d["slok"]),
            "transliteration": clean_sanskrit(d["transliteration"]),
            "speaker": d.get("speaker", ""),
        }
        if n % 100 == 0:
            print(f"  Sanskrit: {n}/{len(names)}")
    return out


def clean_sanskrit(s: str) -> str:
    s = re.sub(r"\|\|\s*[\d\-।॥०-९]+\s*\|\|", "||", s)       # drop "||2-47||" verse numbers
    s = re.sub(r"॥\s*[\d०-९\-]+\s*॥", "॥", s)
    return "\n".join(line.strip() for line in s.strip().splitlines() if line.strip())


# ---------------- English (Besant 1922) ----------------

DEVANAGARI = re.compile(r"[ऀ-ॿ]")
VERSE_END = re.compile(r"\((\d+)(?:\s*[-–,]\s*(\d+))?\)\s*$")


def load_english() -> dict[tuple[int, int], str]:
    out = {}
    for ch in range(1, 19):
        page = urllib.parse.quote(BESANT_PAGE.format(n=ch))
        raw = json.loads(fetch(WIKI_API.format(page=page), f"besant/discourse_{ch}.json"))
        h = raw["parse"]["text"]["*"]
        h = re.sub(r"<style.*?</style>", "", h, flags=re.S)
        h = re.sub(r'<sup[^>]*class="reference".*?</sup>', "", h, flags=re.S)  # footnote markers
        text = html.unescape(re.sub(r"<[^>]+>", "\n", h)).replace("​", "")
        buf = []
        for line in (l.strip() for l in text.splitlines()):
            if not line:
                continue
            if DEVANAGARI.search(line):          # Sanskrit lines separate one verse from the next
                buf = []
                continue
            buf.append(line)
            m = VERSE_END.search(line)
            if m:
                eng = " ".join(buf)
                eng = VERSE_END.sub("", eng)
                eng = re.sub(r"\[\d+\]", "", eng)
                eng = re.sub(r"\s+", " ", eng).strip()
                first, last = int(m[1]), int(m[2] or m[1])
                for v in range(first, last + 1):  # Besant sometimes translates verses together
                    out[(ch, v)] = eng
                buf = []
        print(f"  English: discourse {ch}: {sum(1 for k in out if k[0] == ch)} verses")
    return out


# ---------------- build ----------------

def main():
    print("Sanskrit (vedicscriptures, verse text only)...")
    sanskrit = load_sanskrit()
    print("English (Besant 1922, Wikisource)...")
    english = load_english()

    rows, missing = [], []
    for (ch, v) in sorted(sanskrit):
        eng = english.get((ch, v), "")
        if not eng:
            missing.append(f"{ch}.{v}")
        rows.append({
            "id": f"BG {ch}.{v}",
            "text": "Bhagavad Gita",
            "chapter": ch,
            "verse": v,
            "speaker": sanskrit[(ch, v)]["speaker"],
            "sanskrit": sanskrit[(ch, v)]["sanskrit"],
            "transliteration": sanskrit[(ch, v)]["transliteration"],
            "english": eng,
            "english_source": "Annie Besant, The Bhagavad-Gita, 4th ed. (1922), public domain",
        })
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    print(f"\nWrote {len(rows)} verses to {OUT.relative_to(HERE.parent)}")
    print(f"Verses without English: {len(missing)}" + (f" ({', '.join(missing[:20])}{' ...' if len(missing) > 20 else ''})" if missing else ""))
    return 0 if len(missing) < 15 else 1


if __name__ == "__main__":
    sys.exit(main())
