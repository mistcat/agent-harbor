import asyncio
import json
from pathlib import Path

from agent_panel.app import AgentPanelApp
from agent_panel.effects import Shot, advance, fire
from agent_panel.harbor import Boat, layout, render_harbor
from agent_panel.model import Agent
from agent_panel.session import Snapshot, Watcher
from tests.helpers import advisor_call, assistant
from tests.test_harbor import agents
from tests.test_session import make_session


def test_shot_arcs_and_splashes():
    shot = fire(Boat("main", 10.0, 0, 1, "sloop", True))
    assert shot.vx > 0
    ys, shots, states = [shot.y], [shot], []
    for _ in range(80):
        shots = advance(shots)
        if not shots:
            break
        ys.append(shots[0].y)
        states.append(shots[0].splash)
    assert max(ys) > ys[0]  # rises
    assert ys.index(max(ys)) < len(ys) - 1 and ys[-1] < max(ys)  # then falls
    assert any(s > 0 for s in states)  # splashes on the waterline
    assert shots == []  # and disappears


def test_shot_leaves_the_left_gunport_when_sailing_left():
    shot = fire(Boat("main", 30.0, 0, -1, "rowboat", True))
    assert shot.vx < 0 and shot.x < 30


def test_render_draws_shot_and_flash():
    ags = agents(1)
    boats, _ = layout(ags, 60, 14, {})
    plain = render_harbor(ags, boats, 60, 14, 0).plain
    shot = Shot(x=30.0, y=3.0, vx=1.0, age=2)
    with_shot = render_harbor(ags, boats, 60, 14, 0, shots=[shot]).plain
    assert with_shot != plain and "*" in with_shot
    flashed = render_harbor(ags, boats, 60, 14, 0, flash=True).plain
    assert flashed != plain


class Stub:
    """Stands in for a Watcher: yields scripted snapshots, then repeats the last one."""

    def __init__(self, *shots):
        self.shots = list(shots)
        self.n = 0

    def poll(self, now=None):
        s = self.shots[min(self.n, len(self.shots) - 1)]
        self.n += 1
        return s


def snap(new_shots):
    a = Agent("main", None, 0, "main", "x", "opus 5.5", "medium", "running", 100, 0, 2, None, True)
    return Snapshot("s1", [a], new_shots, "fable 5.1")


class CountingBoomer:
    def __init__(self):
        self.calls = 0

    def boom(self, now):
        self.calls += 1
        return True


def run_app(watcher, steps, boomer=None, size=(60, 30)):
    async def go():
        app = AgentPanelApp(watcher, Path("/p/demo"), boomer=boomer or CountingBoomer())
        async with app.run_test(size=size) as pilot:
            await steps(app, pilot)
            return app
    return asyncio.run(go())


def test_no_fire_on_first_load():
    boomer = CountingBoomer()

    async def steps(app, pilot):
        await pilot.pause(0.4)
        assert app.shots == [] and boomer.calls == 0

    run_app(Stub(snap(0)), steps, boomer)


def test_one_shot_per_new_advisor_call():
    boomer = CountingBoomer()
    w = Stub(snap(0), snap(0), snap(2), snap(0))
    seen = []

    async def steps(app, pilot):
        for _ in range(30):
            await pilot.pause(0.1)
            seen.append(len(app.shots))
            if boomer.calls:
                break

    run_app(w, steps, boomer)
    assert max(seen) == 2 and boomer.calls == 1  # two shots, one boom


def test_real_watcher_only_fires_for_appended_call(tmp_path):
    p = make_session(tmp_path, "s1", main_blocks=[advisor_call()])  # a past call: must not fire
    boomer = CountingBoomer()

    async def steps(app, pilot):
        await pilot.pause(0.7)
        assert boomer.calls == 0
        with open(p, "a") as f:
            f.write(json.dumps(assistant("m9", "claude-opus-5-5", {"output_tokens": 1}, blocks=[advisor_call("2026-11-13T13:00:00Z")])) + "\n")
        for _ in range(15):
            await pilot.pause(0.1)
            if boomer.calls:
                break
        assert boomer.calls == 1

    run_app(Watcher(tmp_path), steps, boomer)
