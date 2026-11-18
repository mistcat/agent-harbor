"""Incremental JSONL transcript reader.

Field paths verified against real transcripts on 2026-11-13. Notes: an Agent
tool_use's input.model is optional, and a subagent .meta.json may lack `finished`.
"""
import json
import re
from dataclasses import dataclass, field
from pathlib import Path


class Tail:
    """Reads only the bytes appended since the last poll."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.offset = 0
        self._buf = b""
        self.was_reset = False
        self._ino: tuple[int, int] | None = None

    def poll(self) -> list[dict]:
        self.was_reset = False
        try:
            st = self.path.stat()
            ino = (st.st_dev, st.st_ino)
            # Shorter, or another file in its place (even a larger one): read it again from the start.
            if st.st_size < self.offset or self._ino is not None and ino != self._ino:
                self.offset, self._buf, self.was_reset = 0, b"", True
            self._ino = ino
            with open(self.path, "rb") as f:
                f.seek(self.offset)
                data = f.read()
        except OSError:
            return []
        self.offset += len(data)
        data = self._buf + data
        *lines, self._buf = data.split(b"\n")
        out = []
        for line in lines:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out


@dataclass
class FileStats:
    model: str | None = None
    effort: str | None = None
    advisor_model: str | None = None
    burn: int = 0
    cache_read: int = 0
    advisor_calls: int = 0
    last_advisor_at: str | None = None
    agent_calls: dict[str, dict] = field(default_factory=dict)
    seen_ids: set[str] = field(default_factory=set)
    last_entry_at: str | None = None
    turn_ended: bool = False  # the last assistant message ended the turn and no prompt has come since


def _count(v) -> int:
    """A token count, or 0 for anything that isn't a plain int."""
    return v if isinstance(v, int) and not isinstance(v, bool) else 0


def fold(stats: FileStats, entries: list[dict], skip_sidechain: bool) -> int:
    """Fold entries into stats; return the number of new advisor calls."""
    new_advisor = 0
    for e in entries:
        if not isinstance(e, dict) or skip_sidechain and e.get("isSidechain"):
            continue
        ts = e.get("timestamp")
        if ts:
            stats.last_entry_at = ts
        msg = e.get("message")
        if e.get("type") == "user" and isinstance(msg, dict) and not e.get("isMeta") and _is_prompt(msg.get("content")):
            stats.turn_ended = False
        if e.get("type") != "assistant" or not isinstance(msg, dict):
            continue
        stats.turn_ended = msg.get("stop_reason") == "end_turn"
        if msg.get("model"):
            stats.model = msg["model"]
        if e.get("effort"):
            stats.effort = e["effort"]
        if e.get("advisorModel"):
            stats.advisor_model = e["advisorModel"]
        mid = msg.get("id")
        usage = msg.get("usage")
        if mid and mid not in stats.seen_ids and isinstance(usage, dict):
            stats.seen_ids.add(mid)
            stats.burn += sum(_count(usage.get(k)) for k in ("input_tokens", "cache_creation_input_tokens", "output_tokens"))
            stats.cache_read += _count(usage.get("cache_read_input_tokens"))
        content = msg.get("content")
        for b in content if isinstance(content, list) else []:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_use" and b.get("name") == "Agent" and b.get("id"):
                inp = b.get("input") if isinstance(b.get("input"), dict) else {}
                stats.agent_calls[b["id"]] = {
                    "description": inp.get("description"),
                    "model": inp.get("model"),
                    "subagent_type": inp.get("subagent_type"),
                }
            elif b.get("type") == "server_tool_use" and b.get("name") == "advisor":
                stats.advisor_calls += 1
                new_advisor += 1
                stats.last_advisor_at = ts or stats.last_advisor_at
    return new_advisor


def _is_prompt(content) -> bool:
    """A user entry the person typed, not a tool result coming back."""
    if isinstance(content, str):
        return True
    return isinstance(content, list) and not any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content)


def short_model(model_id: str | None) -> str:
    """claude-sonnet-5-5 -> 'sonnet 5.5', claude-opus-5 -> 'opus 5'; None -> '?'; unknown shapes unchanged."""
    if not model_id:
        return "?"
    m = re.fullmatch(r"claude-([a-z]+)-(\d+)(?:-(\d+))?", model_id)
    if not m:
        return model_id
    return f"{m[1]} {m[2]}.{m[3]}" if m[3] else f"{m[1]} {m[2]}"
