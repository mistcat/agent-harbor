"""Pure harbor layout and rendering: agents -> boats -> Rich Text."""
from dataclasses import dataclass

from rich.cells import cell_len
from rich.text import Text

from agent_panel.boats import EMBLEM, SAIL, SPRITES, STERN_W, mirror, sprite_key, sprite_width, tier
from agent_panel.colors import model_color
from agent_panel.model import Agent

SPEED = 6.0  # cells per second for a running boat
WAKE = "~-."  # nearest to farthest behind the hull
LANE_H = 6  # tallest sprite
SLOT_W = 10  # widest sprite plus a gap
CAPTAIN_COLOR = "yellow"  # the skull; not used by any model family
HAT_STYLE = "bold bright_white"
CAPTAIN_W = STERN_W
SKULL = "☠" if cell_len("☠") == 1 else "x"
CALL_OUT = "Fire!"
KEEP_DONE_S = 120  # a done subagent leaves the tree and the harbor this long after it finished
# Captain facing right (stern on the left, flotilla astern); mirrored when sailing left.
# Rows: tricorn crown, brim with skull, head (and arm), body.
_HAT = [" ▄▄▄ ", "▀▀" + SKULL + "▀▀"]
_CAPTAIN = {
    "idle": _HAT + ["  o  ", " /|\\ "],
    "commanding": _HAT + [" \\o  ", "  |\\ "],
    "firing": _HAT + ["  o/ ", " /|  "],
}


@dataclass
class Boat:
    agent_id: str
    x: float
    lane: int
    direction: int
    tier: str
    flagship: bool = False


def flagship_boat(boats: dict[str, Boat]) -> Boat | None:
    return next((b for b in boats.values() if b.flagship), None)


def active_ids(agents: list[Agent]) -> set[str]:
    """Agents that sail: running ones, and any ancestor of a running one (a parent leads its flotilla)."""
    by_id = {a.id: a for a in agents}
    active: set[str] = set()
    for a in agents:
        if a.status == "running":
            cur = a
            while cur is not None and cur.id not in active:
                active.add(cur.id)
                cur = by_id.get(cur.parent_id) if cur.parent_id else None
    return active


def retire(agents: list[Agent], now: float, keep_s: float = KEEP_DONE_S) -> tuple[list[Agent], int]:
    """Drop subagents that finished more than keep_s ago. Returns (kept agents, retired count).

    Ships (the flagship and the fleet's worktree ships) never retire, nor does a running agent or any
    ancestor of one; an agent with a kept descendant stays too, so no row loses its parent."""
    active = active_ids(agents)
    keep = {a.id for a in agents
            if a.parent_id is None or a.id in active or a.finished_at is None or now - a.finished_at < keep_s}
    by_id = {a.id: a for a in agents}
    for a in agents:
        if a.id in keep:
            cur = by_id.get(a.parent_id) if a.parent_id else None
            while cur is not None and cur.id not in keep:
                keep.add(cur.id)
                cur = by_id.get(cur.parent_id) if cur.parent_id else None
    kept = [a for a in agents if a.id in keep]
    return kept, len(agents) - len(kept)


def captain_pose(agents: list[Agent], flash: bool) -> str:
    """"firing" during the cannon flash, "commanding" while any of the flagship's subagents runs, else "idle"."""
    if flash:
        return "firing"
    return "commanding" if any(a.status == "running" and a.parent_id and not a.ship for a in agents) else "idle"


def _captain_lines(pose: str, direction: int) -> list[str]:
    lines = _CAPTAIN[pose]
    return lines if direction > 0 else mirror(lines)


def _lanes(width: int, height: int) -> tuple[int, int]:
    return max(0, (height - 1) // LANE_H), max(0, width // SLOT_W)


def _apart(x: float, w: int, other: Boat) -> bool:
    """Whether a boat of width w at x clears `other` by at least a cell."""
    ow = sprite_width(sprite_key(other.flagship, other.tier))
    return x + w < other.x or other.x + ow < x


def layout(agents: list[Agent], width: int, height: int, prev: dict[str, Boat]) -> tuple[dict[str, Boat], int]:
    """Place one boat per agent, keeping earlier positions. Returns (boats, overflow count)."""
    lanes, per_lane = _lanes(width, height)
    # The flagship first (the cannon fires from it), then running agents and their leaders, so a pile of
    # finished boats can't crowd a running one out. The sort is stable: parents stay before their children.
    active = active_ids(agents)
    chosen = sorted(agents, key=lambda a: 0 if a.flagship else 1 if a.id in active else 2)[: lanes * per_lane]
    boats: dict[str, Boat] = {}
    for a in chosen:
        old = prev.get(a.id)
        t = tier(a.burn)
        w = sprite_width(sprite_key(a.flagship, t))
        if old and old.lane < lanes and 0 <= old.x <= width - w:
            boats[a.id] = Boat(a.id, old.x, old.lane, old.direction, t, a.flagship)
    siblings: dict[str, int] = {}
    for a in chosen:
        if a.id in boats:
            continue
        t = tier(a.burn)
        order = list(range(lanes))  # lane 0 is the waterline lane; fill it first
        parent = boats.get(a.parent_id) if a.parent_id else None
        if parent:  # siblings fan out over the lanes above their parent, so they never share a lane while one is free
            above = lanes - 1 - parent.lane
            pref = parent.lane + 1 + siblings.get(a.parent_id, 0) % above if above else parent.lane
            siblings[a.parent_id] = siblings.get(a.parent_id, 0) + 1
            order = [pref] + [l for l in order if l != pref]
        for lane in order:
            w = sprite_width(sprite_key(a.flagship, t))
            slot = next((s for s in range(per_lane)
                         if all(b.lane != lane or _apart(s * SLOT_W, w, b) for b in boats.values())), None)
            if slot is not None:
                boats[a.id] = Boat(a.id, float(slot * SLOT_W), lane, 1, t, a.flagship)
                break
    return boats, len(agents) - len(boats)


def render_harbor(agents: list[Agent], boats: dict[str, Boat], width: int, height: int, frame: int,
                  shots=(), flash: bool = False, captain: bool = True) -> Text:
    width, height = max(width, 1), max(height, 1)
    grid = [[(" ", "")] * width for _ in range(height)]
    grid[height - 1] = [("~", "dodger_blue3")] * width
    by_id = {a.id: a for a in agents}
    active = active_ids(agents)
    for b in sorted(boats.values(), key=lambda b: b.flagship):  # the flagship last, so a crossing boat can't hide the captain
        a = by_id.get(b.agent_id)
        if a is None:
            continue
        key = sprite_key(b.flagship, b.tier)
        sprite = SPRITES[key] if b.direction > 0 or not b.flagship else mirror(SPRITES[key])
        bob = ((frame // 4) + sum(map(ord, b.agent_id))) % 2  # bobbing: lift one row on alternate beats
        top = (height - 1) - (b.lane + 1) * LANE_H + (LANE_H - len(sprite)) - bob  # lane 0 sits on the water
        x0 = int(round(b.x))
        for dy, line in enumerate(sprite):
            y = top + dy
            for dx, ch in enumerate(line):
                x = x0 + dx
                if ch != " " and 0 <= y < height - 1 and 0 <= x < width:
                    grid[y][x] = (ch, model_color(a.model) if ch == SAIL else "bold bright_white" if ch in EMBLEM else "grey70")
        hull_y = top + len(sprite) - 1
        seated = captain and b.flagship and _seat_captain(
            grid, b, x0, hull_y, len(sprite[0]), height, CALL_OUT if flash else "zzz" if a.id not in active else "", captain_pose(agents, flash))
        if a.id in active:
            for i, ch in enumerate(WAKE):
                x = x0 - 1 - i if b.direction == 1 else x0 + len(sprite[0]) + i
                if 0 <= x < width and 0 <= hull_y < height - 1 and grid[hull_y][x][0] == " ":
                    grid[hull_y][x] = (ch, "dodger_blue3" if i < 2 else "grey42")
        elif not seated:
            zx = x0 + len(sprite[0]) // 2 + 1
            for i, ch in enumerate("zzz"):
                if 0 <= top - 1 < height - 1 and 0 <= zx + i < width and grid[top - 1][zx + i][0] == " ":
                    grid[top - 1][zx + i] = (ch, "grey50")
    if shots or flash:
        from agent_panel.effects import gunport, overlay  # effects imports Boat from here

        main = flagship_boat(boats)
        overlay(grid, list(shots), gunport(main) if flash and main else None)
    over = len(agents) - len(boats)
    if over > 0:
        label = f"+{over} more"[:width]
        for i, ch in enumerate(label):
            grid[0][width - len(label) + i] = (ch, "bold yellow")
    out = Text(no_wrap=True)
    for y, row in enumerate(grid):
        for ch, style in row:
            out.append(ch, style=style or None)
        if y < height - 1:
            out.append("\n")
    return out


def _seat_captain(grid, b: Boat, x0: int, hull_y: int, w: int, height: int, say: str, pose: str) -> bool:
    """Stand the captain on the clear stern deck of the main ship, with `say` above his hat. Returns False
    (nothing drawn) if he would leave the harbor; a call-out that doesn't fit is dropped, not the captain."""
    width = len(grid[0])
    figure = _captain_lines(pose, b.direction)
    cx = x0 if b.direction > 0 else x0 + w - CAPTAIN_W
    top = hull_y - len(figure)
    if cx < 0 or cx + CAPTAIN_W > width or top < 0 or hull_y > height - 2:
        return False
    for dy, line in enumerate(figure):
        for dx, ch in enumerate(line):
            if ch != " ":
                hat = dy < 2
                style = f"bold {CAPTAIN_COLOR}" if ch == SKULL else HAT_STYLE if hat else "bright_white"
                grid[top + dy][cx + dx] = (ch, style)
    y = top - 1
    if say and y >= 0 and cx + len(say) <= width and all(grid[y][cx + i][0] == " " for i in range(len(say))):
        for i, ch in enumerate(say):
            grid[y][cx + i] = (ch, "bold red" if say == CALL_OUT else "grey50")
    return True


def step(boats: dict[str, Boat], agents: list[Agent], dt: float, width: int) -> None:
    """Move sailing boats; running children follow their parent. Done and idle boats stay put.
    Lead boats (a ship, or a boat whose parent is anchored) turn around when they meet in a lane."""
    active = active_ids(agents)
    leaders = [boats[a.id] for a in agents if a.id in boats and a.id in active
               and not (a.parent_id in boats and a.parent_id in active)]
    followers: dict[str, int] = {}
    for a in agents:  # parents come before their children
        b = boats.get(a.id)
        if b is None or a.id not in active:
            continue
        parent = boats.get(a.parent_id) if a.parent_id else None
        if not parent or a.parent_id not in active:
            _sail(b, dt, width, [o for o in leaders if o is not b and o.lane == b.lane])
            continue
        k = followers[a.parent_id] = followers.get(a.parent_id, 0) + 1
        w = sprite_width(sprite_key(b.flagship, b.tier))
        b.direction = parent.direction
        lead = max(sprite_width(sprite_key(parent.flagship, parent.tier)) - SLOT_W, 0)  # a long flagship
        target = parent.x - parent.direction * SLOT_W * k + (lead if parent.direction < 0 else 0)
        if 0 <= target <= width - w:  # out of range (leader at an edge): hold, don't pile up
            b.x += (target - b.x) * min(1.0, 4 * dt)
        b.x = min(max(b.x, 0.0), float(max(width - w, 0)))


def _sail(b: Boat, dt: float, width: int, lane_leaders: list[Boat] = ()) -> None:
    w = sprite_width(sprite_key(b.flagship, b.tier))
    x = b.x + b.direction * SPEED * dt
    if any(not _apart(x, w, o) and (o.x - b.x) * b.direction > 0 for o in lane_leaders):
        b.direction = -b.direction  # another lead boat ahead: turn around, as at the harbor's edge
        return
    b.x = x
    if b.x > width - w:
        b.x, b.direction = float(max(width - w, 0)), -1
    elif b.x < 0:
        b.x, b.direction = 0.0, 1
