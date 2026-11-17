"""scripts/make_harbor_gifs.py: the palette mapping and the four scenarios' frames. No Pillow or ffmpeg needed."""
import importlib.util
from pathlib import Path

import pytest
from rich.color import Color
from rich.terminal_theme import SVG_EXPORT_THEME

from agent_panel.boats import SAIL
from agent_panel.harbor import dock_size, dock_x, docked, hull_row

_PATH = Path(__file__).resolve().parent.parent / "scripts" / "make_harbor_gifs.py"
_spec = importlib.util.spec_from_file_location("make_harbor_gifs", _PATH)
gifs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gifs)


def test_style_rgb_uses_richs_own_colors():
    assert gifs.style_rgb("dodger_blue3") == (tuple(Color.parse("dodger_blue3").get_truecolor(SVG_EXPORT_THEME)), False)
    assert gifs.style_rgb("bold yellow") == (tuple(Color.parse("yellow").get_truecolor(SVG_EXPORT_THEME)), True)
    assert gifs.style_rgb("") == (tuple(SVG_EXPORT_THEME.foreground_color), False)


def test_dim_blends_toward_the_background_like_richs_export():
    fg, bg = SVG_EXPORT_THEME.foreground_color, SVG_EXPORT_THEME.background_color
    want = tuple(int(f + (b - f) * 0.4) for f, b in zip(fg, bg))
    assert gifs.style_rgb("dim") == (want, False)


@pytest.mark.parametrize("name", list(gifs.SCENARIOS))
def test_scenario_frames_fill_the_grid_and_repeat_exactly(name):
    first = gifs.frames(name)
    assert len(first) > 10
    for cells, caption in first:
        assert len(cells) == gifs.ROWS and all(len(row) == gifs.COLS for row in cells)
        assert caption
    assert gifs.frames(name) == first


def _plain(name):
    return ["\n".join("".join(ch for ch, _ in row) for row in cells) for cells, _ in gifs.frames(name)]


def test_busy_morning_ends_with_the_subagents_moored():
    _, count, script = gifs.SCENARIOS["busy-morning"]
    agents, _, _ = script(count - 1)
    assert {a.id for a in docked(agents)} == {"scout", "builder", "reviewer"}
    cells, _ = gifs.frames("busy-morning")[-1]
    pile = range(dock_x(gifs.COLS), gifs.COLS - dock_size(gifs.COLS)[1])  # the moored cards, left of the pier
    drawn = [cells[y][x][0] for y in range(hull_row(gifs.ROWS, 0, False) + 1) for x in pile]
    assert SAIL in drawn and "\\" in drawn


def test_crowded_harbor_shows_ticket_labels_captain_and_crew():
    text = "\n".join(_plain("crowded-harbor"))
    for label in ("Captain", "crew", "def-127", "def-128", "feat-255"):
        assert label in text
    assert "more" not in text  # every ship and boat has room


def test_advisor_call_fires_the_cannon():
    plain = _plain("advisor-call")
    assert any("Fire!" in p and "✸" in p for p in plain)
    assert any("*" in p for p in plain)


def test_attention_call_ends_at_anchor():
    cells, _ = gifs.frames("attention-call")[-1]
    assert "zzz" in "\n".join("".join(ch for ch, _ in row) for row in cells)
