"""Runs one debate in one of two formats:

news    (default) the anchor runs the show: opening questions, cross-questions, panelists
        cutting in, "chat breaks" for viewers (welcome roll-call, a question read on air,
        reacting to the chat's mood and poll), final lines, verdict.
classic fixed rounds: host intro -> opening -> rebuttals -> closing -> verdict.

Both end with the judge (two blind passes, see _judge) and the anchor's verdict.
"""
import json
import random
import re
import time
from datetime import datetime

from .characters import Character
from .chat import ChatState
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

# classic format
ROUND_TASKS = {
    "opening": "Give your opening statement: your single strongest argument, told through one funny, "
               "specific moment from your own life.",
    "rebuttal": "Make fun of your opponent's last point first, then add one NEW argument or story "
                "you have not used yet.",
    "closing": "Give your closing statement: one last funny jab at your opponent, then say why you won.",
}

# news format: what a panelist is asked to do on each kind of turn
PANELIST_TASKS = {
    "answer": "Answer the anchor's question directly in your first sentence, then back it up with one "
              "funny, specific moment from your own life.",
    "cutin": "You can't stay quiet! Interrupt {other} with ONE short, heated sentence (max 15 words) "
             "attacking what they just said.",
    "viewer": "A viewer named {viewer} asked you something. Answer {viewer} directly, addressing them "
              "by name, and defend your side.",
    "closing": "Final statement: one last funny jab at {other}, then one line on why you won.",
}

TURN_RULES = (
    "Stay on the exact topic. Every sentence must be about the topic itself, not about other subjects. "
    "Talk like a real person in a heated but funny argument, not like a speech. "
    "Never repeat a point, joke or phrase that was already said in this debate."
)

CONTENT_RULES = (
    "Be funny and sharp, but keep it clean: no slurs, no hate about religion, caste, gender, "
    "region or nationality, no sexual content, and never attack real private people. "
    "Do not name or quote real politicians or other real public figures (other than the one you play); "
    "say 'the government' or 'the opposition' instead."
)

# Topic words that make a debate political; only then do characters' political views come in.
POLITICAL_HINTS = (
    "सरकार", "चुनाव", "नेता", "पार्टी", "जीएसटी", "टैक्स", "पेंशन", "बजट", "संविधान", "मंत्री",
    "वोट", "विपक्ष", "महंगाई", "government", "election", "politic", "party", "gst", "tax",
    "pension", "budget", "vote", "minister", "sarkar", "chunav",
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

    def run(self, topic: str, for_side: str | None = None, chat: ChatState | None = None) -> dict:
        if for_side:
            self.sides = {d.key: "FOR" if d.key == for_side else "AGAINST" for d in self.debaters}
        else:
            sides = ["FOR", "AGAINST"]
            random.shuffle(sides)
            self.sides = {d.key: side for d, side in zip(self.debaters, sides)}
        # The FOR side always goes first.
        order = sorted(self.debaters, key=lambda d: self.sides[d.key] != "FOR")
        fmt = self.s.get("format", "news")

        self.record = {
            "topic": topic,
            "format": fmt,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "model": self.llm.model,
            "language": self.s["language"],
            "sides": self.sides,
            "panel": {d.key: {"name": d.name, "title": d.title} for d in [self.host, *self.debaters]},
            "comments": [],          # questions actually read on air (spotlight + shoutouts)
            "chat": chat.to_record() if chat else None,
            "status": "running",
            "turns": [],
            "verdict": None,
        }
        started = time.time()

        self._host_intro(topic, order)
        if fmt == "classic":
            self._run_classic(topic, order)
        else:
            self._run_news(topic, order, chat or ChatState([]))

        verdict = self._judge(topic)
        self.record["verdict"] = verdict
        self._host_verdict(topic, verdict)

        winner = verdict["winner"] if verdict["winner"] in self.sides else None
        self.scoreboard.record([d.key for d in self.debaters], winner)
        self.record["scoreboard_after"] = {d.key: self.scoreboard.get(d.key) for d in self.debaters}
        self.record["status"] = "finished"
        self.record["total_seconds"] = round(time.time() - started, 1)
        return self.record

    # ---------- formats ----------

    def _run_classic(self, topic: str, order: list[Character]):
        rounds = ["opening"] + ["rebuttal"] * self.s["rebuttal_rounds"] + ["closing"]
        for rnd in rounds:
            for speaker in order:
                self._debater_turn(topic, speaker, rnd)

    def _run_news(self, topic: str, order: list[Character], chat: ChatState):
        a, b = order
        other = {a.key: b, b.key: a}

        # Opening question to each side.
        self._anchor(topic, f"Ask {a.name} a sharp, provocative opening question about the topic. "
                            f"Address {a.name} by name.", to=a)
        self._panelist(topic, a, "answer")
        self._anchor(topic, f"Turn to {b.name}. React to what {a.name} just said in a few words, "
                            f"then ask {b.name} to respond.", to=b)
        self._panelist(topic, b, "answer")

        # Cross-questioning, with interruptions, and a chat break after each exchange.
        exchanges = max(1, int(self.s.get("exchanges", 3)))
        breaks = self._plan_chat_breaks(chat)
        slots = {}
        for j, brk in enumerate(breaks):  # spread breaks over the exchanges
            slots.setdefault(min(exchanges - 1, j * exchanges // max(len(breaks), 1)), []).append(brk)

        target, interrupted_by = a, None
        for i in range(exchanges):
            opp = other[target.key]
            task = (f"Ask {target.name} a tough follow-up question: challenge their weakest point so far, "
                    f"or put {opp.name}'s last point to them. Address {target.name} by name.")
            if interrupted_by:
                task = (f"{interrupted_by.name} just interrupted rudely. Cut them off dramatically "
                        f"(\"एक मिनट! एक मिनट!\"), then " + task[0].lower() + task[1:])
            self._anchor(topic, task, to=target)
            self._panelist(topic, target, "answer")

            interrupted_by = None
            if random.random() < float(self.s.get("cutin_chance", 0.35)):
                self._panelist(topic, opp, "cutin", max_words=15)
                interrupted_by = opp

            for kind, payload in slots.get(i, []):
                self._chat_break(topic, kind, payload, last=target, back_to=opp)
                interrupted_by = None
            target = opp

        # Final lines.
        self._anchor(topic, f"Time is almost up. Ask both panelists for one final line, starting with {a.name}.",
                     to=a)
        self._panelist(topic, a, "closing", max_words=40)
        self._panelist(topic, b, "closing", max_words=40)

    # ---------- chat breaks ----------

    def _plan_chat_breaks(self, chat: ChatState) -> list[tuple[str, object]]:
        """Welcome first (being named makes people stay), then questions with a mood check between."""
        greeters = chat.greeters()
        questions = [{"name": q.name, "text": q.text} for q in chat.questions()[: int(self.s.get("max_questions", 2))]]
        lively = sum(chat.emoji_counts().values()) >= 5 or sum(chat.votes().values()) >= 3
        plan = [("rollcall", greeters)] if greeters else []
        for n, q in enumerate(questions):
            plan.append(("question", q))
            if n == 0 and lively:
                plan.append(("mood", chat))
        if lively and not any(k == "mood" for k, _ in plan):
            plan.append(("mood", chat))
        return plan[: int(self.s.get("max_chat_breaks", 3))]

    def _chat_break(self, topic: str, kind: str, payload, last: Character, back_to: Character):
        if kind == "rollcall":
            n = int(self.s.get("rollcall_names", 5))
            names, more = payload[:n], max(0, len(payload) - n)
            others = f" and {more} others" if more else ""
            self._anchor(topic, (
                f"Quick chat break! Warmly welcome these viewers from the chat by name: {', '.join(names)}{others}. "
                f"One funny line to make them feel part of the show, then turn back to {back_to.name}."),
                to=back_to, max_words=40, kind="rollcall", extra={"names": names, "more": more})

        elif kind == "question":
            c = payload
            to = self._comment_target(c, last=last)
            self._anchor(topic, (
                f"Read a viewer comment on air with full drama. Viewer name: \"{c['name']}\". "
                f"Comment: \"{c['text']}\". Say the viewer's name, read the comment, then ask "
                f"{to.name} to answer the viewer."),
                to=to, max_words=45, comment=c)
            self._panelist(topic, to, "viewer", viewer=c["name"], comment=c)
            self.record["comments"].append(c)

        elif kind == "mood":
            chat: ChatState = payload
            emojis = ", ".join(f"{e} x{n}" for e, n in chat.emoji_counts().most_common(3))
            names = {d.key: d.name for d in self.debaters}
            votes = chat.votes()
            poll = ", ".join(f"{names[k]} {votes.get(k, 0)} votes" for k in names) if votes else ""
            self._anchor(topic, (
                f"Quick look at the chat! Reactions: {emojis or 'quiet'}."
                + (f" Chat poll: {poll}." if poll else "")
                + f" React to the chat's mood in one dramatic, funny line"
                + (", say who the chat is backing" if poll else "")
                + f", then throw it back to {back_to.name}."),
                to=back_to, max_words=40, kind="mood",
                extra={"emojis": dict(chat.emoji_counts().most_common(3)), "votes": dict(votes)})

    def _comment_target(self, comment: dict, last: Character) -> Character:
        """The panelist the comment mentions, else whoever didn't just answer."""
        text = comment["text"].lower()
        for d in self.debaters:
            names = {d.key, d.name.lower(), d.name.split()[0].lower()}
            if any(n and n in text for n in names):
                return d
        return next(d for d in self.debaters if d.key != last.key)

    # ---------- turns ----------

    def _host_intro(self, topic: str, order: list[Character]):
        panel = "\n".join(f"- {d.name} ({d.title or 'panelist'}) argues {self.sides[d.key]}" for d in order)
        user = (
            f"Tonight's topic: \"{topic}\"\n"
            f"Panelists:\n{panel}\n\n"
            f"Open the show: hype the topic dramatically, introduce both panelists and which side "
            f"each one is on, and tell viewers to post their questions in the comments. Max 50 words."
        )
        self._speak(self.host, "intro", self._system_for(self.host, extra=""), user, max_words=50, kind="intro")

    def _anchor(self, topic: str, task: str, to: Character, max_words: int = 35, comment: dict | None = None,
                kind: str | None = None, extra: dict | None = None):
        panel = "; ".join(f"{d.name} ({d.title or 'panelist'}) argues {self.sides[d.key]}" for d in self.debaters)
        system = self._system_for(self.host, extra=(
            f"You are moderating a live debate on \"{topic}\". Panelists: {panel}.\n"
            f"Keep every turn short, punchy and dramatic, and speak directly to the person you address. "
            f"Never answer the question yourself and never take sides."
        ))
        history = self._history_text()
        user = (
            (f"Debate so far:\n{history}\n\n" if history else "")
            + f"Your task now: {task}\n"
            f"Reply with ONLY your spoken words, max {max_words} words."
        )
        extra = {"to": to.key, **(extra or {})}
        if comment:
            extra["comment"] = comment
        kind = kind or ("comment" if comment else "question")
        label = {"comment": f"💬 {comment['name'] if comment else ''} → {to.name}",
                 "rollcall": "👋 chat roll-call", "mood": "🔥 chat mood"}.get(kind, f"→ {to.name}")
        self._speak(self.host, label, system, user, max_words=max_words, kind=kind, extra=extra)

    def _panelist(self, topic: str, speaker: Character, kind: str, max_words: int | None = None,
                  viewer: str = "", comment: dict | None = None):
        side = self.sides[speaker.key]
        opponent = next(d for d in self.debaters if d.key != speaker.key)
        max_words = max_words or self.s["max_words_per_turn"]
        task = PANELIST_TASKS[kind].format(other=opponent.name, viewer=viewer)
        closing_line = (f"\nIf it fits naturally, you may end with your catchphrase: \"{speaker.catchphrase}\""
                        if kind == "closing" and speaker.catchphrase else "")
        user = (
            f"Debate so far:\n{self._history_text()}\n\n"
            f"Topic reminder: \"{topic}\" (you are {side} it)\n"
            f"{task}\n{TURN_RULES}{closing_line}\n"
            f"Reply with ONLY your spoken words, max {max_words} words."
        )
        extra = {"comment": comment} if comment else None
        self._speak(speaker, f"{side} · {kind}", self._panelist_system(speaker, opponent, topic), user,
                    max_words=max_words, kind=kind, extra=extra)

    def _debater_turn(self, topic: str, speaker: Character, rnd: str):
        side = self.sides[speaker.key]
        opponent = next(d for d in self.debaters if d.key != speaker.key)
        history = self._history_text()
        closing_line = (f"\nIf it fits naturally, you may end with your catchphrase: \"{speaker.catchphrase}\""
                        if rnd == "closing" and speaker.catchphrase else "")
        user = (
            (f"Debate so far:\n{history}\n\n" if history else "You speak first.\n\n")
            + f"Topic reminder: \"{topic}\" (you are {side} it)\n"
            f"Round: {rnd.upper()}. {ROUND_TASKS[rnd]}\n{TURN_RULES}{closing_line}\n"
            f"Reply with ONLY your spoken words, max {self.s['max_words_per_turn']} words, 2-3 sentences."
        )
        self._speak(speaker, f"{side} · {rnd}", self._panelist_system(speaker, opponent, topic), user,
                    max_words=self.s["max_words_per_turn"], kind=rnd)

    def _judge(self, topic: str) -> dict:
        """Two blind passes with the speakers' order swapped, so position (who spoke last)
        can't decide the result. Each pass scores both speakers; the totals pick the winner."""
        keys = [d.key for d in self.debaters]
        lines = {k: [t["text"] for t in self.record["turns"] if t["speaker"] == k] for k in keys}
        names = {d.key: d.name for d in self.debaters}
        system = (
            "You are an impartial judge for a comedy debate show. Score each speaker on the strength of "
            "their arguments and on how funny they were. Ignore which side you personally agree with, "
            "and ignore the order in which the speakers are listed."
        )
        (self.voice or self.printer).info("⚖️  Judge is deciding...")

        totals = {k: 0.0 for k in keys}
        passes, reasons, raws = 0, [], []
        for listing in (keys, keys[::-1]):
            labels = dict(zip(listing, ["X", "Y"]))
            blocks = "\n\n".join(
                f"Speaker {labels[k]} ({self.sides[k]} the topic):\n" + "\n".join(f"- {x}" for x in lines[k])
                for k in listing
            )
            user = (
                f"Topic: \"{topic}\"\n\n{blocks}\n\n"
                "Reply with JSON only, in this shape (numbers 1 to 10):\n"
                '{"X": {"argument": <1-10>, "humor": <1-10>}, "Y": {"argument": <1-10>, "humor": <1-10>}, '
                '"reason": "one short sentence saying who was better and why, calling them X and Y"}'
            )
            raw = self.llm.chat(system, user, temperature=self.s["judge_temperature"], max_tokens=200, json_mode=True)
            raws.append(raw)
            scores, reason = parse_scores(raw)
            if scores is None:
                continue
            passes += 1
            for k in keys:
                totals[k] += scores[labels[k]]
            reasons.append(re.sub(r"\b(?:Speaker\s+)?([XY])\b",
                                  lambda m: names[next(k for k in keys if labels[k] == m.group(1))], reason))

        if not passes:
            return {"winner": "draw", "score": "?-?", "reason": "The judge couldn't decide.", "raw": raws}
        avg = {k: totals[k] / passes for k in keys}
        a, b = keys
        winner = a if avg[a] > avg[b] else b if avg[b] > avg[a] else "draw"
        if winner == "draw":
            reason = "Both panelists scored exactly the same."
        else:  # prefer a reason that agrees with the final winner
            reason = next((r for r in reasons if names[winner] in r), "")
        return {
            "winner": winner,
            "score": f"{round(avg[a])}-{round(avg[b])}",
            "scores": {k: round(v, 1) for k, v in avg.items()},
            "reason": reason,
            "raw": raws,
        }

    def _host_verdict(self, topic: str, verdict: dict):
        names = {d.key: d.name for d in self.debaters}
        a, b = (d.key for d in self.debaters)
        score = f"{names[a]} {verdict['score'].split('-')[0]}, {names[b]} {verdict['score'].split('-')[-1]} (out of 20)"
        if verdict["winner"] in names:
            result = f"Winner: {names[verdict['winner']]}. Scores: {score}. Reason: {verdict['reason']}"
        else:
            result = f"It's a draw. Scores: {score}. Reason: {verdict['reason']}"
        votes = (self.record.get("chat") or {}).get("votes") or {}
        if votes:
            result += " Chat poll: " + ", ".join(f"{names[k]} {votes.get(k, 0)}" for k in names) + "."
        viewers = list(dict.fromkeys(c["name"] for c in self.record.get("comments", [])))
        thanks = (f"Thank the viewers who asked questions by name ({', '.join(viewers)}), then "
                  if viewers else "Then ")
        user = (
            f"The debate on \"{topic}\" is over. Judge's decision: {result}\n"
            f"Announce the result dramatically and roast the loser lightly. {thanks}ask viewers to comment "
            f"their questions for the next episode, and sign off. Max 55 words."
        )
        self._speak(self.host, "verdict", self._system_for(self.host, extra=""), user, max_words=55, kind="verdict")

    # ---------- helpers ----------

    def _panelist_system(self, speaker: Character, opponent: Character, topic: str) -> str:
        extra = (
            f"You are a panelist on a TV debate against {opponent.name} ({opponent.title or 'panelist'}). "
            f"Topic: \"{topic}\".\n"
            f"You argue {self.sides[speaker.key]} the topic. Never switch sides and never agree with {opponent.name}."
        )
        if speaker.politics and is_political(topic):
            extra += f"\nYour political views (this topic is political): {speaker.politics}"
        return self._system_for(speaker, extra=extra)

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

    def _speak(self, char: Character, label: str, system: str, user: str, max_words: int,
               kind: str, extra: dict | None = None):
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
        # Drop stage directions like "(dramatic music swells)": never spoken, so never captioned.
        text = re.sub(r"\s*[\(\[][^\)\]]*[\)\]]\s*", " ", text).strip()
        raw_text = None
        if self.s["language"] == "hindi" and len(LATIN_WORD.findall(text)) >= 2:
            raw_text, text = text, self._to_devanagari(text)
        secs = round(time.time() - t0, 1)
        turn = {
            "speaker": char.key,
            "name": char.name,
            "kind": kind,
            "side": self.sides.get(char.key),
            "text": text,
            "gen_seconds": secs,
            **(extra or {}),
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


def parse_scores(raw: str) -> tuple[dict | None, str]:
    """Read {"X": {...}, "Y": {...}, "reason": ...}; small models don't always return clean JSON."""
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

    def total(v) -> float | None:
        if isinstance(v, dict):
            nums = [_num(x) for x in v.values()]
            nums = [n for n in nums if n is not None]
            return sum(nums) if nums else None
        return _num(v)

    x, y = total(data.get("X")), total(data.get("Y"))
    if x is None or y is None:
        return None, ""
    return {"X": x, "Y": y}, str(data.get("reason", "")).strip()


def _num(v) -> float | None:
    try:
        return max(0.0, min(10.0, float(v)))
    except (TypeError, ValueError):
        return None
