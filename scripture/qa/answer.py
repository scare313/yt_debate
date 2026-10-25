"""Turn a viewer's question into a grounded answer script.

    question -> safety screen -> search the library -> the model picks verse IDs from the
    candidates and writes only the explanation -> checker -> script

The verse text and any purport quote on screen always come from the library, never from the
model, so a misquoted or invented verse can't reach a video.
"""
import json
import re
from dataclasses import dataclass, field

# Word caps that keep a Short at roughly 45-60 seconds (the verse itself is never cut).
LIMITS = {"opening": 15, "explanation": 40, "practice": 25, "reflection": 12}

from .library import Hit, Library

# ---------------- safety screen ----------------

SELF_HARM = re.compile(
    r"\b(suicid\w*|kill (my ?self|me)|end (my|this) life|self[- ]?harm|cut(ting)? myself|"
    r"(want|wish) to die|don'?t want to (live|be alive)|no reason to live|better off dead)\b", re.I)
SECTARIAN = re.compile(
    r"\b(which|what) religion is (better|best|true|right)|\b(better|superior) than (islam|christianity|"
    r"hinduism|sikhism|buddhism|jainism)|\b(hindu|muslim|christian|sikh) vs\b|\bcaste\b.*\b(superior|lower|better)\b", re.I)
PROFESSIONAL = re.compile(
    r"\b(medicine|medication|dosage|diagnos\w+|cancer|lawsuit|divorce papers|legal case|invest\w*|stock|crypto|"
    r"loan|tax)\b", re.I)

CRISIS_MESSAGE = (
    "If you're going through something this painful, please talk to someone right now. In India you can "
    "call Tele-MANAS on 14416 or 1-800-891-4416, free and 24x7. You are not alone, and your life matters."
)


@dataclass
class Screen:
    ok: bool
    reason: str = ""
    message: str = ""
    note: str = ""   # extra instruction for the writer (e.g. "not professional advice")


def screen(question: str) -> Screen:
    if SELF_HARM.search(question):
        return Screen(False, "crisis", CRISIS_MESSAGE)
    if SECTARIAN.search(question):
        return Screen(False, "sectarian",
                      "This show doesn't compare or rank religions or communities. Every sincere path deserves respect.")
    if PROFESSIONAL.search(question):
        return Screen(True, "professional", note=(
            "This question touches a medical, legal or financial decision. Offer only a spiritual "
            "perspective and clearly say they should consult a qualified professional for the decision itself."))
    return Screen(True)


# ---------------- writer ----------------

@dataclass
class Answer:
    question: str
    asker: str
    verses: list = field(default_factory=list)          # verse IDs chosen (validated)
    opening: str = ""
    explanation: str = ""
    purport_quote: str = ""                             # exact sentence from the purport, or ""
    quote_verse: str = ""
    practice: str = ""
    reflection: str = ""
    candidates: list = field(default_factory=list)
    screen: str = ""
    attempts: int = 0


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().strip('"“”‘’\'').lower()


def _quoted_runs(text: str) -> list[str]:
    return [q for q in re.findall(r"[\"“‘']([^\"”’']{25,})[\"”’']", text)]


NO_MATCH = Screen(False, "no_match", "The library has no verse that clearly answers this question.")


def write_answer(llm, lib: Library, persona: str, question: str, asker: str = "",
                 k: int = 8, temperature: float = 0.6, min_score: float = 0.0, max_verses: int = 1) -> Answer | Screen:
    sc = screen(question)
    if not sc.ok:
        return sc

    hits: list[Hit] = lib.search(question, k=k)
    if not hits or hits[0].score < min_score:
        return NO_MATCH                       # better no video than a stretched verse
    listing = "\n\n".join(
        f"[{h.verse.id}] SPOKEN BY: {h.verse.speaker or 'unknown'}\nTRANSLATION: {h.verse.translation}\n"
        f"PURPORT EXCERPT: {h.passage if h.passage != h.verse.translation else (h.verse.purport[0] if h.verse.purport else '')}"
        for h in hits)
    ids = [h.verse.id for h in hits]
    name_line = f'The viewer\'s name is "{asker}". Greet them by name in the opening.' if asker else ""

    system = (
        f"{persona}\n\n"
        "Rules:\n"
        f"- Answer ONLY from the candidate verses given. Pick the {'single most relevant verse ID' if max_verses == 1 else f'1 to {max_verses} most relevant verse IDs'} from the list.\n"
        "- This is a 45-60 second YouTube Short: be brief and warm, every word must earn its place.\n"
        "- Never write the verse yourself and never invent quotations; the verse is shown separately.\n"
        "- purport_quote must be ONE sentence copied exactly, word for word, from a PURPORT EXCERPT below, "
        "or an empty string.\n"
        "- Speak as the narrator. Never speak as Krishna or as Srila Prabhupada.\n"
        "- Each candidate says who speaks it. Attribute correctly: only say 'Krishna says' or 'Krishna teaches' "
        "for verses SPOKEN BY Krishna. Arjuna's, Sanjaya's or Dhritarashtra's words are their questions, doubts or "
        "narration, never Krishna's instruction. For advice, strongly prefer verses spoken by Krishna.\n"
        "- Explain ONLY what the translation and purport excerpt actually say. Never stretch a verse to fit "
        "the question or claim it says something it doesn't. Read who is speaking and the context: a verse "
        "describing a character's boast or confusion is not advice. Prefer verses where Krishna teaches.\n"
        "- Be practical and kind. No fear-mongering, no judgement.\n"
        + (f"- {sc.note}\n" if sc.note else "")
    )
    user = (
        f"Viewer's question: \"{question}\"\n{name_line}\n\nCandidate verses:\n\n{listing}\n\n"
        "Reply with JSON only:\n"
        "{\"verses\": [\"<verse ID from the list>\"], "
        f"\"opening\": \"1 warm sentence acknowledging the question, max {LIMITS['opening']} words\", "
        f"\"explanation\": \"what the verse means for this question, max {LIMITS['explanation']} words\", "
        "\"purport_quote\": \"one exact short sentence from a purport excerpt, or empty\", "
        f"\"practice\": \"one concrete thing to try today, max {LIMITS['practice']} words\", "
        f"\"reflection\": \"1 short question for the viewer, max {LIMITS['reflection']} words\"}}"
    )

    ans = Answer(question=question, asker=asker, candidates=ids, screen=sc.reason)
    for attempt in range(1, 4):
        ans.attempts = attempt
        raw = llm.chat(system, user, temperature=temperature, max_tokens=500, json_mode=True)
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            m = re.search(r"\{.*\}", raw or "", re.S)
            try:
                data = json.loads(m.group(0)) if m else {}
            except json.JSONDecodeError:
                data = {}
        problems = _check(data, ids, lib)
        if not problems:
            break
        user += f"\n\nYour previous answer had problems: {'; '.join(problems)}. Fix them and reply with JSON only."
    else:
        raise ValueError(f"Couldn't get a grounded answer after 3 tries: {'; '.join(problems)}")

    chosen = [v for v in data["verses"] if v in ids][:max_verses]
    ans.verses = chosen
    for f in ("opening", "explanation", "practice", "reflection"):
        setattr(ans, f, _cap(re.sub(r"[*_`#]", "", str(data.get(f, ""))).strip(), LIMITS[f]))
    q = str(data.get("purport_quote") or "").strip()
    if q:
        ans.purport_quote, ans.quote_verse = _find_quote(q, [lib.by_id[v] for v in chosen])
    return ans


def _cap(text: str, limit: int) -> str:
    """Models overrun word limits; cut at the last sentence end that fits (a little slack allowed)."""
    words = text.split()
    if len(words) <= limit + 3:
        return text
    cut = " ".join(words[: limit + 3])
    end = max(cut.rfind(p) for p in ".!?")
    return cut[: end + 1] if end > len(cut) // 3 else " ".join(words[:limit]).rstrip(",;:") + "."


def _check(data: dict, ids: list[str], lib: Library) -> list[str]:
    problems = []
    verses = data.get("verses") if isinstance(data, dict) else None
    if not isinstance(verses, list) or not any(v in ids for v in verses):
        problems.append(f"'verses' must contain IDs from this list only: {', '.join(ids)}")
    for f in ("opening", "explanation", "practice"):
        if not str((data or {}).get(f, "")).strip():
            problems.append(f"'{f}' is empty")
    # No invented quotations: any long quoted run must exist in a chosen verse's text.
    chosen = [lib.by_id[v] for v in (verses or []) if v in lib.by_id]
    corpus = _norm(" ".join(v.translation + " " + " ".join(v.purport) for v in chosen))
    for f in ("opening", "explanation", "practice", "reflection"):
        for q in _quoted_runs(str((data or {}).get(f, ""))):
            if _norm(q) not in corpus:
                problems.append(f"'{f}' contains a quotation that isn't in the verse or purport: \"{q[:60]}\"")
    return problems


def _find_quote(q: str, verses) -> tuple[str, str]:
    """Keep the purport quote only if it really is in a chosen purport; return the library's exact text."""
    nq = _norm(q)
    for v in verses:
        for para in v.purport:
            for sent in re.split(r"(?<=[.!?])\s+", para):
                if nq and (nq == _norm(sent) or (len(nq) > 40 and nq in _norm(sent))):
                    return sent.strip(), v.id
    return "", ""
