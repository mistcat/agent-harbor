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
    assert tier(TIER_GALLEON) == "galleon" == tier(300_000)
    assert tier(TIER_SLOOP - 1) == "rowboat"


def test_sprites_are_rectangles_of_3_to_6_lines():
    assert set(SPRITES) == {"rowboat", "sloop", "galleon"} | {"main_rowboat", "main_sloop", "main_galleon"}
    for lines in SPRITES.values():
        assert 3 <= len(lines) <= 6 and len({len(l) for l in lines}) == 1


def test_galleon_is_one_tall_sail_no_wider_than_before():
    g = SPRITES["galleon"]
    assert len(g[0]) <= 9 and len(g) > len(SPRITES["sloop"]) and len(g[0]) >= len(SPRITES["sloop"][0])


def test_skull_is_one_cell_wide():
    from rich.cells import cell_len
    assert cell_len("☠") == 1
    from agent_panel.harbor import SKULL
    assert SKULL == "☠"


def test_main_stern_deck_is_clear_for_the_captain():
    from agent_panel.boats import STERN_W
    for t in ("rowboat", "sloop", "galleon"):
        lines = SPRITES["main_" + t]
        assert all(l[:STERN_W + 1].strip() == "" for l in lines[:-1])  # nothing above the stern hull
        assert len(lines[0]) == len(SPRITES[t][0]) + STERN_W + 1


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
    assert boats["main"].lane == 0 and boats["a1"].lane <= 1  # a child may sail one lane above its parent
    lines = render_harbor(ags, boats, 50, 30, 0).plain.split("\n")
    assert any("\\" in l for l in lines[-3:-1]) and set(lines[-1]) == {"~"}  # hull rests on the water (bob moves it a row)


# ---- Task 6: motion, wake, anchored zzz, frame rate ----
from agent_panel.app import fps_for
from agent_panel.harbor import step


def sailing(n_done=0):
    ags = [ag("main", None, 0, "main", "opus 5.5", burn=1, status="running")]
    ags += [ag(f"d{i}", "main", 1, "fin", burn=1, status="done") for i in range(n_done)]
    return ags


def test_running_boat_moves_done_boat_stays():
    ags = sailing(1)
    boats, _ = layout(ags, 60, 10, {})
    before = {k: b.x for k, b in boats.items()}
    step(boats, ags, 1.0, 60)
    assert boats["main"].x != before["main"]
    assert boats["d0"].x == before["d0"]


def test_boat_turns_at_edge():
    ags = sailing()
    boats, _ = layout(ags, 40, 10, {})
    w = len(SPRITES["main_rowboat"][0])
    boats["main"].x, boats["main"].direction = 36.0, 1
    step(boats, ags, 1.0, 40)
    assert boats["main"].direction == -1 and boats["main"].x <= 40 - w
    boats["main"].x = 0.5
    step(boats, ags, 1.0, 40)
    assert boats["main"].direction == 1 and boats["main"].x >= 0


def hull_line(boats, ags, frame=0, width=60):
    lines = render_harbor(ags, boats, width, 10, frame).plain.split("\n")
    return next(l for l in lines if "\\_" in l)


def test_wake_behind_moving_boat():
    ags = sailing()
    w = len(SPRITES["main_rowboat"][0])
    for direction in (1, -1):
        boats, _ = layout(ags, 60, 10, {})
        boats["main"].x, boats["main"].direction = 30.0, direction
        line = hull_line(boats, ags)
        x = line.index("\\_")
        behind = line[x - 3:x] if direction == 1 else line[x + w:x + w + 3]
        ahead = line[x + w:x + w + 3] if direction == 1 else line[x - 3:x]
        assert behind.strip() and not ahead.strip()


def test_no_wake_for_anchored_boat():
    done = [ag("d", None, 0, "x", burn=1, status="done")]
    boats, _ = layout(done, 60, 10, {})
    boats["d"].x = 30.0
    line = hull_line(boats, done)
    x = line.index("\\_")
    assert not line[x - 3:x].strip() and not line[x + 5:x + 8].strip()


def test_anchored_boat_shows_zzz():
    done = [ag("d", None, 0, "x", burn=1, status="done")]
    boats, _ = layout(done, 60, 10, {})
    assert "zzz" in render_harbor(done, boats, 60, 10, 0).plain
    run = sailing()
    boats, _ = layout(run, 60, 10, {})
    assert "zzz" not in render_harbor(run, boats, 60, 10, 0).plain


def test_anchored_boat_bobs():
    done = [ag("d", None, 0, "x", burn=1, status="done")]
    boats, _ = layout(done, 60, 10, {})
    assert render_harbor(done, boats, 60, 10, 0).plain != render_harbor(done, boats, 60, 10, 4).plain


def test_boats_stay_on_the_water_when_pane_grows():
    ags = agents(2)
    boats, _ = layout(ags, 50, 12, {})
    boats, _ = layout(ags, 50, 30, boats)
    lines = render_harbor(ags, boats, 50, 30, 0).plain.split("\n")
    assert any("\\" in l for l in lines[-3:-1])


def test_fps_for():
    assert fps_for(sailing()) == 10
    assert fps_for([ag("d", None, 0, "x", status="done"), ag("i", None, 0, "x", status="idle")]) == 2


# ---- Task 8: flotillas ----
from agent_panel.harbor import SLOT_W


def fleet(child_status="running", parent_status="running"):
    return [ag("main", None, 0, "main", "opus 5.5", burn=1, status=parent_status),
            ag("a1", "main", 1, "kid", burn=1, status=child_status)]


def sail(ags, boats, seconds, width=80, dt=0.1):
    for _ in range(int(seconds / dt)):
        step(boats, ags, dt, width)


def test_children_sail_behind_parent():
    ags = fleet()
    for direction in (1, -1):
        boats, _ = layout(ags, 80, 20, {})
        boats["main"].x, boats["main"].direction = 40.0, direction
        sail(ags, boats, 4.0)
        p, c = boats["main"], boats["a1"]
        assert abs(p.lane - c.lane) <= 1
        trail = (p.x - c.x) * direction  # positive = child is on the side opposite the parent's heading
        assert 0 < trail <= 2 * SLOT_W
        assert c.direction == p.direction


def test_second_child_trails_further_behind():
    ags = fleet() + [ag("a2", "main", 1, "kid2", burn=1)]
    boats, _ = layout(ags, 120, 20, {})
    boats["main"].x, boats["main"].direction = 60.0, 1
    sail(ags, boats, 4.0, width=120)
    assert boats["main"].x > boats["a1"].x > boats["a2"].x


def test_parent_sails_while_a_child_runs_even_if_main_is_idle():
    ags = fleet(child_status="running", parent_status="idle")
    boats, _ = layout(ags, 80, 20, {})
    x0 = boats["main"].x
    sail(ags, boats, 1.0)
    assert boats["main"].x != x0
    assert "zzz" not in render_harbor(ags, boats, 80, 10, 0).plain


def test_done_child_stays_anchored_when_parent_sails():
    ags = fleet(child_status="done")
    boats, _ = layout(ags, 80, 20, {})
    x = boats["a1"].x
    sail(ags, boats, 2.0)
    assert boats["a1"].x == x


def overlapping_pairs(boats):
    from agent_panel.boats import sprite_key, sprite_width
    wid = {k: sprite_width(sprite_key(k, b.tier)) for k, b in boats.items()}
    ids = sorted(boats)
    return [(a, b) for i, a in enumerate(ids) for b in ids[i + 1:]
            if boats[a].lane == boats[b].lane
            and boats[a].x < boats[b].x + wid[b] and boats[b].x < boats[a].x + wid[a]]


def test_flotilla_does_not_pile_up_at_the_edges():
    ags = [ag("main", None, 0, "main", burn=1)] + [ag(f"a{i}", "main", 1, "k", burn=1) for i in (1, 2)]
    boats, _ = layout(ags, 50, 20, {})
    bad = 0
    frames = 0
    for n in range(600):  # 60 s: several turns at each edge
        step(boats, ags, 0.1, 50)
        if n > 100:  # let the fleet settle into formation first
            frames += 1
            bad += bool(overlapping_pairs(boats))
    assert bad / frames < 0.05, f"{bad}/{frames} frames had same-lane boats overlapping"


# ---- Pirate captain ----
from agent_panel.harbor import captain_pose, CAPTAIN_COLOR
from agent_panel.colors import model_color
from agent_panel.cli import parse_args


def captain_positions(t, w):
    """Columns/rows (y, x) of cells whose style is the captain color."""
    pos = []
    for span in t.spans:
        if str(span.style) == f"bold {CAPTAIN_COLOR}":
            for i in range(span.start, span.end):
                pos.append((i // (w + 1), i % (w + 1)))
    return pos


def test_captain_color_is_distinct_from_model_colors():
    assert CAPTAIN_COLOR not in {model_color(m) for m in ("opus 5", "sonnet 5", "haiku 5", "zzz")}


def test_pose_idle_commanding_firing():
    idle = [ag("main", None, 0, "main", status="idle"), ag("a1", "main", 1, "t", status="done")]
    assert captain_pose(idle, False) == "idle"
    solo = [ag("main", None, 0, "main", status="running")]
    assert captain_pose(solo, False) == "idle"
    cmd = [ag("main", None, 0, "main", status="running"), ag("a1", "main", 1, "t", status="running")]
    assert captain_pose(cmd, False) == "commanding"
    assert captain_pose(cmd, True) == "firing"
    assert captain_pose(idle, True) == "firing"


def test_captain_only_above_the_main_boat():
    ags = agents(3)
    boats, _ = layout(ags, 70, 20, {})
    t = render_harbor(ags, boats, 70, 20, 0)
    pos = captain_positions(t, 70)
    assert pos
    m = boats["main"]
    w = len(SPRITES["main_rowboat"][0])
    assert all(m.x <= x < m.x + w for _, x in pos)
    t2 = render_harbor(ags, boats, 70, 20, 0, captain=False)
    assert not captain_positions(t2, 70)


def test_captain_works_at_every_tier_and_moves_with_the_boat():
    for burn in (1, 60_000, 900_000):
        ags = [ag("main", None, 0, "main", burn=burn, status="running")]
        boats, _ = layout(ags, 60, 14, {})
        boats["main"].x = 5.0
        a = captain_positions(render_harbor(ags, boats, 60, 14, 0), 60)
        boats["main"].x = 25.0
        b = captain_positions(render_harbor(ags, boats, 60, 14, 0), 60)
        assert a and sorted((y, x + 20) for y, x in a) == sorted(b)


def test_captain_stays_in_the_water_box_and_leaves_subagents_alone():
    ags = agents(5, burn=900_000)
    for w, h in [(50, 10), (30, 8), (80, 20), (12, 8), (5, 8)]:
        boats, _ = layout(ags, w, h, {})
        t = render_harbor(ags, boats, w, h, 3, flash=True)
        assert all(0 <= y < h - 1 and 0 <= x < w for y, x in captain_positions(t, w))


def test_firing_shows_call_out_and_commanding_differs_from_idle():
    ags = [ag("main", None, 0, "main", status="running"), ag("a1", "main", 1, "t", status="running")]
    boats, _ = layout(ags, 60, 14, {})
    boats["a1"].x = 30.0
    plain = lambda **kw: render_harbor(ags, boats, 60, 14, 0, **kw).plain
    assert "Fire!" in plain(flash=True) and "Fire!" not in plain()
    idle_ags = [ag("main", None, 0, "main", status="running")]
    iboats, _ = layout(idle_ags, 60, 14, {})
    assert render_harbor(idle_ags, iboats, 60, 14, 0).plain != plain()


def test_anchored_main_gets_zzz_beside_the_captain():
    ags = [ag("main", None, 0, "main", status="idle")]
    boats, _ = layout(ags, 60, 14, {})
    assert "zzz" in render_harbor(ags, boats, 60, 14, 0).plain
    assert "zzz" in render_harbor(ags, boats, 60, 14, 0, captain=False).plain


def test_narrow_and_tiny_harbors_do_not_raise():
    ags = agents(4, burn=900_000)
    for w, h in [(50, 8), (50, 9), (1, 1), (3, 8), (10, 2)]:
        boats, _ = layout(ags, w, h, {})
        for flash in (False, True):
            render_harbor(ags, boats, w, h, 0, flash=flash)


def test_no_captain_flag():
    assert parse_args([]).no_captain is False
    assert parse_args(["--no-captain"]).no_captain is True


def test_captain_never_overlaps_sail_or_hull_art():
    for burn in (1, 60_000, 900_000):
        for d in (1, -1):
            for flash in (False, True):
                ags = [ag("main", None, 0, "main", burn=burn, status="running")]
                boats, _ = layout(ags, 60, 14, {})
                boats["main"].x, boats["main"].direction = 20.0, d
                bare = render_harbor(ags, boats, 60, 14, 0, captain=False).plain.split("\n")
                full = render_harbor(ags, boats, 60, 14, 0, flash=flash).plain.split("\n")
                for yb, yf in zip(bare, full):
                    for cb, cf in zip(yb, yf):
                        if cb != cf:
                            assert cb == " "  # the captain (and call-out) only ever fill blank cells


def cells_with_style(t, w, style):
    return {(i // (w + 1), i % (w + 1)): t.plain[i] for sp in t.spans if str(sp.style) == style for i in range(sp.start, sp.end)}


def test_hat_is_white_and_the_skull_is_yellow():
    from agent_panel.harbor import HAT_STYLE, SKULL
    ags = [ag("main", None, 0, "main", status="running")]
    boats, _ = layout(ags, 60, 14, {})
    t = render_harbor(ags, boats, 60, 14, 0)
    assert "▄▄▄" in t.plain and "▀▀" + SKULL + "▀▀" in t.plain
    hat = cells_with_style(t, 60, HAT_STYLE)
    assert {"▄", "▀"} <= set(hat.values()) and SKULL not in hat.values()
    assert list(cells_with_style(t, 60, f"bold {CAPTAIN_COLOR}").values()) == [SKULL]
    assert CAPTAIN_COLOR == "yellow" and CAPTAIN_COLOR not in {model_color(m) for m in ("opus", "sonnet", "haiku", "x")}


def test_jolly_roger_on_main_sail_only():
    from agent_panel.boats import CROSSBONES, SAIL_SKULL
    assert cell_len_ok(CROSSBONES) and cell_len_ok(SAIL_SKULL)
    for burn, skull in ((900_000, True), (60_000, False), (1, False)):
        ags = [ag("main", None, 0, "main", burn=burn, status="running"), ag("a1", "main", 1, "t", burn=burn, status="running")]
        boats, _ = layout(ags, 70, 20, {})
        boats["main"].x, boats["a1"].x = 0.0, 40.0
        t = render_harbor(ags, boats, 70, 20, 0)
        emblem = cells_with_style(t, 70, "bold bright_white")
        main_x = range(0, len(SPRITES["main_" + tier(burn)][0]))
        assert CROSSBONES in emblem.values() and all(x in main_x for _, x in emblem)  # none on the subagent
        assert t.plain.count(SAIL_SKULL) == 1 + skull  # the hat's skull, plus one in a sail wide enough
        assert t.plain.count(CROSSBONES) == 1
        assert CROSSBONES not in "".join(SPRITES[tier(burn)])


def cell_len_ok(ch):
    from rich.cells import cell_len
    return cell_len(ch) == 1
