"""Synthesize the panel's two sounds into agent_panel/assets/, stdlib only. Run: python3 scripts/make_cannon.py

- cannon.wav: the advisor cannon, a low thump plus a noise burst, both decaying fast.
- attention.wav: the "needs you" call, a deeper, bass-heavy cannon with a longer rolling tail.
"""
import math
import random
import struct
import wave
from pathlib import Path

RATE = 22050
ASSETS = Path(__file__).resolve().parent.parent / "agent_panel" / "assets"


def cannon(t: float, rng: random.Random) -> float:
    thump = math.sin(2 * math.pi * (55 + 25 * math.exp(-t * 12)) * t) * math.exp(-t / 0.22)
    noise = rng.uniform(-1, 1) * math.exp(-t / 0.07)
    return 0.75 * thump + 0.45 * noise


def deep_cannon(t: float, rng: random.Random) -> float:
    # A lower sweep (38 Hz settling from 58) with its octave, so small speakers still carry it, and a slow
    # rumble of low-passed noise that rolls on after the blast.
    f = 38 + 20 * math.exp(-t * 8)
    body = (math.sin(2 * math.pi * f * t) + 0.5 * math.sin(4 * math.pi * f * t)) * math.exp(-t / 0.45)
    deep_cannon.rumble = 0.97 * deep_cannon.rumble + 0.03 * rng.uniform(-1, 1)
    blast = rng.uniform(-1, 1) * math.exp(-t / 0.05)
    return 0.8 * body + 6.0 * deep_cannon.rumble * math.exp(-t / 0.6) + 0.3 * blast


deep_cannon.rumble = 0.0


def write(path: Path, seconds: float, voice, seed: int) -> None:
    rng = random.Random(seed)
    samples = [voice(i / RATE, rng) for i in range(int(RATE * seconds))]
    peak = max(abs(s) for s in samples)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(b"".join(struct.pack("<h", int(s / peak * 30000)) for s in samples))


def main() -> None:
    write(ASSETS / "cannon.wav", 0.8, cannon, 7)
    write(ASSETS / "attention.wav", 1.8, deep_cannon, 11)


if __name__ == "__main__":
    main()
