import json
import os
from pathlib import Path

from agent_panel.session import Watcher, pick_session, slug_dir
from tests.helpers import advisor_call, agent_call, assistant, write_jsonl

U = {"input_tokens": 5, "output_tokens": 5}
SONNET, OPUS = "claude-sonnet-5-5", "claude-opus-5-5"


def make_session(proj: Path, sid="sess1", main_blocks=(), mtime=None):
    p = proj / f"{sid}.jsonl"
    write_jsonl(p, [assistant("m1", OPUS, U, blocks=list(main_blocks))])
    if mtime is not None:
        os.utime(p, (mtime, mtime))
    return p


def add_sub(proj: Path, sid, aid, tool_use_id=None, model=SONNET, finished=None, blocks=(), meta=True, desc="do thing"):
    d = proj / sid / "subagents"
    write_jsonl(d / f"agent-{aid}.jsonl", [assistant(f"s-{aid}", model, U, blocks=list(blocks))])
    if meta:
        m = {"agentType": "general-purpose", "description": desc, "toolUseId": tool_use_id, "spawnDepth": 1, "model": "sonnet"}
        if finished is not None:
            m["finished"] = finished
        (d / f"agent-{aid}.meta.json").write_text(json.dumps(m))


def by_id(snap):
    return {a.id: a for a in snap.agents}


def test_slug_dir(tmp_path):
    # Real rule seen in ~/.claude*/projects: every non-alphanumeric char becomes "-"
    # (/Users/nate/Code/claude_tools/x -> -Users-nate-Code-claude-tools-x; "/.worktrees" -> "--worktrees").
    slug = tmp_path / "projects" / "-Users-nate-Code-claude-tools-my-app"
    assert slug_dir(Path("/Users/nate/Code/claude_tools/my.app"), tmp_path) == slug


def test_subagent_linked_to_main_by_tool_use_id(tmp_path):
    make_session(tmp_path, main_blocks=[agent_call("toolu_1", "audit TUIs")])
    add_sub(tmp_path, "sess1", "a1", "toolu_1", finished=False)
    a = by_id(Watcher(tmp_path).poll())["a1"]
    assert (a.parent_id, a.depth, a.status, a.linked) == ("main", 1, "running", True)
    assert a.label == "do thing" and a.model == "sonnet 5.5"


def test_nested_subagent_links_to_its_parent_agent(tmp_path):
    make_session(tmp_path, main_blocks=[agent_call("toolu_1", "outer")])
    add_sub(tmp_path, "sess1", "a1", "toolu_1", blocks=[agent_call("toolu_2", "inner")])
    add_sub(tmp_path, "sess1", "a2", "toolu_2")
    snap = Watcher(tmp_path).poll()
    a = by_id(snap)
    assert (a["a2"].parent_id, a["a2"].depth) == ("a1", 2)
    ids = [x.id for x in snap.agents]
    assert ids.index("a1") < ids.index("a2")


def test_unlinked_subagent_attaches_to_main(tmp_path):
    make_session(tmp_path)
    add_sub(tmp_path, "sess1", "a1", "toolu_nope")
    a = by_id(Watcher(tmp_path).poll())["a1"]
    assert (a.parent_id, a.depth, a.linked) == ("main", 1, False)


def test_jsonl_without_meta_still_shown(tmp_path):
    make_session(tmp_path)
    add_sub(tmp_path, "sess1", "a1", meta=False)
    a = by_id(Watcher(tmp_path).poll())["a1"]
    assert (a.label, a.status, a.model) == ("a1", "running", "sonnet 5.5")


def test_meta_without_jsonl_still_shown(tmp_path):
    make_session(tmp_path)
    d = tmp_path / "sess1" / "subagents"
    d.mkdir(parents=True)
    (d / "agent-a1.meta.json").write_text(json.dumps({"description": "early", "toolUseId": "t", "model": "haiku"}))
    a = by_id(Watcher(tmp_path).poll())["a1"]
    assert (a.label, a.status, a.model) == ("early", "running", "haiku")


def test_finished_meta_is_done(tmp_path):
    make_session(tmp_path)
    add_sub(tmp_path, "sess1", "a1", finished=True)
    assert by_id(Watcher(tmp_path).poll())["a1"].status == "done"


def test_unmarked_meta_goes_done_when_file_stale(tmp_path):
    # Real meta files can lack `finished`; treat a quiet subagent file as done.
    make_session(tmp_path)
    add_sub(tmp_path, "sess1", "a1")
    f = tmp_path / "sess1" / "subagents" / "agent-a1.jsonl"
    os.utime(f, (1000, 1000))
    assert by_id(Watcher(tmp_path).poll(now=1000 + 120))["a1"].status == "done"


def test_main_running_vs_idle(tmp_path):
    p = make_session(tmp_path, mtime=1000)
    w = Watcher(tmp_path)
    assert by_id(w.poll(now=1005))["main"].status == "running"
    assert by_id(w.poll(now=1020))["main"].status == "idle"


def test_main_is_first_with_label_main(tmp_path):
    make_session(tmp_path)
    m = Watcher(tmp_path).poll().agents[0]
    assert (m.id, m.label, m.depth, m.parent_id, m.model, m.effort) == ("main", "main", 0, None, "opus 5.5", "medium")


def test_new_shots_zero_on_first_poll_then_counts_new(tmp_path):
    p = make_session(tmp_path, main_blocks=[advisor_call()])
    w = Watcher(tmp_path)
    first = w.poll()
    assert first.new_shots == 0 and first.agents[0].advisor_calls == 1
    with open(p, "a") as f:
        f.write(json.dumps(assistant("m2", OPUS, U, blocks=[advisor_call("2026-11-13T12:05:00Z")], advisor_model="claude-fable-5-1")) + "\n")
    snap = w.poll()
    assert snap.new_shots == 1 and snap.agents[0].advisor_calls == 2
    assert snap.advisor_model == "fable 5.1"
    assert w.poll().new_shots == 0


def test_transcript_replaced_resets_stats(tmp_path):
    p = make_session(tmp_path)
    w = Watcher(tmp_path)
    assert w.poll().agents[0].burn == 10
    write_jsonl(p, [assistant("z", OPUS, {"output_tokens": 1})])
    assert w.poll().agents[0].burn == 1


def test_pick_session_stays_until_quiet_60s(tmp_path):
    cur = make_session(tmp_path, "old", mtime=1000)
    make_session(tmp_path, "new", mtime=1030)
    assert pick_session(tmp_path, cur, now=1050) == cur


def test_pick_session_switches_after_quiet(tmp_path):
    cur = make_session(tmp_path, "old", mtime=1000)
    new = make_session(tmp_path, "new", mtime=1030)
    assert pick_session(tmp_path, cur, now=1100) == new


def test_pick_session_first_choice_is_newest(tmp_path):
    make_session(tmp_path, "old", mtime=1000)
    new = make_session(tmp_path, "new", mtime=2000)
    assert pick_session(tmp_path, None, now=2001) == new
    assert pick_session(tmp_path / "empty", None, now=0) is None


def test_pinned_session_never_switches(tmp_path):
    make_session(tmp_path, "old", mtime=1000)
    make_session(tmp_path, "new", mtime=2000)
    w = Watcher(tmp_path, pinned="old")
    assert w.poll(now=9999).session_id == "old"


def test_session_switch_discards_old_agents(tmp_path):
    make_session(tmp_path, "old", main_blocks=[agent_call("toolu_1", "x")], mtime=1000)
    add_sub(tmp_path, "old", "a1", "toolu_1")
    w = Watcher(tmp_path)
    assert "a1" in by_id(w.poll(now=1001))
    make_session(tmp_path, "new", mtime=2000)
    snap = w.poll(now=2001 + 100)
    assert snap.session_id == "new" and [a.id for a in snap.agents] == ["main"]


def test_no_session_yet_returns_none(tmp_path):
    assert Watcher(tmp_path).poll() is None


# ---- Task 8 step 0: profile fallback when CLAUDE_CONFIG_DIR is unset ----
from agent_panel.session import resolve_project


def profile(home, name, mtime):
    proj = home / name / "projects" / "-work-demo"
    make_session(proj, "s1", mtime=mtime)
    return proj


def test_config_dir_fallback_picks_newest_profile(tmp_path, monkeypatch):
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    profile(tmp_path, ".claude", 1000)
    newest = profile(tmp_path, ".claude-work", 2000)
    profile(tmp_path, ".claude-old", 500)
    assert resolve_project(Path("/work/demo"), home=tmp_path) == newest


def test_env_config_dir_wins(tmp_path, monkeypatch):
    mine = profile(tmp_path, ".claude", 1000)
    profile(tmp_path, ".claude-work", 2000)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / ".claude"))
    assert resolve_project(Path("/work/demo"), home=tmp_path) == mine


def test_explicit_config_dir_beats_env(tmp_path, monkeypatch):
    profile(tmp_path, ".claude", 1000)
    work = profile(tmp_path, ".claude-work", 2000)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / ".claude"))
    assert resolve_project(Path("/work/demo"), explicit=tmp_path / ".claude-work", home=tmp_path) == work


def test_fallback_with_no_profile_has_the_project(tmp_path, monkeypatch):
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    assert resolve_project(Path("/work/demo"), home=tmp_path) == tmp_path / ".claude" / "projects" / "-work-demo"


def test_watcher_accepts_a_resolver_and_finds_a_late_profile(tmp_path):
    state = {"dir": tmp_path / "nowhere"}
    w = Watcher(lambda: state["dir"])
    assert w.poll() is None
    state["dir"] = tmp_path / "real"
    make_session(state["dir"], "late")
    assert w.poll().session_id == "late"


def test_replaced_transcript_does_not_refire_the_cannon(tmp_path):
    p = make_session(tmp_path, "s1", main_blocks=[advisor_call(), advisor_call("2026-11-13T12:00:05Z")])
    w = Watcher(tmp_path)
    assert w.poll().new_shots == 0
    write_jsonl(p, [assistant("m1", OPUS, U, blocks=[advisor_call()])])  # replaced, smaller
    snap = w.poll()
    assert snap.new_shots == 0 and snap.agents[0].advisor_calls == 1
    with open(p, "a") as f:
        f.write(json.dumps(assistant("m2", OPUS, U, blocks=[advisor_call("2026-11-13T13:00:00Z")])) + "\n")
    assert w.poll().new_shots == 1  # genuinely new calls still fire afterwards


def test_pinned_session_found_in_a_profile_that_is_not_newest(tmp_path, monkeypatch):
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    cwd = Path("/work/demo")
    make_session(tmp_path / ".claude" / "projects" / "-work-demo", "newer", mtime=2000)
    make_session(tmp_path / ".claude-work" / "projects" / "-work-demo", "wanted", mtime=1000)
    w = Watcher(lambda: resolve_project(cwd, home=tmp_path, session="wanted"), pinned="wanted")
    assert w.poll().session_id == "wanted"


def test_done_subagent_finished_at_is_its_last_entry(tmp_path):
    from datetime import datetime
    make_session(tmp_path)
    add_sub(tmp_path, "sess1", "a1", finished=True)
    add_sub(tmp_path, "sess1", "a2", finished=False)
    snap = by_id(Watcher(tmp_path).poll())
    assert snap["a1"].finished_at == datetime.fromisoformat("2026-11-13T12:00:00+00:00").timestamp()
    assert snap["a2"].finished_at is None


def test_done_subagent_without_timestamps_falls_back_to_file_mtime(tmp_path):
    make_session(tmp_path)
    add_sub(tmp_path, "sess1", "a1", finished=True)
    f = tmp_path / "sess1" / "subagents" / "agent-a1.jsonl"
    write_jsonl(f, [{"type": "user", "message": {"content": "hi"}}])
    os.utime(f, (5000, 5000))
    assert by_id(Watcher(tmp_path).poll())["a1"].finished_at == 5000


def test_malformed_timestamps_do_not_crash_epoch():
    from agent_panel.session import _epoch
    assert [_epoch(t) for t in ("not a date", 12345, ["x"], None)] == [None, None, None, None]


def test_snapshot_reports_the_main_turn_ended(tmp_path):
    e = assistant("m1", OPUS, U)
    e["message"]["stop_reason"] = "end_turn"
    write_jsonl(tmp_path / "sess1.jsonl", [e])
    assert Watcher(tmp_path).poll().turn_ended is True
    make_session(tmp_path)  # its one message has no stop_reason: still mid-turn
    assert Watcher(tmp_path).poll().turn_ended is False


def test_two_subagents_that_claim_each_other_show_under_main(tmp_path):
    make_session(tmp_path)
    add_sub(tmp_path, "sess1", "a1", "toolu_b", blocks=[agent_call("toolu_a", "spawn b")])
    add_sub(tmp_path, "sess1", "b1", "toolu_a", blocks=[agent_call("toolu_b", "spawn a")])
    add_sub(tmp_path, "sess1", "c1", "toolu_c")
    write_jsonl(tmp_path / "sess1" / "subagents" / "agent-b1.jsonl",
                [assistant("s-b1", SONNET, U, blocks=[agent_call("toolu_b", "spawn a"), agent_call("toolu_c", "spawn c")])])
    a = by_id(Watcher(tmp_path).poll())
    assert {"a1", "b1", "c1"} <= set(a)
    # One of the pair goes back under main, unlinked; the other and c1 keep the parent they claim.
    top = [k for k in ("a1", "b1") if a[k].parent_id == "main"]
    assert len(top) == 1 and not a[top[0]].linked
    other = "b1" if top == ["a1"] else "a1"
    assert a[other].parent_id == top[0] and a[other].depth == 2
    assert a["c1"].parent_id == "b1"


def test_a_transcript_replaced_by_a_larger_file_is_read_from_the_start(tmp_path):
    p = make_session(tmp_path)
    w = Watcher(tmp_path)
    assert w.poll().agents[0].burn == 10
    new = tmp_path / "new.tmp"
    write_jsonl(new, [assistant(f"z{i}", OPUS, {"output_tokens": 1}) for i in range(40)])
    os.replace(new, p)  # a new file in its place, larger than the offset already read
    assert w.poll().agents[0].burn == 40


# ---- Running means busy: an open tool call, a reply owed, a live watch, or a recent write ----
from agent_panel.session import REPLY_STALE_S, TOOL_STALE_S
from tests.test_transcript import ended, tool_result, tool_use, user_text


def session_file(proj: Path, entries, mtime, sid="sess1"):
    p = proj / f"{sid}.jsonl"
    write_jsonl(p, entries)
    os.utime(p, (mtime, mtime))
    return p


def sub_file(proj: Path, aid, entries, mtime, tool_use_id="toolu_1", finished=None, sid="sess1"):
    d = proj / sid / "subagents"
    write_jsonl(d / f"agent-{aid}.jsonl", entries)
    os.utime(d / f"agent-{aid}.jsonl", (mtime, mtime))
    m = {"agentType": "general-purpose", "description": "Review the diff", "toolUseId": tool_use_id}
    if finished is not None:
        m["finished"] = finished
    (d / f"agent-{aid}.meta.json").write_text(json.dumps(m))


def test_stale_bounds():
    # Long test suites and CI waits run for many minutes; half an hour without a single write or result is not a
    # tool call any more. A reply owed is seconds, rarely minutes.
    assert TOOL_STALE_S == 30 * 60 and REPLY_STALE_S == 5 * 60


def test_a_tool_call_in_progress_with_a_quiet_transcript_is_running(tmp_path):
    session_file(tmp_path, [tool_use("t1")], mtime=1000)
    w = Watcher(tmp_path)
    assert by_id(w.poll(now=1000 + 600))["main"].status == "running"
    assert by_id(w.poll(now=1000 + TOOL_STALE_S - 1))["main"].status == "running"


def test_a_stale_tool_call_falls_back_to_idle(tmp_path):
    # A crash or a killed tool writes nothing more: after the bound the ship anchors.
    session_file(tmp_path, [tool_use("t1")], mtime=1000)
    assert by_id(Watcher(tmp_path).poll(now=1000 + TOOL_STALE_S))["main"].status == "idle"


def test_an_ended_turn_is_idle(tmp_path):
    session_file(tmp_path, [tool_use("t1"), tool_result("t1"), ended()], mtime=1000)
    w = Watcher(tmp_path)
    assert by_id(w.poll(now=1000 + 20))["main"].status == "idle"
    assert by_id(w.poll(now=1000 + 5))["main"].status == "running"  # a fresh write still counts


def test_an_interrupted_turn_is_idle(tmp_path):
    session_file(tmp_path, [tool_use("t1"), tool_result("t1"),
                            user_text([{"type": "text", "text": "[Request interrupted by user for tool use]"}])], mtime=1000)
    assert by_id(Watcher(tmp_path).poll(now=1000 + 20))["main"].status == "idle"


def test_a_reply_owed_is_running_until_its_bound(tmp_path):
    # The model is thinking after a tool result: its next write can be a minute away.
    session_file(tmp_path, [tool_use("t1"), tool_result("t1")], mtime=1000)
    w = Watcher(tmp_path)
    assert by_id(w.poll(now=1000 + 90))["main"].status == "running"
    assert by_id(w.poll(now=1000 + REPLY_STALE_S))["main"].status == "idle"


def monitor(deadline_ms=600000, persistent=False):
    return [tool_use("tm", "Monitor"), tool_result("tm", ts="2026-11-13T12:00:00.000Z",
                                                  result={"taskId": "m1", "timeoutMs": deadline_ms, "persistent": persistent}),
            ended("watching the inbox")]


T0 = 1794571200.0  # 2026-11-13T12:00:00Z


def test_a_controller_on_watch_is_running_until_the_watch_expires(tmp_path):
    # Its turn ended, but a Monitor will wake it: it waits on its fleet, not on the user.
    session_file(tmp_path, monitor(), mtime=T0)
    w = Watcher(tmp_path)
    a = by_id(w.poll(now=T0 + 300))["main"]
    assert (a.status, a.watching) == ("running", True)
    a = by_id(w.poll(now=T0 + 600))["main"]
    assert (a.status, a.watching) == ("idle", False)


def test_a_persistent_watch_is_bounded_by_the_quiet(tmp_path):
    session_file(tmp_path, monitor(persistent=True), mtime=T0)
    w = Watcher(tmp_path)
    assert by_id(w.poll(now=T0 + TOOL_STALE_S - 1))["main"].status == "running"
    assert by_id(w.poll(now=T0 + TOOL_STALE_S))["main"].status == "idle"


def test_a_busy_session_is_not_watching(tmp_path):
    session_file(tmp_path, [tool_use("t1")], mtime=1000)
    assert by_id(Watcher(tmp_path).poll(now=1000 + 60))["main"].watching is False


def test_a_subagent_in_a_quiet_tool_call_is_running(tmp_path):
    session_file(tmp_path, [agent_call_entry("toolu_1")], mtime=1000)
    sub_file(tmp_path, "a1", [tool_use("t-sub")], mtime=1000)  # meta lacks `finished`, file quiet 10 min
    w = Watcher(tmp_path)
    assert by_id(w.poll(now=1000 + 600))["a1"].status == "running"
    assert by_id(w.poll(now=1000 + TOOL_STALE_S))["a1"].status == "done"  # stale: never running forever


def test_a_subagents_finished_marker_stays_authoritative(tmp_path):
    session_file(tmp_path, [agent_call_entry("toolu_1")], mtime=1000)
    sub_file(tmp_path, "a1", [tool_use("t-sub")], mtime=1000, finished=True)
    assert by_id(Watcher(tmp_path).poll(now=1000 + 5))["a1"].status == "done"


def test_a_subagent_that_ended_its_turn_is_done_once_quiet(tmp_path):
    session_file(tmp_path, [agent_call_entry("toolu_1")], mtime=1000)
    sub_file(tmp_path, "a1", [tool_use("t-sub"), tool_result("t-sub"), ended("report")], mtime=1000)
    w = Watcher(tmp_path)
    assert by_id(w.poll(now=1000 + 10))["a1"].status == "running"
    assert by_id(w.poll(now=1000 + 30))["a1"].status == "done"


def test_finished_false_is_not_running_forever(tmp_path):
    session_file(tmp_path, [agent_call_entry("toolu_1")], mtime=1000)
    sub_file(tmp_path, "a1", [ended("report")], mtime=1000, finished=False)
    assert by_id(Watcher(tmp_path).poll(now=1000 + 120))["a1"].status == "done"


def test_main_waiting_on_its_running_subagent_is_running_past_the_bound(tmp_path):
    # A foreground Agent call keeps main's file quiet for as long as the subagent works.
    session_file(tmp_path, [agent_call_entry("toolu_1")], mtime=1000)
    sub_file(tmp_path, "a1", [tool_use("t-sub")], mtime=1000 + TOOL_STALE_S + 50)
    snap = Watcher(tmp_path).poll(now=1000 + TOOL_STALE_S + 60)
    assert by_id(snap)["a1"].status == "running"
    assert by_id(snap)["main"].status == "running"


def agent_call_entry(tid):
    e = assistant("m-" + tid, OPUS, U, blocks=[agent_call(tid, "Review the diff")])
    e["message"]["stop_reason"] = "tool_use"
    return e
