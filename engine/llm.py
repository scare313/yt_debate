"""Thin wrapper over any OpenAI-compatible chat API (Ollama locally, cloud later)."""
import re
import unicodedata
from typing import Callable, Optional

from openai import OpenAI

THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


class LLM:
    def __init__(self, base_url: str, api_key: str, model: str):
        self.client = OpenAI(base_url=base_url, api_key=api_key)
        self.model = model

    def chat(
        self,
        system: str,
        user: str,
        temperature: float = 0.8,
        max_tokens: int = 300,
        on_token: Optional[Callable[[str], None]] = None,
        json_mode: bool = False,
    ) -> str:
        kwargs = dict(
            model=self.model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        if on_token is None:
            resp = self.client.chat.completions.create(**kwargs)
            return clean(resp.choices[0].message.content or "")

        # Stream tokens so the terminal shows progress (CPU inference is slow).
        parts = []
        for chunk in self.client.chat.completions.create(stream=True, **kwargs):
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                parts.append(delta)
                on_token(delta)
        return clean("".join(parts))


def clean(text: str) -> str:
    """Strip reasoning tags, stray wrapping quotes, and letters from unexpected alphabets
    (small models sometimes glitch out a few Cyrillic/CJK characters mid-sentence)."""
    text = THINK_RE.sub("", text).strip()
    text = "".join(ch for ch in text if _allowed(ch))
    return text.strip('"“”').strip()


def _allowed(ch: str) -> bool:
    if not unicodedata.category(ch).startswith(("L", "M")):
        return True                      # digits, punctuation, spaces, emoji
    o = ord(ch)
    return o < 0x250 or 0x1E00 <= o <= 0x1EFF or 0x900 <= o <= 0x97F   # Latin (incl. IAST ṇḍṛ) or Devanagari
