"""Piper TTS (local, CPU). Voices download on first use from the official Piper voice repo."""
import urllib.request
from pathlib import Path

import numpy as np

from .audio_fx import resample_by

VOICE_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/{family}/{locale}/{speaker}/{quality}/{name}{ext}"


class PiperTTS:
    def __init__(self, models_dir: Path):
        from piper import PiperVoice, SynthesisConfig  # imported here so --no-voice works without piper
        self._PiperVoice = PiperVoice
        self._SynthesisConfig = SynthesisConfig
        self.models_dir = models_dir
        self.voices = {}

    def synth(self, text: str, model: str, speed: float = 1.0, pitch: float = 1.0) -> tuple[np.ndarray, int]:
        """Return (float32 mono audio, sample_rate).

        Piper has no pitch control, so for pitch p we synthesize p times slower, then
        resample p times shorter: pitch moves by p while the pace stays at `speed`.
        """
        voice = self._voice(model)
        cfg = self._SynthesisConfig(length_scale=pitch / speed)
        chunks = list(voice.synthesize(text, syn_config=cfg))
        if not chunks:
            return np.zeros(0, dtype=np.float32), voice.config.sample_rate
        audio = np.concatenate([c.audio_float_array for c in chunks]).astype(np.float32)
        return resample_by(audio, pitch), chunks[0].sample_rate

    def _voice(self, name: str):
        if name not in self.voices:
            self._download(name)
            self.voices[name] = self._PiperVoice.load(str(self.models_dir / f"{name}.onnx"))
        return self.voices[name]

    def _download(self, name: str):
        locale, speaker, quality = name.split("-")
        self.models_dir.mkdir(parents=True, exist_ok=True)
        for ext in (".onnx", ".onnx.json"):
            dest = self.models_dir / f"{name}{ext}"
            if not dest.exists():
                url = VOICE_URL.format(family=locale.split("_")[0], locale=locale,
                                       speaker=speaker, quality=quality, name=name, ext=ext)
                print(f"Downloading voice {dest.name} ...")
                urllib.request.urlretrieve(url, dest)
