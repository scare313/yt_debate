"""Verse library + hybrid search (meaning via embeddings, plus keywords via BM25).

Each verse is indexed as several "units": its translation, and its purport split into
short passages. A search scores every unit, then keeps the best unit per verse, so a
question can match either the verse itself or a sentence deep in its purport.
"""
import hashlib
import json
import math
import re
import unicodedata
import urllib.request
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
LIBRARY_DIR = ROOT / "library"
CACHE = ROOT / ".cache"
OLLAMA = "http://localhost:11434/api/embed"
EMBED_MODEL = "nomic-embed-text"
PASSAGE_WORDS = 120


@dataclass
class Verse:
    id: str
    book: str
    devanagari: str
    transliteration: str
    translation: str
    purport: list[str]
    url: str = ""
    speaker: str = ""   # who says this verse (Krishna, Arjuna, Sanjaya, Dhritarashtra)


@dataclass
class Hit:
    verse: Verse
    score: float
    passage: str        # the unit that matched best (translation or a purport passage)


def fold(text: str) -> str:
    """Lowercase and drop diacritics, so 'Kṛṣṇa' matches 'krishna'-ish searches better."""
    t = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in t if not unicodedata.combining(ch))


TOKEN = re.compile(r"[a-z]{2,}")
STOP = set("the and of to in a is that for it as with be by on not this are or his he you your one who "
           "from at which but they all have was were has so if one's their them there what when can will "
           "into also its our we i my me do does than then such these those".split())


def tokens(text: str) -> list[str]:
    return [t for t in TOKEN.findall(fold(text)) if t not in STOP]


def embed(texts: list[str], prefix: str) -> np.ndarray:
    out = []
    for i in range(0, len(texts), 64):
        body = json.dumps({"model": EMBED_MODEL, "input": [prefix + t for t in texts[i:i + 64]]}).encode()
        req = urllib.request.Request(OLLAMA, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=300) as r:
            out.extend(json.loads(r.read())["embeddings"])
    v = np.asarray(out, dtype=np.float32)
    return v / np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-9)


class Library:
    def __init__(self, path: Path | None = None):
        self.path = path or self._default_path()
        self.verses: list[Verse] = []
        for line in self.path.read_text().splitlines():
            r = json.loads(line)
            self.verses.append(Verse(
                id=r["id"], book=r.get("book") or r.get("text", ""),
                devanagari=r.get("devanagari") or r.get("sanskrit", ""),
                transliteration=r.get("transliteration", ""),
                translation=r.get("translation") or r.get("english", ""),
                purport=r.get("purport") or [], url=r.get("url", ""),
            ))
        self.by_id = {v.id: v for v in self.verses}
        self._tag_speakers()
        self._build_units()
        self._load_or_build_index()

    SPEAKERS = {"śrī-bhagavān": "Krishna", "bhagavān": "Krishna", "arjuna": "Arjuna",
                "sañjaya": "Sanjaya", "dhṛtarāṣṭra": "Dhritarashtra"}

    def _tag_speakers(self):
        """In the Gita a new speaker's first verse starts with "<name> uvāca" ("<name> said");
        everything after is theirs until the next one."""
        current = ""
        for v in self.verses:
            first = (v.transliteration.splitlines() or [""])[0].strip().lower()
            m = re.match(r"^([^\s]+)\s+uvāca", first)
            if m:
                current = self.SPEAKERS.get(m.group(1), m.group(1).capitalize())
            v.speaker = current

    @staticmethod
    def _default_path() -> Path:
        """The biggest library available: the finished download, or the partial one while it runs."""
        candidates = [p for p in (LIBRARY_DIR / "vedabase" / "bg.jsonl", LIBRARY_DIR / "vedabase" / "bg.partial.jsonl",
                                  LIBRARY_DIR / "gita.jsonl") if p.exists()]
        if not candidates:
            raise FileNotFoundError("No verse library yet. Run scripture/tools/build_vedabase.py --book bg")
        return max(candidates, key=lambda p: sum(1 for _ in p.open()))

    def _build_units(self):
        self.units: list[tuple[int, str]] = []          # (verse index, text)
        for i, v in enumerate(self.verses):
            if v.translation:
                self.units.append((i, v.translation))
            words = " ".join(v.purport).split()
            for s in range(0, len(words), PASSAGE_WORDS):
                chunk = " ".join(words[s:s + PASSAGE_WORDS + 20])   # small overlap
                if len(chunk.split()) >= 15:
                    self.units.append((i, chunk))
        # BM25 statistics
        self.unit_tokens = [Counter(tokens(t)) for _, t in self.units]
        self.avg_len = sum(sum(c.values()) for c in self.unit_tokens) / max(len(self.units), 1)
        df = Counter(t for c in self.unit_tokens for t in c)
        n = len(self.units)
        self.idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}

    def _load_or_build_index(self):
        digest = hashlib.sha1(self.path.read_bytes() + EMBED_MODEL.encode()).hexdigest()[:12]
        cache = CACHE / f"index_{self.path.stem}_{digest}.npy"
        if cache.exists():
            self.vectors = np.load(cache)
        else:
            print(f"Indexing {len(self.units)} passages from {len(self.verses)} verses (one time)...")
            self.vectors = embed([t for _, t in self.units], "search_document: ")
            CACHE.mkdir(parents=True, exist_ok=True)
            np.save(cache, self.vectors)

    def _bm25(self, q: list[str]) -> np.ndarray:
        k1, b = 1.4, 0.75
        scores = np.zeros(len(self.units), dtype=np.float32)
        for j, c in enumerate(self.unit_tokens):
            length = sum(c.values()) or 1
            s = 0.0
            for t in q:
                f = c.get(t)
                if f:
                    s += self.idf.get(t, 0) * f * (k1 + 1) / (f + k1 * (1 - b + b * length / self.avg_len))
            scores[j] = s
        return scores

    def search(self, question: str, k: int = 8) -> list[Hit]:
        sem = self.vectors @ embed([question], "search_query: ")[0]
        kw = self._bm25(tokens(question))
        if kw.max() > 0:
            kw = kw / kw.max()
        score = 0.75 * sem + 0.25 * kw
        # Advice comes from Krishna's teaching; other speakers' verses (laments, questions,
        # narration) stay findable but rank a little lower.
        weight = np.array([1.0 if self.verses[vi].speaker in ("Krishna", "") else 0.85 for vi, _ in self.units],
                          dtype=np.float32)
        score = score * weight
        best: dict[int, tuple[float, int]] = {}
        for j in np.argsort(-score)[: k * 12]:
            vi = self.units[j][0]
            if vi not in best or score[j] > best[vi][0]:
                best[vi] = (float(score[j]), int(j))
        ranked = sorted(best.items(), key=lambda kv: -kv[1][0])[:k]
        return [Hit(self.verses[vi], s, self.units[j][1]) for vi, (s, j) in ranked]
