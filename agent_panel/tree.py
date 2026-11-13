"""Pure renderer: agent list -> Rich Text. No terminal needed."""
from datetime import datetime

from rich.text import Text

from agent_panel.colors import model_color
from agent_panel.model import Agent

SPINNER = "◐◓◑◒"
BAR_STEPS = (1_000, 10_000, 50_000, 200_000, 1_000_000)
MIN_LABEL = 4


def fmt_burn(n: int) -> str:
    if n < 1000:
        return str(n)
    if n < 1_000_000:
        return f"{n / 1000:.0f}k"
    return f"{n / 1_000_000:.1f}M"


def bar(burn: int) -> str:
    filled = sum(burn >= s for s in BAR_STEPS)
    return "▮" * filled + "▯" * (len(BAR_STEPS) - filled)


def _prefix(a: Agent, last: bool, frame: int) -> str:
    if a.depth == 0:
        return " "
    slots = ["─"] * 3
    if a.status == "running":
        slots[frame % 3] = "•"
    return " " + "  " * (a.depth - 1) + ("└" if last else "├") + "".join(slots) + "▶ "


def _mark(a: Agent, frame: int) -> str:
    if a.status == "done":
        return "✓"
    if a.status == "running":
        return SPINNER[frame % len(SPINNER)]
    return "·"


def _row(a: Agent, last: bool, width: int, frame: int) -> Text:
    prefix, mark = _prefix(a, last, frame), _mark(a, frame)
    burn = fmt_burn(a.burn)
    label = a.label + ("" if a.linked else " ?")
    eff = f" {a.effort}" if a.effort else ""
    show_bar = True

    def fixed() -> int:
        return len(prefix) + len(a.model) + len(" · ") + len(eff) + (6 if show_bar else 0) + 1 + len(burn) + 2

    # Truncate order: label first, then effort, then the burn bar.
    room = width - fixed()
    if room < MIN_LABEL:
        eff = ""
        room = width - fixed()
    if room < MIN_LABEL:
        show_bar = False
        room = width - fixed()
    room = max(room, 1)
    if len(label) > room:
        label = label[: max(room - 1, 0)] + "…"

    style = "dim" if a.status == "done" else ""
    t = Text(no_wrap=True)
    t.append(prefix, style=style or "grey62")
    t.append(a.model, style=f"bold {model_color(a.model)}" if a.status != "done" else f"dim {model_color(a.model)}")
    t.append(f" · {label}", style=style)
    if eff:
        t.append(eff, style="dim")
    if show_bar:
        t.append(" " + bar(a.burn), style=model_color(a.model) if a.status != "done" else "dim")
    t.append(f" {burn}", style=style)
    t.append(f" {mark}", style="green" if a.status == "done" else model_color(a.model))
    return t


def _advisor_line(main: Agent, advisor_model: str | None) -> Text:
    t = Text(" ◆ advisor", style="grey70")
    if advisor_model:
        t.append(f" ({advisor_model})")
    t.append(f" · {main.advisor_calls} calls")
    if main.last_advisor_at:
        try:
            when = datetime.fromisoformat(main.last_advisor_at.replace("Z", "+00:00")).astimezone()
            t.append(f" · last {when:%H:%M}")
        except ValueError:
            pass
    return t


def render_tree(agents: list[Agent], width: int, frame: int, advisor_model: str | None) -> Text:
    width = max(width, 8)
    out = Text(no_wrap=True)
    for i, a in enumerate(agents):
        sibling_after = False
        for b in agents[i + 1:]:
            if b.depth < a.depth:
                break
            if b.depth == a.depth:
                sibling_after = True
                break
        out.append_text(_row(a, not sibling_after, width, frame))
        out.append("\n")
    main = agents[0] if agents else None
    if main and main.advisor_calls:
        out.append_text(_advisor_line(main, advisor_model))
        out.append("\n")
    return out
