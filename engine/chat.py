"""Sort viewer chat/comments into kinds so the show can handle a flood of messages.

Most messages are "hi" or emojis, not questions. Each kind gets its own treatment:

    greeting   "hi", "namaste", "hello from Pune"   -> batched welcome roll-call
    reaction   "😂😂", "🔥"                          -> emoji rain + drama meter
    vote       "team tiwari", "imran bhai op"         -> live poll bar
    question   real questions / comments              -> read on air (best ones only)
    topic      "next topic: chai vs coffee"           -> topic suggestions
    chatter    "lol", "nice"                          -> shown in the chat ticker only
    blocked    blocklist hits, links, flooding        -> never shown, never read

All rule-based (no LLM), so it stays fast however many messages arrive.
"""
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field

from .characters import Character
from .safety import Blocklist

GREETING_WORDS = {
    "hi", "hii", "hiii", "hy", "hey", "heyy", "hello", "helo", "hlo", "hallo", "namaste", "namaskar",
    "namastey", "pranam", "salaam", "salam", "gm", "gn", "morning", "evening", "yo", "sup",
    "नमस्ते", "नमस्कार", "प्रणाम", "हाय", "हेलो", "हैलो",
}
SUPPORT_WORDS = {
    "team", "op", "sahi", "right", "correct", "jeetega", "jeetegi", "jeet", "winner", "support",
    "saath", "best", "legend", "king", "queen", "boss", "+1", "zindabad", "❤️", "💯", "👑",
    "सही", "जीतेगा", "जीतेगी", "टीम", "ज़िंदाबाद", "जिंदाबाद", "साथ",
}
AGAINST_WORDS = {
    "galat", "wrong", "bekar", "bakwas", "haarega", "haaregi", "loser", "flop",
    "ग़लत", "गलत", "बेकार", "बकवास", "हारेगा", "हारेगी",
}
TOPIC_PREFIX = re.compile(r"^\s*(next topic|topic|agla topic|naya topic|debate on|अगला टॉपिक|टॉपिक|विषय)\s*[:\-–]?\s*", re.I)
LINK = re.compile(r"https?://|www\.|\.(com|in|net|xyz|ly)\b", re.I)
LETTER = re.compile(r"[A-Za-zऀ-ॿ]")
WORD = re.compile(r"[\wऀ-ॿ']+|[+]1")


def is_emoji(ch: str) -> bool:
    return unicodedata.category(ch) == "So" or 0x1F000 <= ord(ch) <= 0x1FAFF


def emojis_in(text: str) -> list[str]:
    return [ch for ch in text if is_emoji(ch)]


@dataclass
class ChatMessage:
    name: str
    text: str
    kind: str = "chatter"
    vote: str | None = None          # debater key this message backs
    score: int = 0                   # how good a question it is (higher = read first)
    emojis: list[str] = field(default_factory=list)

    def public(self) -> dict:
        d = {"name": self.name, "text": self.text, "kind": self.kind}
        if self.vote:
            d["vote"] = self.vote
        return d


class ChatState:
    def __init__(self, messages: list[ChatMessage]):
        self.messages = messages

    @property
    def visible(self) -> list[ChatMessage]:
        return [m for m in self.messages if m.kind != "blocked"]

    def greeters(self) -> list[str]:
        return list(dict.fromkeys(m.name for m in self.visible if m.kind == "greeting"))

    def emoji_counts(self) -> Counter:
        return Counter(e for m in self.visible for e in m.emojis)

    def votes(self) -> Counter:
        # One vote per person: their latest message wins.
        latest = {m.name: m.vote for m in self.visible if m.vote}
        return Counter(latest.values())

    def questions(self) -> list[ChatMessage]:
        """Best questions first, one per person."""
        seen, out = set(), []
        for m in sorted((m for m in self.visible if m.kind == "question"), key=lambda m: -m.score):
            if m.name not in seen:
                seen.add(m.name)
                out.append(m)
        return out

    def topics(self) -> list[str]:
        return [m.text for m in self.visible if m.kind == "topic"]

    def to_record(self) -> dict:
        return {
            "messages": [m.public() for m in self.visible],
            "greeters": self.greeters(),
            "emoji_counts": dict(self.emoji_counts().most_common()),
            "votes": dict(self.votes()),
            "topics": self.topics(),
            "blocked": sum(m.kind == "blocked" for m in self.messages),
        }


def clean_name(name: str) -> str:
    return re.sub(r"[_.@]+", " ", name).strip()[:40] or "Viewer"


def parse_line(line: str) -> tuple[str, str]:
    """'Name: text' -> (name, text); no colon -> ('Viewer', text)."""
    name, sep, text = line.partition(":")
    if sep and 0 < len(name.strip()) <= 40 and not LINK.search(name):
        return clean_name(name), text.strip()[:200]
    return "Viewer", line.strip()[:200]


def aliases_for(c: Character) -> set[str]:
    words = {c.key, c.name.lower(), *c.name.lower().split()} - {"ji", "bhai", "aunty"}
    return {w for w in words | {a.lower() for a in c.aliases} if len(w) >= 3}


def classify(name: str, text: str, debaters: list[Character], blocklist: Blocklist) -> ChatMessage:
    m = ChatMessage(name=name, text=text, emojis=emojis_in(text))
    lower = text.lower()
    words = WORD.findall(lower)

    if (blocklist.check(name) or blocklist.check(text) or LINK.search(text)
            or re.search(r"(.)\1{9,}", text) or not text.strip()):
        m.kind = "blocked"
        return m

    if TOPIC_PREFIX.match(text):
        m.kind, m.text = "topic", TOPIC_PREFIX.sub("", text).strip()
        return m

    if not LETTER.search(text):
        m.kind = "reaction" if m.emojis else "chatter"
        return m

    # Who does it mention, and is it for or against them?
    mentioned = [d for d in debaters if any(a in lower for a in aliases_for(d))]
    if len(mentioned) == 1:
        target = mentioned[0]
        other = next((d for d in debaters if d.key != target.key), None)
        if any(w in AGAINST_WORDS for w in words) and other:
            m.vote = other.key
        elif any(w in SUPPORT_WORDS for w in words) or any(e in SUPPORT_WORDS for e in m.emojis) or len(words) <= 3:
            m.vote = target.key

    if any(w in GREETING_WORDS for w in words) and len(words) <= 5 and "?" not in text:
        m.kind = "greeting"
    elif "?" in text or len(words) >= 6:
        m.kind = "question"
        m.score = 2 * ("?" in text) + 2 * bool(mentioned) + (5 <= len(words) <= 30)
    elif m.vote:
        m.kind = "vote"
    return m


def build_chat(lines: list[str], debaters: list[Character], blocklist: Blocklist) -> ChatState:
    return ChatState([classify(*parse_line(l), debaters, blocklist) for l in lines if l.strip()])
