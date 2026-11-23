"""Incremental JSONL transcript reader.

Field paths verified against real transcripts on 2026-11-13. Notes: an Agent
tool_use's input.model is optional, and a subagent .meta.json may lack `finished`.
"""
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

TOOL_STALE_S = 30 * 60  # an open tool call (or a background command) with no write for this long is stale


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
    open_tools: set[str] = field(default_factory=set)  # client tool calls with no tool_result yet
    awaiting_reply: bool = False  # a tool result or a prompt came in: the model speaks next
    watches: dict[str, float | None] = field(default_factory=dict)  # background task id -> deadline (epoch), if any


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
        if e.get("type") == "user" and isinstance(msg, dict):
            _fold_user(stats, e, msg.get("content"), ts)
        if e.get("type") != "assistant" or not isinstance(msg, dict):
            continue
        stats.turn_ended = msg.get("stop_reason") == "end_turn"
        stats.awaiting_reply = False
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
            if b.get("type") == "tool_use" and b.get("id"):
                stats.open_tools.add(b["id"])
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


INTERRUPT = "[Request interrupted by user"
NO_REPLY = ("<bash-input>", "<bash-stdout>", "<bash-stderr>", "<local-command-", "<command-name>", "<command-message>")
TASK_ID = re.compile(r"<task-id>([^<]+)</task-id>")
TASK_ENDED = re.compile(r"<status>[^<]+</status>|\[Monitor expired")


def _epoch(ts) -> float | None:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError, TypeError):
        return None


def _text(content) -> str:
    if isinstance(content, str):
        return content
    return "".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text") \
        if isinstance(content, list) else ""


def _fold_user(stats: FileStats, e: dict, content, ts) -> None:
    """A user entry: tool results close calls and start background watches; a prompt or a task notification owes
    the model a reply; an interrupt hands the turn back to the person."""
    results = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_result"] if isinstance(content, list) else []
    for b in results:
        stats.open_tools.discard(b.get("tool_use_id"))
    r = e.get("toolUseResult")
    if results and isinstance(r, dict):
        start = _epoch(ts)
        if isinstance(r.get("taskId"), str):  # a Monitor: it ends at its own timeout, unless persistent
            ms = r.get("timeoutMs")
            stats.watches[r["taskId"]] = None if r.get("persistent") or start is None or not isinstance(ms, (int, float)) \
                else start + ms / 1000
        elif isinstance(r.get("backgroundTaskId"), str):  # a background command: bounded like a tool call
            stats.watches[r["backgroundTaskId"]] = None if start is None else start + TOOL_STALE_S
        elif isinstance(r.get("task_id"), str):  # TaskStop
            stats.watches.pop(r["task_id"], None)
    text = _text(content)
    if text.startswith("<task-notification>") and (m := TASK_ID.search(text)) and TASK_ENDED.search(text):
        stats.watches.pop(m.group(1).strip(), None)
    if text.startswith(INTERRUPT):
        stats.open_tools.clear()
        stats.turn_ended = stats.awaiting_reply = False  # as before: no end_turn, so no attention call
        return
    if e.get("isMeta"):
        return
    if results:
        stats.awaiting_reply = True
    elif _is_prompt(content):
        stats.turn_ended = False
        stats.awaiting_reply = not e.get("isCompactSummary") and not text.lstrip().startswith(NO_REPLY)


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
