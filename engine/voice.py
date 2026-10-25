"""Voices a debate: synthesize each turn, save it, and play turns in order.

Playback runs on a background thread, so while one turn is being heard the
orchestrator is already generating the next one (no dead air). Text is printed
when its audio starts, so the terminal stays in sync with what you hear.
"""
import queue
import shutil
import subprocess
import threading
import time
from pathlib import Path

import numpy as np

from .audio_fx import normalize, phone_filter, silence, write_wav
from .characters import Character
from .speech_text import to_speech
from .tts import PiperTTS


def find_player() -> list[str] | None:
    for cmd in (["pw-play"], ["paplay"], ["aplay", "-q"]):
        if shutil.which(cmd[0]):
            return cmd
    return None


class VoiceSession:
    def __init__(self, tts: PiperTTS, settings: dict, audio_dir: Path, printer, play: bool = True,
                 speech_fn=to_speech):
        self.tts = tts
        self.speech_fn = speech_fn      # text -> what the voice reads (Hindi by default)
        self.s = settings
        self.audio_dir = audio_dir
        self.printer = printer
        self.player = find_player() if play else None
        self.gap = float(settings.get("gap_seconds", 0.35))
        self.segments: list[tuple[np.ndarray, int]] = []
        self.cursor = 0.0  # where the next turn starts in the full-debate audio
        self.queue: queue.Queue = queue.Queue(maxsize=1)
        self.proc: subprocess.Popen | None = None
        self.stopped = False
        self.thread = threading.Thread(target=self._play_loop, daemon=True)
        self.thread.start()

    # ---------- called by the orchestrator ----------

    def turn(self, char: Character, label: str, text: str, turn: dict):
        v = char.voice
        spoken = self.speech_fn(text)
        audio, sr = self.tts.synth(spoken, v["model"], float(v.get("speed", 1.0)), float(v.get("pitch", 1.0)))
        if v.get("call") and self.s.get("call_filter", True):
            audio = phone_filter(audio, sr)
        audio = normalize(audio)

        self.audio_dir.mkdir(parents=True, exist_ok=True)
        path = self.audio_dir / f"{len(self.segments) + 1:02d}_{char.key}.wav"
        write_wav(path, audio, sr)
        duration = len(audio) / sr

        turn.update({
            "spoken_text": spoken,
            "audio": f"{self.audio_dir.name}/{path.name}",
            "audio_seconds": round(duration, 2),
            "start_s": round(self.cursor, 2),  # offset in full.wav, for video sync later
        })
        self.cursor += duration + self.gap
        self.segments.append((audio, sr))
        self.queue.put(("turn", char, label, text, path, duration))

    def info(self, text: str):
        self.queue.put(("info", text))

    def finish(self) -> Path | None:
        """Wait until everything has been played, then write the full-debate audio."""
        self.queue.put(None)
        self.thread.join()
        return self._write_full()

    def stop(self):
        self.stopped = True
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()

    # ---------- playback thread ----------

    def _play_loop(self):
        while True:
            item = self.queue.get()
            if item is None or self.stopped:
                return
            if item[0] == "info":
                self.printer.info(item[1])
                continue
            _, char, label, text, path, duration = item
            self.printer.header(char, label)
            self.printer.token(text)
            self.printer.end(round(duration, 1))
            if self.player:
                self.proc = subprocess.Popen([*self.player, str(path)],
                                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self.proc.wait()
                time.sleep(self.gap)

    def _write_full(self) -> Path | None:
        if not self.segments:
            return None
        rates = {sr for _, sr in self.segments}
        if len(rates) != 1:
            return None  # mixed sample rates; skip the combined file
        sr = rates.pop()
        parts = []
        for audio, _ in self.segments:
            parts += [audio, silence(sr, self.gap)]
        path = self.audio_dir / "full.wav"
        write_wav(path, np.concatenate(parts), sr)
        return path
