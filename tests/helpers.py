"""Synthetic transcript builders. Field names checked against real transcripts 2026-11-13.

Differences from the spec: an Agent tool_use's `input.model` is optional, and a
subagent .meta.json may lack `finished`.
"""
import json
from pathlib import Path

TS = "2026-11-13T12:00:00.000Z"


def assistant(msg_id, model, usage, effort="medium", blocks=(), sidechain=False, ts=TS, advisor_model=None):
    u = {"input_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0, "output_tokens": 0}
    u.update(usage)
    e = {
        "type": "assistant",
        "timestamp": ts,
        "isSidechain": sidechain,
        "effort": effort,
        "message": {"id": msg_id, "model": model, "usage": u, "content": list(blocks)},
    }
    if advisor_model:
        e["advisorModel"] = advisor_model
    return e


def agent_call(tool_id, description, model="sonnet", subagent_type="general-purpose"):
    return {
        "type": "tool_use", "id": tool_id, "name": "Agent",
        "input": {"description": description, "model": model, "subagent_type": subagent_type, "prompt": "x"},
    }


def advisor_call(ts=TS):
    return {"type": "server_tool_use", "id": "srvtoolu_" + ts, "name": "advisor", "input": {}, "timestamp": ts}


def write_jsonl(path: Path, entries, partial_tail: str = ""):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")
        f.write(partial_tail)
