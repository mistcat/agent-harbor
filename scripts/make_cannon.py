"""Synthesize agent_panel/assets/cannon.wav: a low thump plus a noise burst, both decaying fast.

stdlib only. Run: python3 scripts/make_cannon.py
"""
import math
import random
import struct
import wave
from pathlib import Path

RATE = 22050
SECONDS = 0.8
OUT = Path(__file__).resolve().parent.parent / "agent_panel" / "assets" / "cannon.wav"


def main() -> None:
    rng = random.Random(7)
    n = int(RATE * SECONDS)
    samples = []
    for i in range(n):
        t = i / RATE
        thump = math.sin(2 * math.pi * (55 + 25 * math.exp(-t * 12)) * t) * math.exp(-t / 0.22)
        noise = rng.uniform(-1, 1) * math.exp(-t / 0.07)
        samples.append(0.75 * thump + 0.45 * noise)
    peak = max(abs(s) for s in samples)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(OUT), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(b"".join(struct.pack("<h", int(s / peak * 30000)) for s in samples))


if __name__ == "__main__":
    main()
