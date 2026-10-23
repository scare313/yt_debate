#!/usr/bin/env python3
"""Generate side-by-side voice samples for choosing a local TTS engine.

Run with the TTS environment (Python 3.12):
    .venv-tts/bin/python tools/tts_samples.py

Writes to data/tts_samples/:
    <engine>_<character>_<script>.wav      single lines
    <engine>_dialogue_<script>_clean.wav   anchor -> Imran -> Tiwari, all clean
    <engine>_dialogue_<script>_news.wav    same, but panelists through a "video call" filter
"""
import time
import urllib.request
import wave
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "tts_samples"
PIPER_DIR = ROOT / "models" / "piper"

# Same three lines in Hindi script (deva) and Hinglish in English letters (roman).
LINES = {
    "anchor": {
        "deva": "नमस्कार, आप देख रहे हैं दंगल चौबीस बाय सात! आज का सबसे बड़ा सवाल: क्या जीएसटी ने छोटे "
                "व्यापारियों की ज़िंदगी आसान बनाई? इमरान जी, सीधा सवाल, सीधा जवाब!",
        "roman": "Namaskar, aap dekh rahe hain Dangal 24x7! Aaj ka sabse bada sawaal: kya GST ne chhote "
                 "vyapariyon ki zindagi aasaan banayi? Imran ji, seedha sawaal, seedha jawab!",
    },
    "imran": {
        "deva": "देखिए, जीएसटी से पहले मेरी दुकान में तीन रजिस्टर थे, अब एक ऐप है। काम दिखता है भाई, बस आँखें खोलिए!",
        "roman": "Dekhiye, GST se pehle meri dukaan mein teen register the, ab ek app hai. "
                 "Kaam dikhta hai bhai, bas aankhen kholiye!",
    },
    "tiwari": {
        "deva": "अरे इमरान भाई, ऐप तो आपके फ़ोन में है, पर टमाटर अस्सी रुपये किलो है! हमारे ज़माने में...",
        "roman": "Arey Imran bhai, app toh aapke phone mein hai, par tamatar assi rupaye kilo hai! "
                 "Hamare zamane mein...",
    },
}

# character -> (voice, speed). Anchor is female for contrast with the two male panelists.
CASTING = {
    "piper": {"anchor": ("hi_IN-priyamvada-medium", 0.9),
              "imran": ("hi_IN-pratham-medium", 1.0),
              "tiwari": ("hi_IN-rohan-medium", 1.1)},
    "kokoro": {"anchor": ("hf_alpha", 1.05),
               "imran": ("hm_omega", 1.0),
               "tiwari": ("hm_psi", 0.95)},
}

PIPER_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/hi/hi_IN/{speaker}/medium/{name}{ext}"


# ---------------- engines ----------------

class PiperEngine:
    name = "piper"

    def __init__(self):
        from piper import PiperVoice
        self.PiperVoice = PiperVoice
        self.voices = {}

    def _voice(self, name):
        if name not in self.voices:
            PIPER_DIR.mkdir(parents=True, exist_ok=True)
            speaker = name.split("-")[1]
            for ext in (".onnx", ".onnx.json"):
                dest = PIPER_DIR / f"{name}{ext}"
                if not dest.exists():
                    print(f"  downloading {dest.name} ...")
                    urllib.request.urlretrieve(PIPER_URL.format(speaker=speaker, name=name, ext=ext), dest)
            self.voices[name] = self.PiperVoice.load(str(PIPER_DIR / f"{name}.onnx"))
        return self.voices[name]

    def synth(self, text, voice, speed):
        from piper import SynthesisConfig
        v = self._voice(voice)
        cfg = SynthesisConfig(length_scale=1.0 / speed)
        chunks = list(v.synthesize(text, syn_config=cfg))
        audio = np.concatenate([c.audio_float_array for c in chunks])
        return audio.astype(np.float32), chunks[0].sample_rate


class KokoroEngine:
    name = "kokoro"

    def __init__(self):
        import torch
        from kokoro import KPipeline
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        try:
            self.pipe = KPipeline(lang_code="h", repo_id="hexgrad/Kokoro-82M", device=self.device)
        except Exception as e:  # GPU busy with the LLM -> fall back to CPU
            print(f"  kokoro on {self.device} failed ({e}); using CPU")
            self.device = "cpu"
            self.pipe = KPipeline(lang_code="h", repo_id="hexgrad/Kokoro-82M", device="cpu")
        print(f"  kokoro device: {self.device}")

    def synth(self, text, voice, speed):
        parts = []
        for result in self.pipe(text, voice=voice, speed=speed):
            audio = result.audio if hasattr(result, "audio") else result[2]
            parts.append(np.asarray(audio.cpu() if hasattr(audio, "cpu") else audio, dtype=np.float32))
        return np.concatenate(parts), 24000


# ---------------- audio helpers ----------------

def phone_filter(audio, sr):
    """Video-call sound: band-limit to ~300-3400 Hz plus light saturation."""
    spec = np.fft.rfft(audio)
    freqs = np.fft.rfftfreq(len(audio), 1 / sr)
    spec[(freqs < 300) | (freqs > 3400)] *= 0.05
    out = np.fft.irfft(spec, n=len(audio))
    out = np.tanh(out * 2.5) / np.tanh(2.5)
    return (out / max(np.abs(out).max(), 1e-6) * 0.9).astype(np.float32)


def silence(sr, seconds):
    return np.zeros(int(sr * seconds), dtype=np.float32)


# ---------------- main ----------------

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    report = []
    for Engine in (PiperEngine, KokoroEngine):
        print(f"\n== {Engine.name} ==")
        try:
            engine = Engine()
        except Exception as e:
            print(f"  could not start {Engine.name}: {e}")
            continue
        for script in ("deva", "roman"):
            clean, news = [], []
            for char in ("anchor", "imran", "tiwari"):
                voice, speed = CASTING[Engine.name][char]
                t0 = time.time()
                try:
                    audio, sr = engine.synth(LINES[char][script], voice, speed)
                except Exception as e:
                    print(f"  {char}/{script}: FAILED ({e})")
                    continue
                gen = time.time() - t0
                dur = len(audio) / sr
                sf.write(OUT / f"{Engine.name}_{char}_{script}.wav", audio, sr)
                report.append(f"{Engine.name:7} {char:7} {script:6} {voice:24} audio {dur:4.1f}s  generated in {gen:4.1f}s")
                print("  " + report[-1])
                clean += [audio, silence(sr, 0.35)]
                news += [audio if char == "anchor" else phone_filter(audio, sr), silence(sr, 0.35)]
            if clean:
                sf.write(OUT / f"{Engine.name}_dialogue_{script}_clean.wav", np.concatenate(clean), sr)
                sf.write(OUT / f"{Engine.name}_dialogue_{script}_news.wav", np.concatenate(news), sr)

    (OUT / "report.txt").write_text("\n".join(report) + "\n")
    print(f"\nSamples in {OUT.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()
