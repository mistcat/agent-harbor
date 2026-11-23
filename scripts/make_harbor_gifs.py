"""Render the README's harbor animations into media/: a GIF and an MP4 per scenario.

Run from the repo root: .venv/bin/python scripts/make_harbor_gifs.py [OUT_DIR]   (default: media/)
                   or: .venv/bin/python scripts/make_harbor_gifs.py --mobile [OUT_DIR]   (default: media/mobile/)

Needs macOS (for the Menlo and Apple Symbols system fonts), ffmpeg, and Pillow (in your venv only, it is
not a package dependency: .venv/bin/pip install pillow).
Each scenario is a made-up fleet of `Agent`s, played frame by frame through the panel's own `layout`,
`step` and `render_harbor` (and the cannon's `fire`/`advance`), at COLS x ROWS cells. Cells are drawn in
Menlo on a dark background, with the colors Rich itself gives the panel's styles under its SVG export theme
(SVG_EXPORT_THEME; `dim` blended toward the background as Rich's export does). These GIFs and MP4s have no
sound, so a caption strip under the harbor says what you would hear. Nothing is random, so a re-run writes the same files.

--mobile writes 4:5 portrait MP4s for phone feeds instead, with sound: the harbor at MOBILE_COLS columns in
big cells, its empty sky cropped, a clear band at the top for a headline, large captions below, and the
panel's own sounds mixed in at the frames they play (SOUND_CUES) over a quiet bed of ocean waves (BED, a CC0
recording; see media/mobile/CREDITS.md).
"""
import shutil
import subprocess
import sys
import tempfile
import math
import textwrap
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rich.color import blend_rgb  # noqa: E402
from rich.style import Style  # noqa: E402
from rich.terminal_theme import SVG_EXPORT_THEME as THEME  # noqa: E402

from agent_panel.effects import FLASH_FRAMES, advance, fire  # noqa: E402
from agent_panel.harbor import CALL_OUT, LABEL_MIN_W, LABEL_STYLE, flagship_boat, layout, render_harbor, step  # noqa: E402
from agent_panel.model import Agent  # noqa: E402
from agent_panel.sound import AHOY_WAV, ATTENTION_WAV, WAV  # noqa: E402

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

# Mobile: 4:5 portrait, 1080x1350. The harbor is rendered at MOBILE_COLS x ROWS (fewer rows would cost the
# crowded harbor its labels) and its top MOBILE_CROP rows, always empty sky, are cropped away.
MOBILE_SIZE = (1080, 1350)
MOBILE_COLS = LABEL_MIN_W  # the narrowest harbor that still labels its ships, for the biggest cells
MOBILE_CROP = 9
MOBILE_FONT_SIZE = 33
MOBILE_CELL = (20, 41)  # Menlo's advance at 33 px is 19.9; the height keeps the wide render's 1.25 line ratio
MOBILE_X = 40  # side margin
MOBILE_HARBOR_Y = 300  # under the clear band (a fifth of the height) the post's headline goes in
MOBILE_TEXT_SIZE = 44
MOBILE_TEXT_CELL = (27, 58)
MOBILE_TITLE_Y = 950
MOBILE_CAPTION_Y = 1030
MOBILE_LINE_H = MOBILE_TEXT_CELL[1]
MOBILE_CAPTION_LINES = 3
MOBILE_CAPTION_CHARS = 37  # 37 x 27 px fits inside the margins
MOBILE_TEXT_STYLE = "bold bright_white"
MOBILE_LABEL_STYLE = "bold bright_white"  # the captain's hat: labels in the panel's dim grey vanish on a phone
RING_TAIL_S = 0.5  # the sound ring keeps pulsing this long after its sound ends
MOBILE_SOUND_STYLE = "bold yellow"  # the panel's red is too dim for a phone caption; the skull's yellow is not
MOBILE_MEDIA = MEDIA / "mobile"
BED = MOBILE_MEDIA / "audio" / "oceanwaves-10-excerpt.m4a"
BED_S = 28.0  # the excerpt's length, longer than any scenario
# Where a clip starts in the bed, in seconds: chosen so no swell breaks just before or after a cue. The
# attention call's 27 s leave it no choice; its ducks before each cue keep its quiet seconds quiet.
BED_OFFSET = {"advisor-call": 5.0}
# Gains in dB, applied after the mono wavs are spread to stereo (which costs them 3 dB a channel). The booms
# peak near -2 dBFS, so the AAC's true peak stays under -1 dBTP; the ahoy, recorded hotter, sits a little
# under them. The bed sits well under all three and ducks a further DUCK_DB around each one.
GAIN_DB = {WAV.name: 1.0, ATTENTION_WAV.name: 1.7, AHOY_WAV.name: -3.0}
BED_DB = -6.0  # the excerpt measures -21.8 LUFS; this puts the bed near -28 LUFS
DUCK_DB = -12.0
PRE_DUCK_S, POST_DUCK_S = 1.5, 1.0  # the bed is calm this long before a cue, and stays down this long after it
# name -> {cue frame: second}: a duck held longer, to that second. The attention call's boom is followed by
# the bed's biggest swell, so the bed stays down from the boom until the ahoy's own duck takes over.
DUCK_HOLD = {"attention-call": {140: 19.5}}
FADE_S = 1.0


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


# The first to finish is the biggest, so in the moored pile (newest on top, three columns apart) each of
# the three stays visible; two sloops side by side would merge into one block of sail.
BUSY_SUBS = [("builder", "sonnet 5.5", 50, 100, 80_000), ("scout", "haiku 4.5", 60, 120, 10_000),
             ("reviewer", "opus 5.5", 70, 140, 10_000)]
BUSY_CAPTIONS = [
    (0, "Morning. The captain's ship sails out: the main session is working."),
    (50, "Subagents put out one by one, each sail colored by its model."),
    (100, "As each one finishes it moors at the pier, the newest on top."),
    (150, "All the building work is done. The captain is ready to deliver it."),
]


def busy_morning(f: int, subs=BUSY_SUBS):
    agents = [agent("main", model="opus 5.5", burn=400_000)]
    agents += [agent(n, "main", model=m, burn=b, status=_span(f, s, e), finished_at=e / FPS)
               for n, m, s, e, b in subs if f >= s]
    return agents, _caption(f, BUSY_CAPTIONS), 0


# No galleons in lane 1: a galleon never bobs, and a boat a row out of step with its neighbor puts its wake
# right against the neighbor's label (the agent ids here all bob in the same phase).
SHIPS = [("def-127-grading", "sonnet 5.5", 120_000), ("def-128-binding", "opus 5.5", 200_000),
         ("feat-255-wizard", "haiku 4.5", 10_000)]


CROWDED_CAPTIONS = [
    (0, "Three worktree agents share the harbor, each labeled with its ticket id."),
    (55, "The main ship reads Captain; each subagent reads its role."),
    (110, "A crew boat that has finished is moored at the pier, still labeled with its role."),
]


def crowded_harbor(f: int, ships=SHIPS, tests: str = "running"):
    agents = [agent("main", model="opus 5.5", burn=400_000),
              agent("tests", "main", model="sonnet 5.5", burn=60_000, status=tests, finished_at=0.0),
              agent("docs", "main", model="haiku 4.5", status="done", finished_at=0.0)]
    for name, model, burn in ships:
        agents.append(agent(f"{name}/main", model=model, burn=burn, ship=name))
    return agents, _caption(f, CROWDED_CAPTIONS), 0


FIRES = {45: 1, 160: 2}  # frame -> advisor calls landing in that poll


def advisor_call(f: int):
    agents = [agent("main", model="opus 5.5", burn=400_000), agent("builder", "main", model="sonnet 5.5", burn=80_000)]
    return agents, _caption(f, [
        (0, "The main session is working, with a subagent in tow."),
        (45, SOUND + "BOOM! An advisor call: the captain fires, and the cannonball splashes into the sea."),
        (110, "The captain sails on until the next advisor call."),
        (160, SOUND + "BOOM! Two advisor calls in one poll: two shots, one boom."),
    ]), FIRES.get(f, 0)


ATTENTION_CAPTIONS = [
    (0, "The main session works with one subagent."),
    (45, "The subagent finishes and moors at the pier."),
    (90, "The turn ends: the ship stops and the captain dozes (zzz)."),
    (140, SOUND + 'A few quiet seconds later the panel calls you: BOOM (a deep cannon) or "Ahoy, matey!"'),
    (210, SOUND + "GIFs have no sound, so this caption stands in for the call. Your turn."),
]


def attention_call(f: int):
    agents = [agent("main", model="opus 5.5", burn=400_000, status="idle" if f >= 90 else "running"),
              agent("builder", "main", model="sonnet 5.5", burn=80_000, status=_span(f, 0, 45), finished_at=4.5)]
    return agents, _caption(f, ATTENTION_CAPTIONS), 0


# name -> (title, frames, script)
SCENARIOS = {
    "busy-morning": ("Busy morning", 210, busy_morning),
    "crowded-harbor": ("Crowded harbor", 170, crowded_harbor),
    "advisor-call": ("Advisor call", 220, advisor_call),
    "attention-call": ("Your turn", 270, attention_call),
}

# Mobile fleets. Two moored boats, not three: at this width the pile is three cards, and the clip was made
# when a middle card showed no hull of its own (the pile now closes each one, \_/). A boat lane is sailed in 10-column slots,
# so sloops (7 wide, and a 3-cell wake) sail nose to tail: the worktree ships are rowboats and the crew boat
# is moored, which leaves water between the boats.
MOBILE_BUSY_SUBS = [BUSY_SUBS[0], BUSY_SUBS[2]]
MOBILE_SHIPS = [(name, model, 20_000) for name, model, _ in SHIPS]
MOBILE_SCRIPTS = {
    "busy-morning": lambda f: busy_morning(f, MOBILE_BUSY_SUBS),
    "crowded-harbor": lambda f: crowded_harbor(f, MOBILE_SHIPS, tests="done"),
}

# The mobile clips have sound, so their captions say what you hear. Scenarios not named keep their captions.
MOBILE_CAPTIONS = {
    "busy-morning": BUSY_CAPTIONS[:2] + [(100, "As each one finishes, it moors in line at the pier.")]
    + BUSY_CAPTIONS[3:],
    "crowded-harbor": CROWDED_CAPTIONS[:2] + [(110, "Finished crew boats are moored at the pier, still labeled with their roles.")],
    "attention-call": ATTENTION_CAPTIONS[:3] + [
        (140, SOUND + "A few seconds later the panel calls you. A deep boom: your turn."),
        (210, SOUND + 'Or, if you pick it, a gravelly "Ah-hoy, may-tee!"'),
    ],
}

# name -> [(frame, wav)]: the sounds the panel plays. One boom per poll, however many advisor calls landed in
# it (the app's Boomer), so the second volley's two shots make one boom, as its caption says.
SOUND_CUES = {
    "advisor-call": [(f, WAV) for f in sorted(FIRES)],
    "attention-call": [(140, ATTENTION_WAV), (210, AHOY_WAV)],
}


def sound_cues(name: str) -> list[tuple[int, Path]]:
    return SOUND_CUES.get(name, [])


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


def frames(name: str, cols: int = COLS, rows: int = ROWS, captions: list[tuple[int, str]] | None = None,
           script=None) -> list[tuple[list[list[tuple[str, str]]], str]]:
    """Play a scenario through the panel's harbor code, in the order the app's tick does it. `captions`
    replaces the scenario's own (start frame, text) timeline, and `script` its fleet."""
    _, count, own = SCENARIOS[name]
    script = script or own
    boats, shots, flash, out = {}, [], 0, []
    for f in range(count):
        agents, caption, calls = script(f)
        if captions:
            caption = _caption(f, captions)
        boats, _ = layout(agents, cols, rows, boats)
        if f:
            step(boats, agents, 1 / FPS, cols)
        if calls and (main := flagship_boat(boats)):
            shots += [fire(main, i) for i in range(calls)]
            flash = FLASH_FRAMES
        out.append((cells(render_harbor(agents, boats, cols, rows, f, shots, flash > 0)), caption))
        shots = advance(shots)
        flash = max(flash - 1, 0)
    return out


def mobile_frames(name: str) -> list[tuple[list[list[tuple[str, str]]], str]]:
    """The mobile clip's frames: the narrow harbor without its top MOBILE_CROP rows, with the mobile captions."""
    return [(grid[MOBILE_CROP:], caption)
            for grid, caption in frames(name, MOBILE_COLS, ROWS, MOBILE_CAPTIONS.get(name), MOBILE_SCRIPTS.get(name))]


def mobile_style(style: str) -> str:
    """The panel's style for a cell, except labels: dim grey is too faint at phone size."""
    return MOBILE_LABEL_STYLE if style == LABEL_STYLE else style


def ringing(name: str, f: int) -> bool:
    """Whether the sound ring pulses at frame f: while a cue's sound plays, and RING_TAIL_S after."""
    return any(c <= f < c + math.ceil((wav_seconds(wav) + RING_TAIL_S) * FPS) for c, wav in sound_cues(name))


def duck_windows(name: str) -> list[tuple[float, float]]:
    """(start, end) seconds the bed is ducked around each cue: calm before it, and while its tail rings out."""
    hold = DUCK_HOLD.get(name, {})
    return [(f / FPS - PRE_DUCK_S, max(f / FPS + wav_seconds(wav) + POST_DUCK_S, hold.get(f, 0)))
            for f, wav in sound_cues(name)]


def wrap_caption(caption: str) -> list[str]:
    return textwrap.wrap(caption, MOBILE_CAPTION_CHARS, break_on_hyphens=False)


def bed_offset(name: str) -> float:
    return BED_OFFSET.get(name, 0.0)


def wav_seconds(path: Path) -> float:
    with wave.open(str(path)) as w:
        return w.getnframes() / w.getframerate()


def mix_filter(name: str) -> str:
    """The ffmpeg filter graph for a mobile clip's audio, labelled [a]. Input 1 is the bed, inputs 2.. the
    cues' wavs in SOUND_CUES order. Each cue is delayed to its frame; the bed fades in and out and ducks by
    DUCK_DB over each of `duck_windows`, with short ramps so the duck is not heard."""
    seconds = SCENARIOS[name][1] / FPS
    stereo = "aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo"
    duck = duck_windows(name)
    ramp_in, ramp_out = 0.4, 0.4
    depth = 1 - 10 ** (DUCK_DB / 20)
    shape = "+".join(f"clip(min((t-{s - ramp_in:g})/{ramp_in},({e:g}-t)/{ramp_out}),0,1)"
                     for s, e in duck)
    bed = (f"[1:a]{stereo},volume={BED_DB}dB,afade=t=in:d={FADE_S},afade=t=out:st={seconds - FADE_S:g}:d={FADE_S}"
           + (f",volume='1-{depth:.4f}*min({shape},1)':eval=frame" if duck else "") + "[bed]")
    if not duck:
        return f"{bed};[bed]apad,atrim=duration={seconds}[a]"
    fx = [f"[{i + 2}:a]{stereo},volume={GAIN_DB[wav.name]}dB,adelay={f * 1000 // FPS}|{f * 1000 // FPS}[c{i}]"
          for i, (f, wav) in enumerate(sound_cues(name))]
    mix = "".join(f"[c{i}]" for i in range(len(fx))) + f"[bed]amix=inputs={len(fx) + 1}:normalize=0"
    return ";".join([bed, *fx, f"{mix},apad,atrim=duration={seconds}[a]"])


def check_bed(path: Path = BED) -> Path:
    if not path.is_file():
        sys.exit(f"make_harbor_gifs.py --mobile needs its background track, {path}: see media/mobile/CREDITS.md "
                 "for the source and the command that cut it")
    return path


def _fonts(size: int = FONT_SIZE):
    """For each (char, bold), the first face that has the glyph: Menlo's bold (when bold), then Menlo, then
    Apple Symbols. Menlo Bold, for one, has no "╳", the crossbones on the main ship's sail."""
    try:
        from PIL import ImageFont
    except ImportError:
        sys.exit("make_harbor_gifs.py needs Pillow, in your venv only: .venv/bin/pip install pillow")
    regular, bold, symbols = (ImageFont.truetype(path, size, index=i) for path, i in ((FONT, 0), (FONT, 1), (FALLBACK, 0)))
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


def draw_mobile(grid, title: str, caption: str, cell_fonts, text_fonts, frame: int = 0, ring: bool = False):
    """A 4:5 frame: the clear band, the harbor in big cells, the title (and the sound ring), the caption."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", MOBILE_SIZE, tuple(THEME.background_color))
    pen = ImageDraw.Draw(img)

    def put(x: int, y: int, ch: str, style: str, fonts) -> None:
        if ch != " ":
            rgb, bold = style_rgb(style)
            pen.text((x, y), ch, font=fonts(ch, bold), fill=rgb)

    cw, ch_ = MOBILE_CELL
    for y, row in enumerate(grid):
        for x, (ch, style) in enumerate(row):
            put(MOBILE_X + x * cw, MOBILE_HARBOR_Y + y * ch_, ch, mobile_style(style), cell_fonts)
    sound = caption.startswith(SOUND)
    n = 1 + (frame // 2) % 3
    ring = "  " + "(" * n + " " + SOUND.strip() + " " + ")" * n if ring else ""
    tw = MOBILE_TEXT_CELL[0]
    for x, ch in enumerate(title):
        put(MOBILE_X + x * tw, MOBILE_TITLE_Y, ch, TITLE_STYLE, text_fonts)
    for x, ch in enumerate(ring):
        put(MOBILE_X + (len(title) + x) * tw, MOBILE_TITLE_Y, ch, MOBILE_SOUND_STYLE, text_fonts)
    for i, line in enumerate(wrap_caption(caption)):
        for x, ch in enumerate(line):
            put(MOBILE_X + x * tw, MOBILE_CAPTION_Y + i * MOBILE_LINE_H, ch,
                MOBILE_SOUND_STYLE if sound else MOBILE_TEXT_STYLE, text_fonts)
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


def render_mobile(name: str, out_dir: Path, cell_fonts, text_fonts) -> Path:
    title = SCENARIOS[name][0]
    mp4 = out_dir / f"{name}.mp4"
    with tempfile.TemporaryDirectory() as tmp:
        for i, (grid, caption) in enumerate(mobile_frames(name)):
            draw_mobile(grid, title, caption, cell_fonts, text_fonts, i, ringing(name, i)).save(Path(tmp) / f"{i:04d}.png")
        seek = ["-ss", str(bed_offset(name))] if bed_offset(name) else []  # even -ss 0 adds a stray AAC frame
        inputs = ["-framerate", str(FPS), "-i", str(Path(tmp) / "%04d.png"), *seek, "-i", str(BED)]
        for _, wav in sound_cues(name):
            inputs += ["-i", str(wav)]
        ffmpeg(*inputs, "-filter_complex", mix_filter(name), "-map", "0:v", "-map", "[a]",
               "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", "-threads", "1",
               "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2", "-movflags", "+faststart",
               "-fflags", "+bitexact", "-flags:v", "+bitexact", "-flags:a", "+bitexact", "-map_metadata", "-1",
               str(mp4))
    return mp4


def main() -> None:
    if shutil.which("ffmpeg") is None:
        sys.exit("make_harbor_gifs.py needs ffmpeg on PATH (brew install ffmpeg)")
    missing = [path for path in (FONT, FALLBACK) if not Path(path).is_file()]
    if missing:
        sys.exit(f"make_harbor_gifs.py runs on macOS only: it draws with the system fonts, and these are missing: {', '.join(missing)}")
    args = sys.argv[1:]
    mobile = "--mobile" in args
    args = [a for a in args if a != "--mobile"]
    if mobile:
        check_bed()
        cell_fonts, text_fonts = _fonts(MOBILE_FONT_SIZE), _fonts(MOBILE_TEXT_SIZE)
        out_dir = Path(args[0]) if args else MOBILE_MEDIA
        out_dir.mkdir(parents=True, exist_ok=True)
        for name in SCENARIOS:
            path = render_mobile(name, out_dir, cell_fonts, text_fonts)
            print(f"{path}  {path.stat().st_size / 1e6:.2f} MB")
        return
    fonts = _fonts()
    out_dir = Path(args[0]) if args else MEDIA
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in SCENARIOS:
        for path in render(name, out_dir, fonts):
            print(f"{path}  {path.stat().st_size / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
