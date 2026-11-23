"""Finds the Claude session to follow and folds its transcripts into an agent list. Read-only."""
import json
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from agent_panel.model import Agent
from agent_panel.transcript import FileStats, Tail, fold, short_model

MAIN_RUNNING_S = 10  # main "running" = transcript modified this recently
SUBAGENT_STALE_S = 30  # a subagent whose meta lacks `finished` is done once its file is this quiet
TOOL_STALE_S = 30 * 60
REPLY_STALE_S = 5 * 60


def slug_dir(cwd: Path, cfg: Path) -> Path:
    # Every non-alphanumeric char becomes "-" (checked against real project dirs).
    return cfg / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(cwd))


def _epoch(ts: str | None) -> float | None:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() if ts else None
    except (ValueError, AttributeError, TypeError):  # a malformed timestamp must not crash poll()
        return None


def _mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


def resolve_project(cwd: Path, explicit: Path | None = None, home: Path | None = None, session: str | None = None) -> Path:
    """The project dir to follow (it may not exist yet).

    Order: --config-dir, then $CLAUDE_CONFIG_DIR, then the profile among ~/.claude and ~/.claude-*
    whose copy of the project has the most recently written transcript (or, with `session`, the one
    that holds that session's transcript). Rex panes don't inherit
    CLAUDE_CONFIG_DIR, so the fallback is what makes a bare `agent-panel` work there.
    """
    if explicit:
        return slug_dir(cwd, Path(explicit))
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    if env:
        return slug_dir(cwd, Path(env))
    home = home or Path.home()
    best, best_t = None, -1.0
    for cfg in [home / ".claude", *sorted(home.glob(".claude-*"))]:
        proj = slug_dir(cwd, cfg)
        if not proj.is_dir():
            continue
        if session and (proj / f"{session}.jsonl").exists():
            return proj
        t = max((_mtime(f) for f in proj.glob("*.jsonl")), default=0.0)
        if t > best_t:
            best, best_t = proj, t
    return best or slug_dir(cwd, home / ".claude")


def pick_session(proj: Path, current: Path | None, now: float, quiet_s: float = 60) -> Path | None:
    files = list(proj.glob("*.jsonl")) if proj.is_dir() else []
    if not files:
        return None
    newest = max(files, key=_mtime)
    if current is None or not current.exists():
        return newest
    if newest != current and now - _mtime(current) >= quiet_s and _mtime(newest) > _mtime(current):
        return newest
    return current


def _break_cycles(kids: dict[str, list], ids: list[str], key) -> None:
    """Subagents whose parents claim each other in a loop never hang from main, so the tree would drop them.
    Move one agent of each loop under main, unlinked; the rest of the loop and its children hang from it."""
    parent = {aid: pid for pid, ks in kids.items() for _, aid, _ in ks}
    while True:
        seen, todo = set(), ["main"]
        while todo:
            for _, aid, _ in kids.get(todo.pop(), []):
                if aid not in seen:
                    seen.add(aid)
                    todo.append(aid)
        lost = [aid for aid in ids if aid not in seen]
        if not lost:
            return
        cur, path = lost[0], []
        while cur not in path:  # walk up from a lost agent until the walk repeats: that agent is in the loop
            path.append(cur)
            cur = parent[cur]
        kids[parent[cur]] = [k for k in kids[parent[cur]] if k[1] != cur]
        kids["main"].append((key(cur), cur, False))
        parent[cur] = "main"


@dataclass
class Snapshot:
    session_id: str
    agents: list[Agent]
    new_shots: int
    advisor_model: str | None
    turn_ended: bool = False  # the flagship's last turn is over: it waits on the user (or a subagent)


class Watcher:
    def __init__(self, proj: "Path | Callable[[], Path]", pinned: str | None = None):
        # A callable is re-evaluated each poll, so a project dir that appears later is found.
        self._proj = proj
        self.pinned = pinned
        self.current: Path | None = None
        self._tails: dict[Path, Tail] = {}
        self._stats: dict[Path, FileStats] = {}
        self._first = True

    def _reset(self):
        self._tails, self._stats, self._first = {}, {}, True

    def _read(self, path: Path, skip_sidechain: bool) -> int:
        tail = self._tails.setdefault(path, Tail(path))
        entries = tail.poll()
        if tail.was_reset:  # a replaced file is a re-baseline: its old calls are not new shots
            self._stats[path] = FileStats()
            fold(self._stats[path], entries, skip_sidechain)
            return 0
        stats = self._stats.setdefault(path, FileStats())
        return fold(stats, entries, skip_sidechain)

    def poll(self, now: float | None = None) -> Snapshot | None:
        now = time.time() if now is None else now
        self.proj = self._proj() if callable(self._proj) else self._proj
        if self.pinned:
            picked = self.proj / f"{self.pinned}.jsonl"
            picked = picked if picked.exists() else None
        else:
            picked = pick_session(self.proj, self.current, now)
        if picked is None:
            return None
        if picked != self.current:
            self._reset()
            self.current = picked
        main = picked
        shots = self._read(main, skip_sidechain=True)
        if self._first:
            shots = 0
        self._first = False

        sub_dir = main.with_suffix("") / "subagents"
        ids = sorted({p.name.split(".")[0].removeprefix("agent-") for p in sub_dir.glob("agent-*")}) if sub_dir.is_dir() else []
        files, metas = {}, {}
        for aid in ids:
            f = sub_dir / f"agent-{aid}.jsonl"
            files[aid] = f
            if f.exists():
                self._read(f, skip_sidechain=False)
            try:
                meta = json.loads((sub_dir / f"agent-{aid}.meta.json").read_text())
            except (OSError, ValueError):
                meta = {}
            metas[aid] = meta if isinstance(meta, dict) else {}

        # toolUseId -> (owner id, call order within that owner's transcript)
        owner: dict[str, tuple[str, int]] = {}
        for oid, path in [("main", main)] + [(a, files[a]) for a in ids]:
            for i, tid in enumerate(self._stats.get(path, FileStats()).agent_calls):
                owner[tid] = (oid, i)

        main_stats = self._stats[main]
        agents = [self._agent("main", None, 0, "main", "main", main_stats, "running" if now - _mtime(main) < MAIN_RUNNING_S else "idle", None, True)]
        kids: dict[str, list[tuple[tuple, str, bool]]] = {"main": []}
        for aid in ids:
            tid = metas[aid].get("toolUseId")
            parent, idx = owner.get(tid, ("main", 10**9)) if tid else ("main", 10**9)
            linked = tid in owner and parent != aid
            if not linked:
                parent, idx = "main", 10**9
            kids.setdefault(parent, []).append(((idx, _mtime(files[aid]), aid), aid, linked))
        _break_cycles(kids, ids, lambda aid: (10**9, _mtime(files[aid]), aid))

        def add(pid: str, depth: int):
            for _, aid, linked in sorted(kids.get(pid, [])):
                meta, stats = metas[aid], self._stats.get(files[aid], FileStats())
                call = owner.get(meta.get("toolUseId"))
                desc = meta.get("description")
                if not desc and call:
                    desc = self._stats[main if call[0] == "main" else files[call[0]]].agent_calls[meta["toolUseId"]].get("description")
                fin = meta.get("finished")
                if fin is None:
                    fin = files[aid].exists() and now - _mtime(files[aid]) >= SUBAGENT_STALE_S
                agent = self._agent(aid, pid, depth, desc or aid, meta.get("agentType") or "", stats,
                                    "done" if fin else "running", meta.get("model"), linked)
                if fin:  # the last entry's timestamp; the file's mtime matches it to within 0.1s on real transcripts
                    agent.finished_at = _epoch(stats.last_entry_at) or _mtime(files[aid]) or None
                agents.append(agent)
                add(aid, depth + 1)

        add("main", 1)
        return Snapshot(main.stem, agents, shots, short_model(main_stats.advisor_model) if main_stats.advisor_model else None,
                        main_stats.turn_ended)

    @staticmethod
    def _agent(aid, parent, depth, label, agent_type, stats: FileStats, status, meta_model, linked) -> Agent:
        return Agent(
            id=aid, parent_id=parent, depth=depth, label=label, agent_type=agent_type,
            model=short_model(stats.model) if stats.model else (meta_model or "?"),
            effort=stats.effort, status=status, burn=stats.burn, cache_read=stats.cache_read,
            advisor_calls=stats.advisor_calls, last_advisor_at=stats.last_advisor_at, linked=linked,
        )
