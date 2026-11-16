"""The cannon boom and the attention call. Playing a local WAV (or `say`) is the one side effect besides drawing."""
import shutil
import subprocess
from pathlib import Path

ASSETS = Path(__file__).parent / "assets"
WAV = ASSETS / "cannon.wav"
ATTENTION_WAV = ASSETS / "attention.wav"  # a deeper cannon with a longer tail
AHOY = "Ahoy, matey"
ATTENTION_GAP_S = 30.0  # the attention call never repeats sooner than this


class Boomer:
    """Plays `wav` with `player` (or runs `player *args`), at most once per min_gap_s. Missing player or file: silent."""

    def __init__(self, enabled: bool, min_gap_s: float = 2.0, player: str = "afplay", wav: Path = WAV,
                 args: list[str] | None = None):
        self.enabled = enabled
        self.min_gap_s = min_gap_s
        self.player = player
        self.wav = wav
        self.args = args
        self._last: float | None = None
        self._procs: list[subprocess.Popen] = []

    def boom(self, now: float) -> bool:
        if not self.enabled or self.args is None and not self.wav.exists():
            return False
        if self._last is not None and now - self._last < self.min_gap_s:
            return False
        exe = shutil.which(self.player)
        if exe is None:
            return False
        self._procs = [p for p in self._procs if p.poll() is None]  # reap finished players
        try:
            argv = [exe, *self.args] if self.args is not None else [exe, str(self.wav)]
            self._procs.append(subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        except OSError:
            return False
        self._last = now
        return True


def attention_player(mode: str, enabled: bool) -> Boomer:
    """The attention call for --attention-sound: "boom" (attention.wav), "say" (macOS `say`) or "off"."""
    on = enabled and mode != "off"
    if mode == "say":
        return Boomer(on, ATTENTION_GAP_S, player="say", args=[AHOY])
    return Boomer(on, ATTENTION_GAP_S, wav=ATTENTION_WAV)


def waiting_on_user(snap) -> bool:
    """The flagship's turn has ended and none of its subagents runs: the controller waits on the user."""
    return snap.turn_ended and not any(a.status == "running" and a.parent_id and not a.ship for a in snap.agents)


class Attention:
    """Rings once when the flagship starts waiting on the user. Pure: feed it snapshots and the time."""

    def __init__(self, min_gap_s: float = ATTENTION_GAP_S):
        self.min_gap_s = min_gap_s
        self._was: bool | None = None  # None until the first poll, so an already idle session stays quiet
        self._last: float | None = None

    def update(self, snap, now: float) -> bool:
        waiting = waiting_on_user(snap)
        ring = (self._was is False and waiting
                and (self._last is None or now - self._last >= self.min_gap_s))
        self._was = waiting
        if ring:
            self._last = now
        return ring
