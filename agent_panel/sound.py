"""The cannon boom and the attention call. Playing a local WAV (or `say`) is the one side effect besides drawing."""
import shutil
import subprocess
from pathlib import Path

ASSETS = Path(__file__).parent / "assets"
WAV = ASSETS / "cannon.wav"
ATTENTION_WAV = ASSETS / "attention.wav"  # a deeper cannon with a longer tail
AHOY_WAV = ASSETS / "ahoy.wav"  # a gravelly "Ah-hoy ... may-tee" in the Daniel voice (scripts/make_ahoy.sh)
AHOY = "Ahoy, matey"
ATTENTION_GAP_S = 30.0  # the attention call never repeats sooner than this
SETTLE_S = 6.0  # the call waits this long with nothing running, so a controller about to resume stays quiet


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
    """The attention call for --attention-sound: "boom" (attention.wav), "ahoy" (ahoy.wav), "say" (macOS `say`)
    or "off"."""
    on = enabled and mode != "off"
    if mode == "say":
        return Boomer(on, ATTENTION_GAP_S, player="say", args=[AHOY])
    if mode == "ahoy":
        return Boomer(on, ATTENTION_GAP_S, wav=AHOY_WAV)
    return Boomer(on, ATTENTION_GAP_S, wav=ATTENTION_WAV)


def waiting_on_user(snap) -> bool:
    """The flagship's turn has ended and nothing else runs, no subagent and no other worktree's session:
    the controller waits on the user, not on its fleet."""
    return snap.turn_ended and not any(a.status == "running" and not a.flagship for a in snap.agents)


class Attention:
    """Rings at most once per ended turn of the flagship. Pure: feed it snapshots and the time.

    Only the flagship's own `turn_ended` going False -> True (a new end_turn) arms the call. Subagents and
    other worktrees' sessions never arm it; while one runs it only holds a pending ring, because those
    statuses are quiet-time guesses. The ring sounds once nothing else has run for SETTLE_S, and a new turn
    starting first cancels it. The gap between rings delays a pending ring; it never drops one."""

    def __init__(self, min_gap_s: float = ATTENTION_GAP_S, settle_s: float = SETTLE_S):
        self.min_gap_s = min_gap_s
        self.settle_s = settle_s
        self._session: str | None = None
        self._ended = False
        self._pending = False
        self._quiet_since: float | None = None
        self._last: float | None = None

    def update(self, snap, now: float) -> bool:
        if snap.session_id != self._session:  # a first poll, or a switch: an already idle session stays quiet
            self._session, self._ended, self._pending = snap.session_id, snap.turn_ended, False
            return False
        if snap.turn_ended and not self._ended:
            self._pending, self._quiet_since = True, None
        elif not snap.turn_ended:
            self._pending = False
        self._ended = snap.turn_ended
        if not self._pending:
            return False
        if not waiting_on_user(snap):
            self._quiet_since = None
            return False
        if self._quiet_since is None:
            self._quiet_since = now
        if now - self._quiet_since < self.settle_s or self._last is not None and now - self._last < self.min_gap_s:
            return False
        self._pending, self._last = False, now
        return True
