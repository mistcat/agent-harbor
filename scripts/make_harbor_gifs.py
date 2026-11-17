"""Render the README's harbor animations into media/: a GIF and an MP4 per scenario.

Run from the repo root: .venv/bin/python scripts/make_harbor_gifs.py [OUT_DIR]   (default: media/)

Needs Pillow (in your venv only, it is not a package dependency: .venv/bin/pip install pillow) and ffmpeg.
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
SOUND = "♪ "  # a caption that starts with this is a sound
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


def busy_morning(f: int):
    subs = [("scout", "haiku 4.5", 8, 42, 10_000), ("builder", "sonnet 5.5", 16, 58, 80_000), ("reviewer", "opus 5.5", 24, 74, 80_000)]
    agents = [agent("main", model="opus 5.5", burn=400_000)]
    agents += [agent(n, "main", model=m, burn=b, status=_span(f, s, e), finished_at=e / FPS)
               for n, m, s, e, b in subs if f >= s]
    if f < 8:
        caption = "Morning. The captain's ship sails out: the main session is working."
    elif f < 30:
        caption = "Subagents put out one by one, each sail colored by its model."
    elif f < 74:
        caption = "As each one finishes it moors at the pier, the newest on top."
    else:
        caption = "All three moored. The captain sails on."
    return agents, caption, 0


SHIPS = [("def-127-grading", "sonnet 5.5", 120_000), ("def-128-binding", "opus 5.5", 400_000),
         ("feat-255-wizard", "sonnet 5.5", 10_000), ("def-131-export", "haiku 4.5", 60_000)]


def crowded_harbor(f: int):
    agents = [agent("main", model="opus 5.5", burn=400_000),
              agent("tests", "main", model="sonnet 5.5", burn=60_000),
              agent("docs", "main", model="haiku 4.5", status="done", finished_at=0.0)]
    for name, model, burn in SHIPS:
        agents.append(agent(f"{name}/main", model=model, burn=burn, ship=name))
    agents.append(agent("def-127-grading/sub", "def-127-grading/main", model="haiku 4.5", ship="def-127-grading"))
    if f < 30:
        caption = "Four worktree agents share the harbor, each labeled with its ticket id."
    elif f < 60:
        caption = "The main session's own ship reads Captain; its subagents read crew."
    else:
        caption = "A worktree's subagents sail under its label too, e.g. def-127 above."
    return agents, caption, 0


FIRES = {20: 1, 50: 2}  # frame -> advisor calls landing in that poll


def advisor_call(f: int):
    agents = [agent("main", model="opus 5.5", burn=400_000), agent("builder", "main", model="sonnet 5.5", burn=80_000)]
    since = [f - at for at in FIRES if f >= at]
    if not since:
        caption = "The main session is working, with a subagent in tow."
    elif min(since) < 18:
        caption = SOUND + ("BOOM! An advisor call: the captain fires the cannon." if f < 50
                           else "BOOM! Two advisor calls in one poll: two shots, one boom.")
    else:
        caption = "The captain sails on until the next advisor call."
    return agents, caption, FIRES.get(f, 0)


def attention_call(f: int):
    turn_over = f >= 40
    agents = [agent("main", model="opus 5.5", burn=400_000, status="idle" if turn_over else "running"),
              agent("builder", "main", model="sonnet 5.5", burn=80_000, status=_span(f, 0, 25), finished_at=2.5)]
    if f < 25:
        caption = "The main session works with one subagent."
    elif f < 40:
        caption = "The subagent finishes and moors at the pier."
    elif f < 55:
        caption = "The turn ends: the ship drops anchor and the captain dozes (zzz)."
    else:
        caption = SOUND + 'BOOM (a deep cannon), or "Ahoy, matey!": your turn.'
    return agents, caption, 0


# name -> (title, frames, script)
SCENARIOS = {
    "busy-morning": ("Busy morning", 95, busy_morning),
    "crowded-harbor": ("Crowded harbor", 90, crowded_harbor),
    "advisor-call": ("Advisor call", 80, advisor_call),
    "attention-call": ("Your turn", 90, attention_call),
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


def draw(grid, title: str, caption: str, fonts):
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
    for x, ch in enumerate(title):
        put(x, ROWS + 1, ch, TITLE_STYLE)
    for x, ch in enumerate(caption):
        put(x, ROWS + 2, ch, SOUND_STYLE if caption.startswith(SOUND) else "")
    return img


def ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


def render(name: str, out_dir: Path, fonts) -> list[Path]:
    title = SCENARIOS[name][0]
    with tempfile.TemporaryDirectory() as tmp:
        for i, (grid, caption) in enumerate(frames(name)):
            draw(grid, title, caption, fonts).save(Path(tmp) / f"{i:04d}.png")
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
    fonts = _fonts()
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else MEDIA
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in SCENARIOS:
        for path in render(name, out_dir, fonts):
            print(f"{path}  {path.stat().st_size / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
