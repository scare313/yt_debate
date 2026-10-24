from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Character:
    key: str
    name: str
    emoji: str
    color: str
    persona: str
    title: str = ""                              # name-strip line, e.g. "Garment Trader, Surat"
    voice: dict = field(default_factory=dict)    # model, speed, pitch, call
    catchphrase: str = ""                        # offered only in the closing statement
    politics: str = ""                           # added to the prompt only for political topics
    aliases: list = field(default_factory=list)  # other spellings viewers use (votes in chat)
    examples: list = field(default_factory=list) # sample lines showing how they talk
    name_hi: str = ""                            # name in Hindi script, so models don't mangle it


def load_character(config_dir: Path, key: str) -> Character:
    data = yaml.safe_load((config_dir / "characters" / f"{key}.yaml").read_text())
    return Character(
        key=key,
        name=data["name"],
        emoji=data.get("emoji", ""),
        color=data.get("color", "white"),
        persona=data["persona"].strip(),
        title=data.get("title", ""),
        voice=data.get("voice") or {},
        catchphrase=data.get("catchphrase", ""),
        politics=(data.get("politics") or "").strip(),
        aliases=data.get("aliases") or [],
        examples=data.get("examples") or [],
        name_hi=data.get("name_hi", ""),
    )
