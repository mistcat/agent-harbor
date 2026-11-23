import json

from agent_panel.transcript import FileStats, Tail, fold, short_model
from tests.helpers import advisor_call, agent_call, assistant, write_jsonl

U1 = {"input_tokens": 10, "cache_creation_input_tokens": 100, "cache_read_input_tokens": 1000, "output_tokens": 5}


def test_usage_counted_once_per_message_id():
    s = FileStats()
    fold(s, [assistant("m1", "claude-sonnet-5-5", U1), assistant("m1", "claude-sonnet-5-5", U1),
             assistant("m2", "claude-sonnet-5-5", {"input_tokens": 1, "output_tokens": 2})], skip_sidechain=False)
    assert s.burn == 118
    assert s.cache_read == 1000


def test_sidechain_skipped_when_asked():
    s = FileStats()
    fold(s, [assistant("m1", "claude-sonnet-5-5", U1, sidechain=True)], skip_sidechain=True)
    assert s.burn == 0


def test_latest_model_and_effort_win():
    s = FileStats()
    fold(s, [assistant("m1", "claude-sonnet-5-5", U1, effort="low"),
             assistant("m2", "claude-opus-5-5", U1, effort="high")], skip_sidechain=False)
    assert (s.model, s.effort) == ("claude-opus-5-5", "high")


def test_agent_calls_indexed_by_tool_id():
    s = FileStats()
    fold(s, [assistant("m1", "claude-opus-5-5", U1, blocks=[agent_call("toolu_1", "grep", "haiku")])], skip_sidechain=False)
    assert s.agent_calls["toolu_1"]["description"] == "grep"
    assert s.agent_calls["toolu_1"]["model"] == "haiku"


def test_advisor_calls_counted_and_new_returned():
    s = FileStats()
    first = fold(s, [assistant("m1", "claude-opus-5-5", U1, blocks=[advisor_call("2026-11-13T12:00:01Z"), advisor_call("2026-11-13T12:00:02Z")])], False)
    later = fold(s, [assistant("m2", "claude-opus-5-5", U1, blocks=[advisor_call("2026-11-13T12:00:09Z")], ts="2026-11-13T12:00:09Z")], False)
    assert (first, later) == (2, 1)
    assert s.advisor_calls == 3
    assert s.last_advisor_at == "2026-11-13T12:00:09Z"


def test_advisor_model_tracked():
    s = FileStats()
    fold(s, [assistant("m1", "claude-opus-5-5", U1, advisor_model="claude-fable-5-1")], False)
    assert s.advisor_model == "claude-fable-5-1"


def test_tail_keeps_partial_line(tmp_path):
    p = tmp_path / "a.jsonl"
    whole = json.dumps({"n": 2})
    write_jsonl(p, [{"n": 1}], partial_tail=whole[:5])
    t = Tail(p)
    assert t.poll() == [{"n": 1}]
    with open(p, "a") as f:
        f.write(whole[5:] + "\n")
    assert t.poll() == [{"n": 2}]


def test_tail_resets_when_file_shrinks(tmp_path):
    p = tmp_path / "a.jsonl"
    write_jsonl(p, [{"n": 1}, {"n": 2}, {"n": 3}])
    t = Tail(p)
    assert len(t.poll()) == 3
    write_jsonl(p, [{"n": 9}])
    assert t.poll() == [{"n": 9}]


def test_tail_skips_bad_json(tmp_path):
    p = tmp_path / "a.jsonl"
    p.write_text('{"n": 1}\nnot json\n{"n": 2}\n')
    assert Tail(p).poll() == [{"n": 1}, {"n": 2}]


def test_tail_missing_file_is_empty(tmp_path):
    assert Tail(tmp_path / "nope.jsonl").poll() == []


def test_short_model():
    assert short_model("claude-sonnet-5-5") == "sonnet 5.5"
    assert short_model("claude-opus-5-5") == "opus 5.5"
    assert short_model("claude-fable-5-1") == "fable 5.1"
    assert short_model(None) == "?"
    assert short_model("gpt-weird") == "gpt-weird"


def test_short_model_two_part_ids():
    # Real transcripts contain ids with no minor version, e.g. claude-opus-5.
    assert short_model("claude-opus-5") == "opus 5"
    assert short_model("claude-sonnet-5") == "sonnet 5"


def test_turn_ended_follows_stop_reason_and_prompts():
    def asst(mid, reason):
        e = assistant(mid, "claude-opus-5-5", U1)
        e["message"]["stop_reason"] = reason
        return e

    def user(content, meta=False):
        return {"type": "user", "isMeta": meta, "message": {"role": "user", "content": content}}

    s = FileStats()
    fold(s, [user("hi"), asst("m1", "tool_use")], skip_sidechain=True)
    assert s.turn_ended is False
    fold(s, [user([{"type": "tool_result", "tool_use_id": "t", "content": "ok"}]), asst("m2", "end_turn")], skip_sidechain=True)
    assert s.turn_ended is True
    fold(s, [user("ok", meta=True)], skip_sidechain=True)
    assert s.turn_ended is True  # injected meta entries are not prompts
    fold(s, [user("next question")], skip_sidechain=True)
    assert s.turn_ended is False
    fold(s, [asst("m3", "end_turn")], skip_sidechain=True)
    assert s.turn_ended is True


# ---- What a session is busy with: open tool calls, a reply owed, background watches ----
from datetime import datetime, timezone


def tool_use(tid, name="Bash", stop="tool_use", ts="2026-11-13T12:00:00.000Z"):
    e = assistant("m-" + tid, "claude-opus-5-5", U1, ts=ts, blocks=[{"type": "tool_use", "id": tid, "name": name, "input": {}}])
    e["message"]["stop_reason"] = stop
    return e


def tool_result(tid, ts="2026-11-13T12:00:01.000Z", result=None):
    e = {"type": "user", "timestamp": ts,
         "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tid, "content": "ok"}]}}
    if result is not None:
        e["toolUseResult"] = result
    return e


def user_text(text, **kw):
    return {"type": "user", "timestamp": "2026-11-13T12:00:02.000Z", "message": {"role": "user", "content": text}, **kw}


def ended(text="done"):
    e = assistant("m-end-" + text, "claude-opus-5-5", U1, blocks=[{"type": "text", "text": text}])
    e["message"]["stop_reason"] = "end_turn"
    return e


def test_open_tool_calls_are_tracked_until_their_result():
    # Real transcripts write one content block per assistant entry, so parallel calls span entries.
    s = FileStats()
    fold(s, [tool_use("t1"), tool_use("t2")], skip_sidechain=False)
    assert s.open_tools == {"t1", "t2"}
    fold(s, [tool_result("t1")], skip_sidechain=False)
    assert s.open_tools == {"t2"}


def test_the_advisor_is_no_open_call():
    s = FileStats()
    e = assistant("m1", "claude-opus-5-5", U1, blocks=[advisor_call()])
    e["message"]["stop_reason"] = "tool_use"
    fold(s, [e], skip_sidechain=False)
    assert s.open_tools == set()


def test_a_tool_result_or_a_prompt_owes_the_model_a_reply():
    s = FileStats()
    fold(s, [tool_use("t1")], skip_sidechain=False)
    assert not s.awaiting_reply
    fold(s, [tool_result("t1")], skip_sidechain=False)
    assert s.awaiting_reply
    fold(s, [ended()], skip_sidechain=False)
    assert not s.awaiting_reply
    fold(s, [user_text("go on")], skip_sidechain=False)
    assert s.awaiting_reply
    fold(s, [ended(), user_text("<task-notification> <task-id>b1</task-id> </task-notification>")], skip_sidechain=False)
    assert s.awaiting_reply  # a background task waking the model


def test_local_commands_meta_entries_and_summaries_owe_no_reply():
    for e in (user_text("<bash-input>ls</bash-input>"), user_text("<bash-stdout>x</bash-stdout>"),
              user_text("<local-command-stdout>x</local-command-stdout>"), user_text("<command-name>/clear</command-name>"),
              user_text("This session is being continued from a previous conversation", isCompactSummary=True),
              user_text("Base directory for this skill", isMeta=True)):
        s = FileStats()
        fold(s, [ended(), e], skip_sidechain=False)
        assert not s.awaiting_reply, e


def test_an_interrupt_closes_the_calls_and_owes_nothing():
    for tail in ([user_text([{"type": "text", "text": "[Request interrupted by user]"}])],
                 [tool_result("t1"), user_text([{"type": "text", "text": "[Request interrupted by user for tool use]"}])]):
        s = FileStats()
        fold(s, [tool_use("t1"), *tail], skip_sidechain=False)
        assert s.open_tools == set() and not s.awaiting_reply, tail


def epoch(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()


def test_monitors_and_background_commands_are_watched_until_they_end():
    s = FileStats()
    fold(s, [tool_use("tm", "Monitor"), tool_result("tm", ts="2026-11-13T12:00:00.000Z",
                                                    result={"taskId": "m1", "timeoutMs": 600000, "persistent": False}),
             tool_use("tb"), tool_result("tb", ts="2026-11-13T12:01:00.000Z", result={"backgroundTaskId": "b1"})],
         skip_sidechain=False)
    start = epoch("2026-11-13T12:00:00.000Z")
    assert s.watches == {"m1": start + 600, "b1": start + 60 + 30 * 60}  # a background command: the stale bound
    fold(s, [user_text("<task-notification>\n<task-id>b1</task-id>\n<status>completed</status>\n</task-notification>")],
         skip_sidechain=False)
    assert set(s.watches) == {"m1"}
    fold(s, [user_text("<task-notification>\n<task-id>m1</task-id>\n<event>NEW REPORT: x</event>\n</task-notification>")],
         skip_sidechain=False)
    assert set(s.watches) == {"m1"}  # an event is not the end
    fold(s, [user_text("<task-notification>\n<task-id>m1</task-id>\n<event>[Monitor expired after 30m with 3 events "
                       "delivered. Re-arm it if you still need the watch.]</event>\n</task-notification>")],
         skip_sidechain=False)
    assert s.watches == {}


def test_a_persistent_monitor_and_a_stopped_task():
    s = FileStats()
    fold(s, [tool_use("tm", "Monitor"), tool_result("tm", ts="2026-11-13T12:00:00.000Z",
                                                    result={"taskId": "m1", "timeoutMs": 600000, "persistent": True})],
         skip_sidechain=False)
    assert s.watches == {"m1": None}  # no deadline of its own: only the transcript's quiet bounds it
    fold(s, [tool_use("ts", "TaskStop"), tool_result("ts", result={"task_id": "m1", "task_type": "monitor"})],
         skip_sidechain=False)
    assert s.watches == {}
