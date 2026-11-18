"""scripts/make_harbor_gifs.py: the palette mapping and the four scenarios' frames. No Pillow or ffmpeg needed."""
import importlib.util
import itertools
import math
import re
from pathlib import Path

import pytest
from rich.color import Color
from rich.terminal_theme import SVG_EXPORT_THEME

from agent_panel.boats import SAIL
from agent_panel.harbor import LABEL_MIN_W, LABEL_STYLE, WAKE, dock_size, dock_x, docked, hull_row

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


def test_busy_morning_pile_shows_each_moored_boat():
    cells, _ = gifs.frames("busy-morning")[-1]
    pile = range(dock_x(gifs.COLS), gifs.COLS - dock_size(gifs.COLS)[1])
    sails = {cells[y][x][1] for y in range(hull_row(gifs.ROWS, 0, False) + 1) for x in pile if cells[y][x][0] == SAIL}
    assert len(sails) == 3  # one sail color per model: none of the three is hidden under the others


@pytest.mark.parametrize("name", list(gifs.SCENARIOS))
def test_every_caption_shows_long_enough_for_a_slow_reader(name):
    """At least 4.5 s each, and longer for long captions: 14 characters a second."""
    shown = [caption for _, caption in gifs.frames(name)]
    for caption, run in itertools.groupby(shown):
        assert len(list(run)) >= max(4.5, len(caption) / 14) * gifs.FPS, caption


def test_crowded_harbor_labels_never_touch_a_wake():
    for cells, _ in gifs.frames("crowded-harbor"):
        for row in cells[:-1]:  # not the water
            for (a, sa), (b, sb) in zip(row, row[1:]):
                wake_a, wake_b = a in WAKE and sa != LABEL_STYLE, b in WAKE and sb != LABEL_STYLE
                assert not (sa == LABEL_STYLE and wake_b or wake_a and sb == LABEL_STYLE), "".join(c for c, _ in row)


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


# Mobile: 4:5 portrait MP4s with sound, the harbor at MOBILE_COLS columns, cropped to its lower rows.

def test_mobile_frame_is_4_by_5_with_even_sides():
    w, h = gifs.MOBILE_SIZE
    assert (w, h) == (1080, 1350) and w * 5 == h * 4 and w % 2 == h % 2 == 0


def test_mobile_layout_leaves_the_top_band_clear_and_fits_the_frame():
    w, h = gifs.MOBILE_SIZE
    harbor_h = (gifs.ROWS - gifs.MOBILE_CROP) * gifs.MOBILE_CELL[1]
    assert gifs.MOBILE_HARBOR_Y >= h // 5  # the band the post's headline goes in
    assert gifs.MOBILE_X + gifs.MOBILE_COLS * gifs.MOBILE_CELL[0] <= w - gifs.MOBILE_X
    assert gifs.MOBILE_HARBOR_Y + harbor_h <= gifs.MOBILE_TITLE_Y
    assert gifs.MOBILE_CAPTION_Y + gifs.MOBILE_CAPTION_LINES * gifs.MOBILE_LINE_H <= h
    assert gifs.MOBILE_CAPTION_CHARS * gifs.MOBILE_TEXT_CELL[0] <= w - 2 * gifs.MOBILE_X
    assert gifs.MOBILE_TEXT_SIZE >= 40


def _mobile_plain(name):
    return ["\n".join("".join(ch for ch, _ in row) for row in cells) for cells, _ in gifs.mobile_frames(name)]


@pytest.mark.parametrize("name", list(gifs.SCENARIOS))
def test_mobile_crop_only_drops_empty_sky(name):
    for cells, _ in gifs.frames(name, gifs.MOBILE_COLS, script=gifs.MOBILE_SCRIPTS.get(name)):
        assert all(ch == " " for row in cells[:gifs.MOBILE_CROP] for ch, _ in row)
    for cells, _ in gifs.mobile_frames(name):
        assert len(cells) == gifs.ROWS - gifs.MOBILE_CROP and all(len(row) == gifs.MOBILE_COLS for row in cells)


def test_mobile_crowded_harbor_labels_never_touch_a_wake():
    for cells, _ in gifs.mobile_frames("crowded-harbor"):
        for row in cells[:-1]:
            for (a, sa), (b, sb) in zip(row, row[1:]):
                wake_a, wake_b = a in WAKE and sa != LABEL_STYLE, b in WAKE and sb != LABEL_STYLE
                assert not (sa == LABEL_STYLE and wake_b or wake_a and sb == LABEL_STYLE), "".join(c for c, _ in row)


def test_mobile_crowded_harbor_shows_every_label():
    text = "\n".join(_mobile_plain("crowded-harbor"))
    for label in ("Captain", "crew", "def-127", "def-128", "feat-255"):
        assert label in text
    assert "more" not in text


def _mobile_pile(cells):
    """The moored cards' cells in a cropped mobile frame: (sail styles, hull row text)."""
    pile = range(dock_x(gifs.MOBILE_COLS), gifs.MOBILE_COLS - dock_size(gifs.MOBILE_COLS)[1])
    hull = hull_row(gifs.ROWS, 0, False) - gifs.MOBILE_CROP
    sails = {cells[y][x][1] for y in range(hull + 1) for x in pile if cells[y][x][0] == SAIL}
    return sails, "".join(cells[hull][x][0] for x in pile).strip()


def test_mobile_busy_morning_pile_shows_each_moored_boat_with_its_own_hull():
    """Each card under another shows a closed little hull, \\_/, and the top card its whole hull."""
    cells, _ = gifs.mobile_frames("busy-morning")[-1]
    sails, hulls = _mobile_pile(cells)
    cards = ["\\" + h for h in hulls.split("\\")[1:]]
    assert len(sails) == len(cards) == len(gifs.MOBILE_BUSY_SUBS) >= 2
    assert all(card.endswith("/") for card in cards) and len(cards[-1]) >= 5, hulls


def test_mobile_harbor_is_as_narrow_as_labels_allow():
    assert gifs.MOBILE_COLS == LABEL_MIN_W


def test_mobile_labels_are_drawn_bright():
    assert gifs.mobile_style(LABEL_STYLE) == gifs.MOBILE_LABEL_STYLE
    assert gifs.style_rgb(gifs.MOBILE_LABEL_STYLE)[1]  # bold
    assert gifs.mobile_style("dodger_blue3") == "dodger_blue3"


def _longest_nose_to_tail(frames):
    """The most frames in a row with a hull's end, its wake, then the next hull and no blank cell between."""
    def water(row):  # the pier's row without its pile, whose cards lie hull to hull on purpose
        text = "".join(ch for ch, _ in row)
        return text[:dock_x(len(text))] if "╤" in text else text

    touching = [any(re.search(r"/[~\-.]*\\", water(row)) for row in cells) for cells, _ in frames]
    return max((len(list(run)) for hit, run in itertools.groupby(touching) if hit), default=0)


def test_mobile_crowded_harbor_boats_keep_water_between_them():
    """Boats touch only for a moment, as two pass at a turn; the wide fleet at this width sails nose to tail."""
    assert _longest_nose_to_tail(gifs.mobile_frames("crowded-harbor")) <= 0.8 * gifs.FPS
    assert _longest_nose_to_tail(gifs.frames("crowded-harbor", gifs.MOBILE_COLS)) == gifs.SCENARIOS["crowded-harbor"][1]


def test_mobile_busy_morning_caption_says_what_the_pile_shows():
    captions = _mobile_captions("busy-morning")
    assert not any("newest on top" in c for c in captions)
    assert any("in line at the pier" in c for c in captions)


def test_mobile_crowded_harbor_caption_speaks_of_every_moored_crew_boat():
    captions = _mobile_captions("crowded-harbor")
    assert not any("A crew boat" in c for c in captions)
    assert any("crew boats" in c and "moored" in c for c in captions)


def test_mobile_attention_call_never_promises_quiet_over_the_waves():
    assert not any("quiet" in c for c in _mobile_captions("attention-call"))


def test_attention_call_bed_stays_down_from_the_boom_until_the_ahoy():
    (_, boom_end), (ahoy_start, _) = gifs.duck_windows("attention-call")
    assert boom_end == pytest.approx(ahoy_start) == pytest.approx(19.5)


@pytest.mark.parametrize("name", list(gifs.SCENARIOS))
def test_ring_pulses_only_while_a_sound_plays(name):
    count = gifs.SCENARIOS[name][1]
    want = set()
    for f, wav in gifs.sound_cues(name):
        want |= set(range(f, f + math.ceil((gifs.wav_seconds(wav) + gifs.RING_TAIL_S) * gifs.FPS)))
    assert {f for f in range(count) if gifs.ringing(name, f)} == want
    captions = _mobile_captions(name)
    assert all(captions[f].startswith(gifs.SOUND) for f in want)


@pytest.mark.parametrize("name", list(gifs.SCENARIOS))
def test_bed_ducks_from_before_each_cue_until_after_it(name):
    windows = gifs.duck_windows(name)
    cues = gifs.sound_cues(name)
    assert len(windows) == len(cues)
    for (start, end), (f, wav) in zip(windows, cues):
        assert start == pytest.approx(f / gifs.FPS - gifs.PRE_DUCK_S)
        default = f / gifs.FPS + gifs.wav_seconds(wav) + gifs.POST_DUCK_S
        assert end == pytest.approx(max(default, gifs.DUCK_HOLD.get(name, {}).get(f, 0)))
        assert gifs.PRE_DUCK_S >= 1.5 and gifs.POST_DUCK_S >= 1.0


def test_mobile_advisor_call_fires_the_cannon():
    plain = _mobile_plain("advisor-call")
    assert any("Fire!" in p and "✸" in p for p in plain)


def _mobile_captions(name):
    return [caption for _, caption in gifs.mobile_frames(name)]


@pytest.mark.parametrize("name", list(gifs.SCENARIOS))
def test_mobile_captions_wrap_into_the_caption_block_and_stay_up_long_enough(name):
    for caption, run in itertools.groupby(_mobile_captions(name)):
        lines = gifs.wrap_caption(caption)
        assert 1 <= len(lines) <= gifs.MOBILE_CAPTION_LINES, caption
        assert all(len(line) <= gifs.MOBILE_CAPTION_CHARS for line in lines)
        assert " ".join(lines) == caption
        assert len(list(run)) >= max(4.5, len(caption) / 14) * gifs.FPS, caption


@pytest.mark.parametrize("name", list(gifs.SCENARIOS))
def test_mobile_captions_never_say_there_is_no_sound(name):
    assert not any("GIF" in c or "no sound" in c for c in _mobile_captions(name))


def test_wide_captions_are_unchanged():
    assert any("GIFs have no sound" in c for _, c in gifs.frames("attention-call"))


def test_mobile_attention_call_plays_the_boom_then_the_ahoy_at_their_captions():
    cues = gifs.sound_cues("attention-call")
    assert [(f, w.name) for f, w in cues] == [(140, "attention.wav"), (210, "ahoy.wav")]
    shown = dict((f, c) for f, (_, c) in enumerate(gifs.mobile_frames("attention-call")))
    assert "boom" in shown[140].lower() and "Ah-hoy, may-tee" in shown[210]


def test_mobile_advisor_call_booms_once_per_poll_like_the_panel():
    """Two calls in one poll fire two shots but play one boom (the app's Boomer), as the caption says."""
    assert [(f, w.name) for f, w in gifs.sound_cues("advisor-call")] == [(f, "cannon.wav") for f in sorted(gifs.FIRES)]


@pytest.mark.parametrize("name", list(gifs.SCENARIOS))
def test_every_sound_caption_starts_with_its_cue(name):
    captions = _mobile_captions(name)
    starts = [f for f, c in enumerate(captions) if c.startswith(gifs.SOUND) and (f == 0 or captions[f - 1] != c)]
    assert starts == [f for f, _ in gifs.sound_cues(name)]


@pytest.mark.parametrize("name", list(gifs.SCENARIOS))
def test_sound_cues_end_inside_the_clip(name):
    import wave

    count = gifs.SCENARIOS[name][1]
    for f, wav in gifs.sound_cues(name):
        with wave.open(str(wav)) as w:
            length = w.getnframes() / w.getframerate()
        assert wav.is_file() and 0 <= f < count and f / gifs.FPS + length + 0.5 <= count / gifs.FPS


def test_mix_delays_each_cue_to_its_frame():
    graph = gifs.mix_filter("attention-call")
    assert "adelay=14000|14000" in graph and "adelay=21000|21000" in graph
    assert "normalize=0" in graph and f"atrim=duration={270 / gifs.FPS}" in graph


def test_mix_without_cues_is_the_bed_alone():
    graph = gifs.mix_filter("busy-morning")
    assert "adelay" not in graph and f"atrim=duration={210 / gifs.FPS}" in graph


def test_missing_bed_exits_with_a_clear_message(tmp_path):
    with pytest.raises(SystemExit, match="background track"):
        gifs.check_bed(tmp_path / "nope.ogg")


@pytest.mark.parametrize("name", list(gifs.SCENARIOS))
def test_each_clip_plays_a_stretch_of_the_bed_that_it_holds(name):
    assert 0 <= gifs.bed_offset(name) and gifs.bed_offset(name) + gifs.SCENARIOS[name][1] / gifs.FPS <= gifs.BED_S


def test_advisor_call_starts_the_bed_where_its_cannons_land_between_swells():
    assert gifs.bed_offset("advisor-call") == 5.0 and gifs.bed_offset("busy-morning") == 0.0
