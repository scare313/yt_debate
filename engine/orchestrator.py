"""Runs one debate: host intro -> opening -> rebuttals -> closing -> judge -> host verdict."""
import json
import random
import re
import time
from datetime import datetime

from .characters import Character
from .llm import LLM
from .storage import Scoreboard

LANGUAGE_RULES = {
    "hinglish": "Speak in Hinglish: Hindi written in Roman (English) letters mixed naturally with "
                "English, the way young Indians chat on WhatsApp. Never use Devanagari script.",
    "english": "Speak in simple, punchy English. An occasional Indian expression is fine.",
    "hindi": "Speak in simple spoken Hindi using only Devanagari script. Your words will be read aloud "
             "by a Hindi voice, so write English words, brand names, abbreviations and all numbers in "
             "Devanagari too (for example टीवी not TV, दस not 10), never in English letters or digits.",
}

ROUND_TASKS = {
    "opening": "Give your opening statement: your single strongest argument, told through one funny, "
               "specific moment from your own life.",
    "rebuttal": "Make fun of your opponent's last point first, then add one NEW argument or story "
                "you have not used yet.",
    "closing": "Give your closing statement: one last funny jab at your opponent, then say why you won.",
}

TURN_RULES = (
    "Stay on the exact topic. Every sentence must be about the topic itself, not about other subjects. "
    "Talk like a real person in a heated but funny argument, not like a speech. "
    "Never repeat a point, joke or phrase that was already said in this debate."
)

# Topic words that make a debate political; only then do characters' political views come in.
POLITICAL_HINTS = (
    "सरकार", "चुनाव", "नेता", "पार्टी", "जीएसटी", "टैक्स", "पेंशन", "बजट", "संविधान", "मंत्री",
    "वोट", "विपक्ष", "महंगाई", "government", "election", "politic", "party", "gst", "tax",
    "pension", "budget", "vote", "minister", "sarkar", "chunav",
)

CONTENT_RULES = (
    "Be funny and sharp, but keep it clean: no slurs, no hate about religion, caste, gender, "
    "region or nationality, no sexual content, and never attack real private people. "
    "Do not name or quote real politicians or other real public figures (other than the one you play); "
    "say 'the government' or 'the opposition' instead."
)

# Latin-letter words that the speech converter can't fix (acronyms like GST are fine).
LATIN_WORD = re.compile(r"\b(?![A-Z]{2,6}\b)[A-Za-z]{2,}\b")


class Debate:
    def __init__(self, llm: LLM, host: Character, debaters: list[Character],
                 settings: dict, scoreboard: Scoreboard, printer, voice=None):
        self.llm = llm
        self.host = host
        self.debaters = debaters
        self.s = settings
        self.scoreboard = scoreboard
        self.printer = printer  # object with .header(char, label) / .token(text) / .end(seconds) / .info(text)
        self.voice = voice      # VoiceSession, or None for text-only
        self.record: dict = {}

    # ---------- public ----------

    def run(self, topic: str, for_side: str | None = None) -> dict:
        if for_side:
            self.sides = {d.key: "FOR" if d.key == for_side else "AGAINST" for d in self.debaters}
        else:
            sides = ["FOR", "AGAINST"]
            random.shuffle(sides)
            self.sides = {d.key: side for d, side in zip(self.debaters, sides)}
        # The FOR side always opens.
        order = sorted(self.debaters, key=lambda d: self.sides[d.key] != "FOR")

        self.record = {
            "topic": topic,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "model": self.llm.model,
            "language": self.s["language"],
            "sides": self.sides,
            "status": "running",
            "turns": [],
            "verdict": None,
        }
        started = time.time()

        self._host_intro(topic, order)

        rounds = ["opening"] + ["rebuttal"] * self.s["rebuttal_rounds"] + ["closing"]
        for rnd in rounds:
            for speaker in order:
                self._debater_turn(topic, speaker, rnd)

        verdict = self._judge(topic)
        self.record["verdict"] = verdict
        self._host_verdict(topic, verdict)

        winner = verdict["winner"] if verdict["winner"] in self.sides else None
        self.scoreboard.record([d.key for d in self.debaters], winner)
        self.record["scoreboard_after"] = {d.key: self.scoreboard.get(d.key) for d in self.debaters}
        self.record["status"] = "finished"
        self.record["total_seconds"] = round(time.time() - started, 1)
        return self.record

    # ---------- turns ----------

    def _host_intro(self, topic: str, order: list[Character]):
        panel = "\n".join(f"- {d.name} ({d.title or 'panelist'}) argues {self.sides[d.key]}" for d in order)
        user = (
            f"Tonight's topic: \"{topic}\"\n"
            f"Panelists:\n{panel}\n\n"
            f"Open the show: hype the topic dramatically, introduce both panelists and which side "
            f"each one is on. Max 45 words."
        )
        self._speak(self.host, "intro", self._system_for(self.host, extra=""), user, max_words=45)

    def _debater_turn(self, topic: str, speaker: Character, rnd: str):
        side = self.sides[speaker.key]
        opponent = next(d for d in self.debaters if d.key != speaker.key)
        extra = (
            f"You are in a debate against {opponent.name} ({opponent.title or 'panelist'}). "
            f"Topic: \"{topic}\".\n"
            f"You argue {side} the topic. Never switch sides and never agree with {opponent.name}."
        )
        if speaker.politics and is_political(topic):
            extra += f"\nYour political views (this topic is political): {speaker.politics}"
        system = self._system_for(speaker, extra=extra)
        history = self._history_text()
        closing_line = (f"\nIf it fits naturally, you may end with your catchphrase: \"{speaker.catchphrase}\""
                        if rnd == "closing" and speaker.catchphrase else "")
        user = (
            (f"Debate so far:\n{history}\n\n" if history else "You speak first.\n\n")
            + f"Topic reminder: \"{topic}\" (you are {side} it)\n"
            f"Round: {rnd.upper()}. {ROUND_TASKS[rnd]}\n{TURN_RULES}{closing_line}\n"
            f"Reply with ONLY your spoken words, max {self.s['max_words_per_turn']} words, 2-3 sentences."
        )
        self._speak(speaker, f"{side} · {rnd}", system, user, max_words=self.s["max_words_per_turn"], rnd=rnd)

    def _judge(self, topic: str) -> dict:
        keys = [d.key for d in self.debaters]
        names = ", ".join(f"{d.key} = {d.name} ({self.sides[d.key]})" for d in self.debaters)
        transcript = "\n".join(f"{t['name']}: {t['text']}" for t in self.record["turns"] if t["speaker"] in keys)
        system = (
            "You are an impartial judge for a comedy debate show. Judge on strength of arguments, "
            "quality of rebuttals and entertainment value. Ignore which side you personally agree with."
        )
        user = (
            f"Topic: \"{topic}\"\nDebaters: {names}\n\nTranscript:\n{transcript}\n\n"
            f"Reply with JSON only, exactly this shape:\n"
            f'{{"winner": "{keys[0]}" or "{keys[1]}" or "draw", "score": "7-5", "reason": "one short sentence"}}'
        )
        (self.voice or self.printer).info("⚖️  Judge is deciding...")
        raw = self.llm.chat(system, user, temperature=self.s["judge_temperature"], max_tokens=150, json_mode=True)
        return parse_verdict(raw, keys)

    def _host_verdict(self, topic: str, verdict: dict):
        names = {d.key: d.name for d in self.debaters}
        if verdict["winner"] in names:
            result = f"Winner: {names[verdict['winner']]} ({verdict['score']}). Reason: {verdict['reason']}"
        else:
            result = f"It's a draw ({verdict['score']}). Reason: {verdict['reason']}"
        user = (
            f"The debate on \"{topic}\" is over. Judge's decision: {result}\n"
            f"Announce the result dramatically, roast the loser lightly, and sign off. Max 40 words."
        )
        self._speak(self.host, "verdict", self._system_for(self.host, extra=""), user, max_words=40)

    # ---------- helpers ----------

    def _system_for(self, char: Character, extra: str) -> str:
        parts = [
            char.persona,
            extra,
            LANGUAGE_RULES[self.s["language"]],
            CONTENT_RULES,
            "Stay fully in character. No stage directions, no emojis, no hashtags, "
            "and do not start with your own name.",
        ]
        return "\n\n".join(p for p in parts if p)

    def _history_text(self) -> str:
        turns = self.record["turns"][-self.s["history_turns"]:]
        return "\n".join(f"{t['name']}: {t['text']}" for t in turns)

    def _speak(self, char: Character, label: str, system: str, user: str, max_words: int, rnd: str | None = None):
        # Text-only: stream tokens to the terminal. With voice, the VoiceSession prints
        # each turn when its audio starts playing instead.
        if not self.voice:
            self.printer.header(char, label)
        t0 = time.time()
        text = self.llm.chat(
            system, user,
            temperature=self.s["temperature"],
            max_tokens=int(max_words * 4),  # Hinglish/Devanagari tokenize poorly; leave headroom
            on_token=None if self.voice else self.printer.token,
        )
        # Small models often prefix their own name ("**Bunty:** ..."); drop it.
        text = re.sub(rf"^[\W_]*{re.escape(char.name)}[*_\s]*:[*_\s]*", "", text, flags=re.IGNORECASE).strip()
        raw_text = None
        if self.s["language"] == "hindi" and len(LATIN_WORD.findall(text)) >= 2:
            raw_text, text = text, self._to_devanagari(text)
        secs = round(time.time() - t0, 1)
        turn = {
            "speaker": char.key,
            "name": char.name,
            "round": rnd or label,
            "side": self.sides.get(char.key),
            "text": text,
            "gen_seconds": secs,
        }
        if raw_text:
            turn["raw_text"] = raw_text  # what the LLM wrote before the script fix
        self.record["turns"].append(turn)
        if self.voice:
            self.voice.turn(char, label, text, turn)
        else:
            self.printer.end(secs)


    def _to_devanagari(self, text: str) -> str:
        """Small models slip into Hinglish in English letters; Hindi voices can't read that."""
        fixed = self.llm.chat(
            "You convert text to Devanagari script. Keep the exact same words, meaning and tone. "
            "Transliterate every Hindi or English word written in English letters into Devanagari "
            "(e.g. 'Vikas mein toh jaago' -> 'विकास में तो जागो', 'business' -> 'बिज़नेस'). "
            "Output only the converted text, nothing else.",
            text, temperature=0.1, max_tokens=len(text) * 2,
        )
        return fixed or text


def is_political(topic: str) -> bool:
    t = topic.lower()
    return any(h in t for h in POLITICAL_HINTS)


def parse_verdict(raw: str, keys: list[str]) -> dict:
    """Small models don't always return clean JSON; recover what we can."""
    data = {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(0))
            except json.JSONDecodeError:
                pass

    winner = str(data.get("winner", "")).strip().lower()
    if winner not in keys and winner != "draw":
        mentioned = [k for k in keys if k in raw.lower()]
        winner = mentioned[0] if len(mentioned) == 1 else "draw"

    return {
        "winner": winner,
        "score": str(data.get("score", "?-?")),
        "reason": str(data.get("reason", "")).strip() or "The judge kept their reasons to themselves.",
        "raw": raw,
    }
