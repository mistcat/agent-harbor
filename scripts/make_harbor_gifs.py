"""Render the README's harbor animations into media/: a GIF and an MP4 per scenario.

Run from the repo root: .venv/bin/python scripts/make_harbor_gifs.py [OUT_DIR]   (default: media/)

Needs macOS (for the Menlo and Apple Symbols system fonts), ffmpeg, and Pillow (in your venv only, it is
not a package dependency: .venv/bin/pip install pillow).
Each scenario is a made-up fleet of `Agent`s, played frame by frame through the panel's own `layout`,
`step` and `render_harbor` (and the cannon's `fire`/`advance`), at COLS x ROWS cells. Cells are drawn in
Menlo on a dark background, with the colors Rich itself gives the panel's styles under its SVG export theme
(SVG_EXPORT_THEME; `dim` blended toward the background as Rich's export does). Videos have no sound, so a
caption strip under the harbor says what you would hear. Nothing is random, so a re-run writes the same files.
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rich.color import blend_rgb  # noqa: E402
from rich.style import Style  # noqa: E402
from rich.terminal_theme import SVG_EXPORT_THEME as THEME  # noqa: E402

from agent_panel.effects import FLASH_FRAMES, advance, fire  # noqa: E402
from agent_panel.harbor import CALL_OUT, flagship_boat, layout, render_harbor, step  # noqa: E402
from agent_panel.model import Agent  # noqa: E402

COLS, ROWS = 100, 24
FPS = 10
FONT = "/System/Library/Fonts/Menlo.ttc"  # face 0 is Regular, face 1 Bold
FALLBACK = "/System/Library/Fonts/Apple Symbols.ttf"  # for a glyph Menlo lacks
UNMAPPED = "\ue83a"  # a private-use code point no font here maps: it draws the missing-glyph box
FONT_SIZE = 16
CELL_W, CELL_H = 10, 20
MARGIN = 10
CAPTION_ROWS = 2  # the scenario's title, then what is happening (or what you would hear)
TITLE_STYLE = "bold bright_white"  # the panel's own styles: the captain's hat, and his "Fire!"
SOUND_STYLE = "bold red"
SOUND = "♪ "  # a caption that starts with this is a sound; a ring pulses beside the title while it shows
MEDIA = ROOT / "media"


def style_rgb(style: str) -> tuple[tuple[int, int, int], bool]:
    """(RGB, bold) for one of the panel's Rich style strings, as Rich's own SVG export would color it."""
    st = Style.parse(style) if style else Style()
    color = THEME.foreground_color if st.color is None or st.color.is_default else st.color.get_truecolor(THEME)
    if st.dim:
        color = blend_rgb(color, THEME.background_color, 0.4)
    return tuple(color), bool(st.bold)


def agent(id: str, parent: str | None = None, *, model: str = "sonnet 5.5", status: str = "running", burn: int = 10_000,
          ship: str = "", finished_at: float | None = None) -> Agent:
    return Agent(id, parent, 0 if parent is None else 1, id, "general-purpose", model, "medium", status, burn, 0, 0, None,
                 ship=ship, finished_at=finished_at)


def _span(f: int, start: int, end: int | None = None) -> str:
    """A subagent's status at frame f: running from `start`, done from `end`."""
    return "done" if end is not None and f >= end else "running"


def _caption(f: int, timeline: list[tuple[int, str]]) -> str:
    """The caption showing at frame f: the last one in (start frame, text) order that has started."""
    return [text for start, text in timeline if f >= start][-1]


def busy_morning(f: int):
    # The first to finish is the biggest, so in the moored pile (newest on top, two columns apart) each of
    # the three stays visible; two sloops side by side would merge into one block of sail.
    subs = [("builder", "sonnet 5.5", 30, 75, 80_000), ("scout", "haiku 4.5", 40, 95, 10_000),
            ("reviewer", "opus 5.5", 50, 115, 10_000)]
    agents = [agent("main", model="opus 5.5", burn=400_000)]
    agents += [agent(n, "main", model=m, burn=b, status=_span(f, s, e), finished_at=e / FPS)
               for n, m, s, e, b in subs if f >= s]
    return agents, _caption(f, [
        (0, "Morning. The captain's ship sails out: the main session is working."),
        (30, "Subagents put out one by one, each sail colored by its model."),
        (75, "As each one finishes it moors at the pier, the newest on top."),
        (120, "The finished boats stack in a pile at the pier. The captain sails on."),
    ]), 0


# No galleons in lane 1: a galleon never bobs, and a boat a row out of step with its neighbor puts its wake
# right against the neighbor's label (the agent ids here all bob in the same phase).
SHIPS = [("def-127-grading", "sonnet 5.5", 120_000), ("def-128-binding", "opus 5.5", 200_000),
         ("feat-255-wizard", "haiku 4.5", 10_000)]


def crowded_harbor(f: int):
    agents = [agent("main", model="opus 5.5", burn=400_000),
              agent("tests", "main", model="sonnet 5.5", burn=60_000),
              agent("docs", "main", model="haiku 4.5", status="done", finished_at=0.0)]
    for name, model, burn in SHIPS:
        agents.append(agent(f"{name}/main", model=model, burn=burn, ship=name))
    return agents, _caption(f, [
        (0, "Three worktree agents share the harbor, each labeled with its ticket id."),
        (35, "The main session's ship reads Captain; its own subagents read crew."),
        (70, "A crew boat that has finished is moored at the pier, still labeled crew."),
    ]), 0


FIRES = {30: 1, 95: 2}  # frame -> advisor calls landing in that poll


def advisor_call(f: int):
    agents = [agent("main", model="opus 5.5", burn=400_000), agent("builder", "main", model="sonnet 5.5", burn=80_000)]
    return agents, _caption(f, [
        (0, "The main session is working, with a subagent in tow."),
        (30, SOUND + "BOOM! An advisor call: the captain fires the cannon, and the shot splashes down."),
        (65, "The captain sails on until the next advisor call."),
        (95, SOUND + "BOOM! Two advisor calls in one poll: two shots, one boom."),
    ]), FIRES.get(f, 0)


def attention_call(f: int):
    agents = [agent("main", model="opus 5.5", burn=400_000, status="idle" if f >= 65 else "running"),
              agent("builder", "main", model="sonnet 5.5", burn=80_000, status=_span(f, 0, 35), finished_at=3.5)]
    return agents, _caption(f, [
        (0, "The main session works with one subagent."),
        (35, "The subagent finishes and moors at the pier."),
        (65, "The turn ends: the ship stops and the captain dozes (zzz)."),
        (100, SOUND + 'A few quiet seconds later the panel calls you: BOOM (a deep cannon) or "Ahoy, matey!"'),
        (135, SOUND + "GIFs have no sound, so this caption stands in for the call. Your turn."),
    ]), 0


# name -> (title, frames, script)
SCENARIOS = {
    "busy-morning": ("Busy morning", 160, busy_morning),
    "crowded-harbor": ("Crowded harbor", 105, crowded_harbor),
    "advisor-call": ("Advisor call", 135, advisor_call),
    "attention-call": ("Your turn", 165, attention_call),
}


def cells(text) -> list[list[tuple[str, str]]]:
    """A rendered harbor `Text` as rows of (char, style string)."""
    styles = [""] * len(text.plain)
    for span in text.spans:
        for i in range(span.start, span.end):
            styles[i] = str(span.style)
    rows, row = [], []
    for ch, style in zip(text.plain, styles):
        if ch == "\n":
            rows.append(row)
            row = []
        else:
            row.append((ch, style))
    return rows + [row]


def frames(name: str) -> list[tuple[list[list[tuple[str, str]]], str]]:
    """Play a scenario through the panel's harbor code, in the order the app's tick does it."""
    _, count, script = SCENARIOS[name]
    boats, shots, flash, out = {}, [], 0, []
    for f in range(count):
        agents, caption, calls = script(f)
        boats, _ = layout(agents, COLS, ROWS, boats)
        if f:
            step(boats, agents, 1 / FPS, COLS)
        if calls and (main := flagship_boat(boats)):
            shots += [fire(main, i) for i in range(calls)]
            flash = FLASH_FRAMES
        out.append((cells(render_harbor(agents, boats, COLS, ROWS, f, shots, flash > 0)), caption))
        shots = advance(shots)
        flash = max(flash - 1, 0)
    return out


def _fonts():
    """For each (char, bold), the first face that has the glyph: Menlo's bold (when bold), then Menlo, then
    Apple Symbols. Menlo Bold, for one, has no "╳", the crossbones on the main ship's sail."""
    try:
        from PIL import ImageFont
    except ImportError:
        sys.exit("make_harbor_gifs.py needs Pillow, in your venv only: .venv/bin/pip install pillow")
    regular, bold, symbols = (ImageFont.truetype(path, FONT_SIZE, index=i) for path, i in ((FONT, 0), (FONT, 1), (FALLBACK, 0)))
    cache = {}

    def face(ch: str, want_bold: bool):
        if (ch, want_bold) not in cache:
            faces = [bold, regular, symbols] if want_bold else [regular, symbols]
            cache[ch, want_bold] = next((f for f in faces if bytes(f.getmask(ch)) != bytes(f.getmask(UNMAPPED))), regular)
        return cache[ch, want_bold]

    return face


def draw(grid, title: str, caption: str, fonts, frame: int = 0):
    from PIL import Image, ImageDraw

    size = (COLS * CELL_W + 2 * MARGIN, (ROWS + 1 + CAPTION_ROWS) * CELL_H + 2 * MARGIN)
    img = Image.new("RGB", size, tuple(THEME.background_color))
    pen = ImageDraw.Draw(img)

    def put(x: int, y: int, ch: str, style: str) -> None:
        if ch != " ":
            rgb, bold = style_rgb(style)
            pen.text((MARGIN + x * CELL_W, MARGIN + y * CELL_H), ch, font=fonts(ch, bold), fill=rgb)

    for y, row in enumerate(grid):
        for x, (ch, style) in enumerate(row):
            put(x, y, ch, style)
    ring = ""
    if caption.startswith(SOUND):  # the sound made visible: rings that widen and shrink back
        n = 1 + (frame // 2) % 3
        ring = "  " + "(" * n + " " + SOUND.strip() + " " + ")" * n
    for x, ch in enumerate(title):
        put(x, ROWS + 1, ch, TITLE_STYLE)
    for x, ch in enumerate(ring):
        put(len(title) + x, ROWS + 1, ch, SOUND_STYLE)
    for x, ch in enumerate(caption):
        put(x, ROWS + 2, ch, SOUND_STYLE if caption.startswith(SOUND) else "")
    return img


def ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


def render(name: str, out_dir: Path, fonts) -> list[Path]:
    title = SCENARIOS[name][0]
    with tempfile.TemporaryDirectory() as tmp:
        for i, (grid, caption) in enumerate(frames(name)):
            draw(grid, title, caption, fonts, i).save(Path(tmp) / f"{i:04d}.png")
        src = ["-framerate", str(FPS), "-i", str(Path(tmp) / "%04d.png")]
        exact = ["-fflags", "+bitexact", "-flags:v", "+bitexact", "-map_metadata", "-1"]
        gif, mp4 = out_dir / f"{name}.gif", out_dir / f"{name}.mp4"
        ffmpeg(*src, "-vf", "split[a][b];[a]palettegen[p];[b][p]paletteuse=dither=none", "-loop", "0", *exact, str(gif))
        ffmpeg(*src, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-threads", "1", "-movflags", "+faststart",
               *exact, str(mp4))
    return [gif, mp4]


def main() -> None:
    if shutil.which("ffmpeg") is None:
        sys.exit("make_harbor_gifs.py needs ffmpeg on PATH (brew install ffmpeg)")
    missing = [path for path in (FONT, FALLBACK) if not Path(path).is_file()]
    if missing:
        sys.exit(f"make_harbor_gifs.py runs on macOS only: it draws with the system fonts, and these are missing: {', '.join(missing)}")
    fonts = _fonts()
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else MEDIA
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in SCENARIOS:
        for path in render(name, out_dir, fonts):
            print(f"{path}  {path.stat().st_size / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
