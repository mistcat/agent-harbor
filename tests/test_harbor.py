import asyncio
import re
from pathlib import Path

from agent_panel.app import AgentPanelApp
from agent_panel.boats import SPRITES, TIER_GALLEON, TIER_SLOOP, tier
from agent_panel.harbor import Boat, layout, render_harbor
from agent_panel.session import Watcher
from tests.helpers import agent_call
from tests.test_session import add_sub, make_session
from tests.test_tree import ag


def agents(n, burn=1000):
    return [ag("main", None, 0, "main", "opus 5.5", burn=burn)] + [ag(f"a{i}", "main", 1, f"t{i}", burn=burn) for i in range(1, n)]


def test_tier_thresholds():
    assert tier(0) == "rowboat"
    assert tier(TIER_SLOOP) == "sloop" == tier(50_000)
    assert tier(TIER_GALLEON) == "galleon" == tier(500_000)
    assert tier(TIER_SLOOP - 1) == "rowboat"


def test_sprites_are_rectangles_of_3_to_5_lines():
    assert set(SPRITES) == {"rowboat", "sloop", "galleon"}
    for lines in SPRITES.values():
        assert 3 <= len(lines) <= 5 and len({len(l) for l in lines}) == 1


def test_layout_gives_every_agent_a_boat_when_room():
    boats, over = layout(agents(3), 50, 10, {})
    assert set(boats) == {"main", "a1", "a2"} and over == 0
    assert len({(b.lane, round(b.x)) for b in boats.values()}) == 3


def test_upgrade_keeps_position():
    prev = {"a1": Boat("a1", 17.0, 0, 1, "rowboat")}
    boats, _ = layout([ag("main", None, 0, "main"), ag("a1", "main", 1, "t", burn=60_000)], 50, 10, prev)
    b = boats["a1"]
    assert (b.x, b.lane, b.tier) == (17.0, 0, "sloop")


def test_overflow_marker():
    ags = agents(25)
    boats, over = layout(ags, 50, 10, {})
    assert over > 0 and len(boats) + over == 25
    text = render_harbor(ags, boats, 50, 10, 0).plain
    assert re.search(r"\+\d+", text)


def test_render_fits_box():
    for w, h in [(50, 10), (30, 8), (80, 20), (12, 8)]:
        ags = agents(6, burn=600_000)
        boats, _ = layout(ags, w, h, {})
        lines = render_harbor(ags, boats, w, h, 3).plain.split("\n")
        assert len(lines) == h and all(len(l) <= w for l in lines)


def test_render_shows_each_tier_sprite():
    ags = [ag("main", None, 0, "main", burn=1), ag("a1", "main", 1, "t", burn=60_000), ag("a2", "main", 1, "t", burn=900_000)]
    boats, _ = layout(ags, 60, 10, {})
    plain = render_harbor(ags, boats, 60, 10, 0).plain
    assert "▲" in plain and "~" in plain


def test_harbor_hidden_under_8_rows(tmp_path):
    make_session(tmp_path, "s1")

    async def go(height):
        app = AgentPanelApp(Watcher(tmp_path), Path("/p/demo"))
        async with app.run_test(size=(50, height)) as pilot:
            await pilot.pause(0.7)
            return app.query_one("#harbor").display

    assert asyncio.run(go(24)) is True
    assert asyncio.run(go(8)) is False


def test_harbor_fills_its_box_exactly(tmp_path):
    # Regression: tree line count was off by one, so the harbor's waterline row was clipped.
    make_session(tmp_path, "s1", main_blocks=[agent_call("t1", "x")])
    add_sub(tmp_path, "s1", "a1", "t1")

    async def go():
        app = AgentPanelApp(Watcher(tmp_path), Path("/p/demo"))
        async with app.run_test(size=(50, 30)) as pilot:
            await pilot.pause(0.8)
            h = app.query_one("#harbor")
            return len(str(h.content).split("\n")), h.region.height

    lines, region = asyncio.run(go())
    assert lines == region


def test_first_boats_sit_on_the_waterline_lane():
    ags = agents(2)
    boats, _ = layout(ags, 50, 30, {})
    assert {b.lane for b in boats.values()} == {0}
    lines = render_harbor(ags, boats, 50, 30, 0).plain.split("\n")
    assert "\\" in lines[-2] and set(lines[-1]) == {"~"}
