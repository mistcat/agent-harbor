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
