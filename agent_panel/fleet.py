"""The fleet: the followed session plus the newest session in each of the repo's other git worktrees. Read-only."""
import subprocess
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from agent_panel.session import Snapshot, Watcher, resolve_project

RESCAN_S = 5.0  # how often `git worktree list` is re-run


def git_worktrees(cwd: Path) -> list[Path]:
    """Every worktree of the repo holding `cwd` (the main checkout included), or [] if that can't be read."""
    try:
        out = subprocess.run(["git", "-C", str(cwd), "worktree", "list", "--porcelain"],
                             capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return []
    if out.returncode != 0:
        return []
    return [Path(line[len("worktree "):]).resolve() for line in out.stdout.splitlines() if line.startswith("worktree ")]


def _rename(snap: Snapshot, key: str) -> list:
    """A ship's agents with ids prefixed by `key`, so they can't collide with the flagship's "main"."""
    out = []
    for a in snap.agents:
        a = replace(a, id=f"{key}/{a.id}", parent_id=f"{key}/{a.parent_id}" if a.parent_id else None)
        out.append(replace(a, label=key) if a.parent_id is None else a)
    return out


class Fleet:
    """Same poll() surface as Watcher. The flagship is the `cwd` session; each other worktree adds a ship."""

    def __init__(self, cwd: Path, config_dir: Path | None = None, pinned: str | None = None,
                 list_worktrees: Callable[[Path], list[Path]] = git_worktrees):
        self.cwd = cwd.resolve()
        self.config_dir = config_dir
        self.flagship = Watcher(lambda: resolve_project(self.cwd, config_dir, session=pinned), pinned=pinned)
        self._list = list_worktrees
        self.ships: dict[Path, Watcher] = {}
        self._scanned_at: float | None = None

    def _others(self, now: float) -> list[Path]:
        if self._scanned_at is None or now - self._scanned_at >= RESCAN_S:
            self._scanned_at = now
            paths = self._list(self.cwd)
            # The flagship's own worktree is skipped, also when --cwd is a folder inside it (the deepest match,
            # since a worktree can sit inside the main checkout).
            own = max((p for p in paths if p == self.cwd or p in self.cwd.parents), key=lambda p: len(p.parts), default=None)
            paths = [p for p in paths if p != own and p.is_dir()]
            self.ships = {p: self.ships.get(p) or Watcher(lambda p=p: resolve_project(p, self.config_dir)) for p in paths}
        return list(self.ships)

    def poll(self, now: float | None = None) -> Snapshot | None:
        now = time.time() if now is None else now
        snap = self.flagship.poll(now)
        if snap is None:
            return None
        agents, keys = list(snap.agents), set()
        for path in self._others(now):
            try:
                ship = self.ships[path].poll(now)
            except Exception:  # one unreadable ship must not sink the flagship's view
                continue
            if ship is None:
                continue
            key, n = path.name, 2
            while key in keys:
                key, n = f"{path.name}-{n}", n + 1
            keys.add(key)
            agents += _rename(ship, key)
        return replace(snap, agents=agents)
