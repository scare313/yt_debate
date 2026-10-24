# Dangal 24x7 — AI debate show

Dangal 24x7: anchor Ritika Rathore hosts two AI panelists who debate a topic in Hindi,
with local voices (Piper). A judge picks a winner, and every debate is saved as JSON plus
audio (the input for the video and Shorts stages).

## Setup (Ubuntu)

```bash
# 1. Install Ollama (local LLM server, runs as a systemd service)
curl -fsSL https://ollama.com/install.sh | sh

# 2. Download a model (~3 GB), then make the variant that fits fully on a 4 GB GPU
ollama pull gemma3:4b
ollama create gemma3-gpu -f config/ollama/Modelfile.gemma3-gpu

# 3. Python environment
cd ~/automation-projects/yt_debate
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Run

```bash
.venv/bin/python debate.py "क्या पुरानी पेंशन स्कीम वापस आनी चाहिए?"     # one debate, spoken aloud
.venv/bin/python debate.py                                # interactive, keep entering topics
.venv/bin/python debate.py --for imran "..."              # choose who argues FOR
.venv/bin/python debate.py --cast pandit,bunty "..."      # other panelists
.venv/bin/python debate.py --silent "..."                 # save audio, don't play it
.venv/bin/python debate.py --no-voice --language english "Tea vs coffee"   # text only
.venv/bin/python debate.py --comment "Rohit_from_Pune: तिवारी जी, कुछ बोलिए!" "..."   # viewer comment on air
.venv/bin/python debate.py --comments-file comments.txt "..."                     # one "Name: comment" per line
.venv/bin/python debate.py --format classic "..."         # fixed rounds instead of the news show
```

Writing: before each debate a "writers' room" step plans the jokes (angles, roasts, escalation,
an ending twist), and every turn uses one idea from that plan. Each character's file has
`examples:` lines that show the model how they talk; edit them to tune the humour.

Edit by hand (best for Shorts): every debate also saves `data/debates/<id>.script.txt`.
`--script-only` writes just the script (no voices). Rewrite, delete or add lines ("+ name: ..."),
then voice it with `.venv/bin/python tools/voice_script.py "data/debates/<id>.script.txt"`.
The voiced result becomes the newest debate, so the show screen plays it next.

Viewer chat: pass real comments with `--comments-file` (see `examples/comments_sample.txt`).
Every message is sorted automatically: greetings become Ritika's welcome roll-call, emojis rain
on screen, "team X" / "X op" / "X galat" count as poll votes, the best questions are read on air,
"next topic: ..." is saved as a suggestion, and spam/links/blocklisted words are dropped. Every
shown message scrolls in the ticker. Limits are in `config/settings.yaml` (`max_chat_breaks`,
`max_questions`, `rollcall_names`).

Show screen: `.venv/bin/python tools/stage_server.py`, then open http://localhost:8765/ to play
any voiced debate in the 9:16 news layout. Character art goes in `stage/assets/characters/`.

Formats: **news** (default) is a prime-time news debate. Ritika asks each panelist an opening
question, cross-questions them, panelists sometimes cut in, viewer comments are read on air,
then final lines and the verdict. **classic** is opening, rebuttals, closing. `--rounds` sets
the number of cross-questions (news) or rebuttal rounds (classic). Only use real viewer
comments; names and comments pass through the blocklist.

The judge scores both panelists twice with their order swapped, so speaking last
doesn't decide the winner.

`Ctrl+C` stops a debate and saves what was said so far.

Voices: each character's `voice:` block (Piper model, speed, pitch, and `call: true`
for the video-call sound) lives in `config/characters/<name>.yaml`. Voices download to
`models/piper/` on first use. Debates in Hindi script sound best; turns that slip into
English letters are converted to Devanagari automatically before being spoken.

## Where things live

| Path | What |
|---|---|
| `config/settings.yaml` | Model, language, rounds, words per turn |
| `config/characters/*.yaml` | Personalities, edit these to tune the comedy |
| `config/blocklist.txt` | Words that reject a topic |
| `data/debates/<id>.json` | Saved debate: text, timings, and each turn's offset in `full.wav` |
| `data/debates/<id>/` | Audio: one WAV per turn plus `full.wav` |
| `data/scoreboard.json` | Win/loss record and streaks (delete to reset) |

## Switching to a cloud LLM later

Change `llm.base_url`, `llm.api_key` and `llm.model` in `config/settings.yaml` to any
OpenAI-compatible endpoint. No code changes.
