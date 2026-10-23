"""Stage 1 safety: a simple blocklist on incoming topics. A proper safety model comes in Stage 5."""
import re
from pathlib import Path


class Blocklist:
    def __init__(self, path: Path):
        terms = []
        if path.exists():
            for line in path.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    terms.append(re.escape(line.lower()))
        self.pattern = re.compile(r"\b(" + "|".join(terms) + r")\b") if terms else None

    def check(self, text: str) -> str | None:
        """Return the blocked term found, or None if the text is allowed."""
        if not self.pattern:
            return None
        m = self.pattern.search(text.lower())
        return m.group(1) if m else None
