"""Small audio helpers on float32 mono numpy arrays."""
import wave
from pathlib import Path

import numpy as np


def normalize(audio: np.ndarray, peak: float = 0.89) -> np.ndarray:
    """Scale so the loudest sample sits at ~-1 dBFS (prevents clipping, evens out voices)."""
    top = float(np.abs(audio).max()) if audio.size else 0.0
    return (audio * (peak / top)).astype(np.float32) if top > 0 else audio


def phone_filter(audio: np.ndarray, sr: int) -> np.ndarray:
    """Video-call sound: band-limit to ~300-3400 Hz plus light saturation."""
    spec = np.fft.rfft(audio)
    freqs = np.fft.rfftfreq(len(audio), 1 / sr)
    spec[(freqs < 300) | (freqs > 3400)] *= 0.05
    out = np.fft.irfft(spec, n=len(audio))
    return (np.tanh(out * 2.5) / np.tanh(2.5)).astype(np.float32)


def resample_by(audio: np.ndarray, factor: float) -> np.ndarray:
    """Shorten by `factor` (>1 raises pitch and speeds up; <1 lowers and slows)."""
    if abs(factor - 1.0) < 1e-3:
        return audio
    positions = np.arange(0, len(audio) - 1, factor)
    return np.interp(positions, np.arange(len(audio)), audio).astype(np.float32)


def silence(sr: int, seconds: float) -> np.ndarray:
    return np.zeros(int(sr * seconds), dtype=np.float32)


def write_wav(path: Path, audio: np.ndarray, sr: int):
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())
