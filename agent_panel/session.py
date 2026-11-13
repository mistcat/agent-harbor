"""Finds the Claude session to follow and folds its transcripts into an agent list. Read-only."""
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

from agent_panel.model import Agent
from agent_panel.transcript import FileStats, Tail, fold, short_model

MAIN_RUNNING_S = 10  # main "running" = transcript modified this recently
SUBAGENT_STALE_S = 30  # a subagent whose meta lacks `finished` is done once its file is this quiet


def config_dir() -> Path:
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(env) if env else Path.home() / ".claude"


def slug_dir(cwd: Path, cfg: Path) -> Path:
    # Every non-alphanumeric char becomes "-" (checked against real project dirs).
    return cfg / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(cwd))


def project_dir(cwd: Path, cfg: Path) -> Path | None:
    p = slug_dir(cwd, cfg)
    return p if p.is_dir() else None


def _mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


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


@dataclass
class Snapshot:
    session_id: str
    agents: list[Agent]
    new_shots: int
    advisor_model: str | None


class Watcher:
    def __init__(self, proj: Path, pinned: str | None = None):
        self.proj = proj
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
        if tail.was_reset:
            self._stats[path] = FileStats()
        stats = self._stats.setdefault(path, FileStats())
        return fold(stats, entries, skip_sidechain)

    def poll(self, now: float | None = None) -> Snapshot | None:
        now = time.time() if now is None else now
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
                metas[aid] = json.loads((sub_dir / f"agent-{aid}.meta.json").read_text())
            except (OSError, ValueError):
                metas[aid] = {}

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
                agents.append(self._agent(aid, pid, depth, desc or aid, meta.get("agentType") or "", stats,
                                          "done" if fin else "running", meta.get("model"), linked))
                add(aid, depth + 1)

        add("main", 1)
        return Snapshot(main.stem, agents, shots, short_model(main_stats.advisor_model) if main_stats.advisor_model else None)

    @staticmethod
    def _agent(aid, parent, depth, label, agent_type, stats: FileStats, status, meta_model, linked) -> Agent:
        return Agent(
            id=aid, parent_id=parent, depth=depth, label=label, agent_type=agent_type,
            model=short_model(stats.model) if stats.model else (meta_model or "?"),
            effort=stats.effort, status=status, burn=stats.burn, cache_read=stats.cache_read,
            advisor_calls=stats.advisor_calls, last_advisor_at=stats.last_advisor_at, linked=linked,
        )
