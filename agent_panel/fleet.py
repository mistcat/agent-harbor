"""The fleet: the followed session plus the newest session in each of the repo's other git worktrees, and in
each worktree of any --also-repo. Read-only."""
import os
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
    """A ship's agents, marked as ship `key`, with ids prefixed by it so they can't collide with the flagship's."""
    out = []
    for a in snap.agents:
        a = replace(a, id=f"{key}/{a.id}", parent_id=f"{key}/{a.parent_id}" if a.parent_id else None, ship=key)
        out.append(replace(a, label=key) if a.parent_id is None else a)
    return out


def _same(a: Path, b: Path) -> bool:
    try:
        return os.path.samefile(a, b)  # also matches a path spelled in another case on a case-insensitive disk
    except OSError:
        return a == b


class Fleet:
    """Same poll() surface as Watcher. The flagship is the `cwd` session; each other worktree adds a ship.

    Each of `also_repos` adds a ship per worktree of that repo, but not its main checkout (where that repo's
    own controller usually runs). Those ships are labelled `<repo>:<worktree>`, so two repos with a worktree
    of the same name stay apart; a path that is no git repo, or can't be read, adds nothing."""

    def __init__(self, cwd: Path, config_dir: Path | None = None, pinned: str | None = None,
                 list_worktrees: Callable[[Path], list[Path]] = git_worktrees, also_repos: list[Path] = ()):
        self.cwd = cwd.resolve()
        self.also_repos = list(also_repos)
        self.config_dir = config_dir
        self.flagship = Watcher(lambda: resolve_project(self.cwd, config_dir, session=pinned), pinned=pinned)
        self._list = list_worktrees
        self.ships: dict[Path, Watcher] = {}
        self.keys: dict[Path, str] = {}  # ship label and id prefix, kept for as long as the worktree is listed
        self._projs: dict[Path, Path] = {}  # each ship's project dir, resolved once per scan
        self._scanned_at: float | None = None

    def _rescan(self) -> None:
        paths = self._list(self.cwd)
        # The flagship's own worktree is skipped, also when --cwd is a folder inside it (the deepest match,
        # since a worktree can sit inside the main checkout).
        mine = [self.cwd, *self.cwd.parents]
        own = max((p for p in paths if any(_same(p, c) for c in mine)), key=lambda p: len(p.parts), default=None)
        names = {p: p.name for p in paths if p != own and p.is_dir()}
        for repo in self.also_repos:
            main, *worktrees = self._list(repo) or [None]  # git lists the main checkout first
            for p in worktrees:
                if p != own and p not in names and p.is_dir():
                    names[p] = f"{main.name}:{p.name}"
        paths = list(names)
        self.keys = {p: k for p, k in self.keys.items() if p in names}
        taken = {"main", *self.keys.values()}
        for p in paths:
            if p not in self.keys:
                key, n = names[p], 2
                while key in taken:
                    key, n = f"{names[p]}-{n}", n + 1
                self.keys[p] = key
                taken.add(key)
        self._projs = {p: resolve_project(p, self.config_dir) for p in paths}
        self.ships = {p: self.ships.get(p) or Watcher(lambda p=p: self._projs[p]) for p in paths}

    def poll(self, now: float | None = None) -> Snapshot | None:
        now = time.time() if now is None else now
        snap = self.flagship.poll(now)
        if snap is None:
            return None
        if self._scanned_at is None or now - self._scanned_at >= RESCAN_S:
            self._scanned_at = now
            self._rescan()
        agents = list(snap.agents)
        for path, watcher in self.ships.items():
            try:
                ship = watcher.poll(now)
            except Exception:  # one unreadable ship must not sink the flagship's view
                continue
            if ship is not None:
                agents += _rename(ship, self.keys[path])
        return replace(snap, agents=agents)
