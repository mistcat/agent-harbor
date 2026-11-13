"""The cannon boom. Playing a local WAV is the one side effect besides drawing."""
import shutil
import subprocess
from pathlib import Path

WAV = Path(__file__).parent / "assets" / "cannon.wav"


class Boomer:
    def __init__(self, enabled: bool, min_gap_s: float = 2.0, player: str = "afplay"):
        self.enabled = enabled
        self.min_gap_s = min_gap_s
        self.player = player
        self._last: float | None = None
        self._procs: list[subprocess.Popen] = []

    def boom(self, now: float) -> bool:
        if not self.enabled or not WAV.exists():
            return False
        if self._last is not None and now - self._last < self.min_gap_s:
            return False
        exe = shutil.which(self.player)
        if exe is None:
            return False
        self._procs = [p for p in self._procs if p.poll() is None]  # reap finished players
        try:
            self._procs.append(subprocess.Popen([exe, str(WAV)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        except OSError:
            return False
        self._last = now
        return True
