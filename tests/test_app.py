import json
import asyncio
from pathlib import Path

from agent_panel.app import AgentPanelApp
from agent_panel.session import Watcher
from tests.helpers import agent_call, assistant, write_jsonl
from tests.test_session import add_sub, make_session


def run(coro):
    return asyncio.run(coro)


def test_app_waiting_message():
    async def go():
        app = AgentPanelApp(None, Path("/some/dir"))
        async with app.run_test(size=(50, 20)) as pilot:
            await pilot.pause()
            assert "waiting for a Claude session in /some/dir" in str(app.query_one("#tree").content)
    run(go())


def test_app_renders_fixture_session(tmp_path):
    make_session(tmp_path, "abcdef123456", main_blocks=[agent_call("toolu_1", "audit TUIs")])
    add_sub(tmp_path, "abcdef123456", "a1", "toolu_1", desc="audit TUIs")

    async def go():
        app = AgentPanelApp(Watcher(tmp_path), Path("/proj/demo"))
        async with app.run_test(size=(60, 20)) as pilot:
            await pilot.pause(0.7)
            text = str(app.query_one("#tree").content)
            assert "audit TUIs" in text and "opus 5.5" in text
            assert str(app.query_one("#header").content) == "agent-panel · abcdef12 · demo"
    run(go())


def test_app_survives_resize(tmp_path):
    make_session(tmp_path, "s1")
    add_sub(tmp_path, "s1", "a1", desc="x" * 100)

    async def go():
        app = AgentPanelApp(Watcher(tmp_path), Path("/proj/demo"))
        async with app.run_test(size=(80, 30)) as pilot:
            await pilot.pause(0.6)
            await pilot.resize_terminal(30, 6)
            await pilot.pause(0.6)
            assert app.is_running
    run(go())


def test_app_picks_up_session_appearing_later(tmp_path):
    w = Watcher(tmp_path)

    async def go():
        app = AgentPanelApp(w, Path("/proj/demo"))
        async with app.run_test(size=(60, 20)) as pilot:
            await pilot.pause(0.6)
            assert "waiting for a Claude session" in str(app.query_one("#tree").content)
            make_session(tmp_path, "late")
            await pilot.pause(1.2)
            assert "opus 5.5" in str(app.query_one("#tree").content)
    run(go())


def test_app_survives_odd_shaped_entries(tmp_path):
    """Valid JSON in shapes the reader doesn't expect must not kill the poll timer."""
    make_session(tmp_path, "s1", main_blocks=[agent_call("toolu_1", "audit TUIs")])
    add_sub(tmp_path, "s1", "a1", "toolu_1", desc="audit TUIs")
    main = tmp_path / "s1.jsonl"
    sub_dir = tmp_path / "s1" / "subagents"

    async def go():
        app = AgentPanelApp(Watcher(tmp_path), Path("/proj/demo"))
        async with app.run_test(size=(60, 20)) as pilot:
            await pilot.pause(0.7)
            odd = [
                {"type": "assistant", "message": "not an object"},
                {"type": "assistant", "message": {"id": "x", "usage": None, "content": "text"}},
                {"type": "assistant", "message": {"id": "y", "usage": {"input_tokens": "lots"}, "content": [None, 3]}},
                [1, 2, 3],
                "just a string",
            ]
            with open(main, "a") as f:
                for e in odd:
                    f.write(json.dumps(e) + "\n")
            (sub_dir / "agent-a1.meta.json").write_text(json.dumps([1, 2]))
            await pilot.pause(1.2)
            assert app.is_running
            text = str(app.query_one("#tree").content)
            # Main keeps its burn; the subagent with garbage meta stays listed, falling back to its id.
            assert "main" in text and "a1" in text
    run(go())


def test_app_says_a_pinned_session_was_not_found(tmp_path):
    make_session(tmp_path, "other")

    async def go():
        app = AgentPanelApp(Watcher(tmp_path, pinned="nope1234"), Path("/proj/demo"), pinned="nope1234")
        async with app.run_test(size=(80, 20)) as pilot:
            await pilot.pause(0.6)
            text = str(app.query_one("#tree").content)
            assert "nope1234" in text and "waiting for a Claude session" not in text
    run(go())


def test_app_header_updates_only_when_it_changes(tmp_path):
    make_session(tmp_path, "abcdef123456")

    async def go():
        app = AgentPanelApp(Watcher(tmp_path), Path("/proj/demo"))
        async with app.run_test(size=(60, 20)) as pilot:
            await pilot.pause(0.6)
            header = app.query_one("#header")
            calls = []
            orig = header.update
            header.update = lambda *a, **k: (calls.append(a), orig(*a, **k))
            await pilot.pause(1.2)
            assert calls == []
    run(go())
