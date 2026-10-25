#!/usr/bin/env python3
"""Voice an (edited) Ask the Gita script.

    .venv/bin/python scripture/voice.py "scripture/data/answers/<id>.script.txt"

Re-voices every line with the narrator voice; the result becomes the newest answer, so the
show screen plays it next.
"""
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from scripture.qa.voicing import turns_from_script, voice_answer  # noqa: E402


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    script = Path(sys.argv[1]).resolve()
    json_path = script.with_name(script.name.removesuffix(".script.txt") + ".json")
    if not json_path.exists():
        sys.exit(f"Can't find {json_path.name} next to the script.")
    record = json.loads(json_path.read_text())
    narrator = yaml.safe_load((ROOT / "scripture" / "config" / "narrator.yaml").read_text())
    record["turns"] = turns_from_script(script, record)
    record["edited_at"] = record["created_at"] = datetime.now().isoformat(timespec="seconds")
    voice_answer(record, json_path, narrator)
    last = record["turns"][-1]
    secs = last["start_s"] + last["audio_seconds"]
    print(f"\nDone: {len(record['turns'])} lines, {int(secs // 60)}:{int(secs % 60):02d}. "
          f"It's now the newest answer, so the show screen plays it next.")


if __name__ == "__main__":
    main()
