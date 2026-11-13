"""Pure harbor layout and rendering: agents -> boats -> Rich Text."""
from dataclasses import dataclass

from rich.text import Text

from agent_panel.boats import SAIL, SPRITES, sprite_key, sprite_width, tier
from agent_panel.colors import model_color
from agent_panel.model import Agent

SPEED = 6.0  # cells per second for a running boat
WAKE = "~-."  # nearest to farthest behind the hull
LANE_H = 5  # tallest sprite
SLOT_W = 10  # widest sprite plus a gap


@dataclass
class Boat:
    agent_id: str
    x: float
    lane: int
    direction: int
    tier: str


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


def _lanes(width: int, height: int) -> tuple[int, int]:
    return max(0, (height - 1) // LANE_H), max(0, width // SLOT_W)


def layout(agents: list[Agent], width: int, height: int, prev: dict[str, Boat]) -> tuple[dict[str, Boat], int]:
    """Place one boat per agent, keeping earlier positions. Returns (boats, overflow count)."""
    lanes, per_lane = _lanes(width, height)
    chosen = agents[: lanes * per_lane]
    boats: dict[str, Boat] = {}
    for a in chosen:
        old = prev.get(a.id)
        t = tier(a.burn)
        w = sprite_width(sprite_key(a.id, t))
        if old and old.lane < lanes and 0 <= old.x <= width - w:
            boats[a.id] = Boat(a.id, old.x, old.lane, old.direction, t)
    for a in chosen:
        if a.id in boats:
            continue
        t = tier(a.burn)
        order = list(range(lanes))  # lane 0 is the waterline lane; fill it first
        parent = boats.get(a.parent_id) if a.parent_id else None
        if parent:  # a child sails in the lane above its parent when there is one
            pref = parent.lane + 1 if parent.lane + 1 < lanes else parent.lane
            order = [pref] + [l for l in order if l != pref]
        for lane in order:
            slot = next((s for s in range(per_lane)
                         if all(b.lane != lane or abs(b.x - s * SLOT_W) >= SLOT_W for b in boats.values())), None)
            if slot is not None:
                boats[a.id] = Boat(a.id, float(slot * SLOT_W), lane, 1, t)
                break
    return boats, len(agents) - len(boats)


def render_harbor(agents: list[Agent], boats: dict[str, Boat], width: int, height: int, frame: int,
                  shots=(), flash: bool = False) -> Text:
    width, height = max(width, 1), max(height, 1)
    grid = [[(" ", "")] * width for _ in range(height)]
    grid[height - 1] = [("~", "dodger_blue3")] * width
    by_id = {a.id: a for a in agents}
    active = active_ids(agents)
    for b in boats.values():
        a = by_id.get(b.agent_id)
        if a is None:
            continue
        key = sprite_key(b.agent_id, b.tier)
        sprite = SPRITES[key]
        bob = ((frame // 4) + sum(map(ord, b.agent_id))) % 2  # bobbing: lift one row on alternate beats
        top = (height - 1) - (b.lane + 1) * LANE_H + (LANE_H - len(sprite)) - bob  # lane 0 sits on the water
        x0 = int(round(b.x))
        for dy, line in enumerate(sprite):
            y = top + dy
            for dx, ch in enumerate(line):
                x = x0 + dx
                if ch != " " and 0 <= y < height - 1 and 0 <= x < width:
                    grid[y][x] = (ch, model_color(a.model) if ch == SAIL else "grey70")
        hull_y = top + len(sprite) - 1
        if a.id in active:
            for i, ch in enumerate(WAKE):
                x = x0 - 1 - i if b.direction == 1 else x0 + len(sprite[0]) + i
                if 0 <= x < width and 0 <= hull_y < height - 1 and grid[hull_y][x][0] == " ":
                    grid[hull_y][x] = (ch, "dodger_blue3" if i < 2 else "grey42")
        else:
            zx = x0 + len(sprite[0]) // 2 + 1
            for i, ch in enumerate("zzz"):
                if 0 <= top - 1 < height - 1 and 0 <= zx + i < width and grid[top - 1][zx + i][0] == " ":
                    grid[top - 1][zx + i] = (ch, "grey50")
    if shots or flash:
        from agent_panel.effects import gunport, overlay  # effects imports Boat from here

        main = boats.get("main")
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


def step(boats: dict[str, Boat], agents: list[Agent], dt: float, width: int) -> None:
    """Move sailing boats; running children follow their parent. Done and idle boats stay put."""
    active = active_ids(agents)
    followers: dict[str, int] = {}
    for a in agents:  # parents come before their children
        b = boats.get(a.id)
        if b is None or a.id not in active:
            continue
        w = sprite_width(sprite_key(b.agent_id, b.tier))
        parent = boats.get(a.parent_id) if a.parent_id else None
        if parent and a.parent_id in active:
            k = followers[a.parent_id] = followers.get(a.parent_id, 0) + 1
            target = parent.x - parent.direction * SLOT_W * k
            b.direction = parent.direction
            b.x += (target - b.x) * min(1.0, 4 * dt)
            b.x = min(max(b.x, 0.0), float(max(width - w, 0)))
            continue
        b.x += b.direction * SPEED * dt
        if b.x > width - w:
            b.x, b.direction = float(max(width - w, 0)), -1
        elif b.x < 0:
            b.x, b.direction = 0.0, 1
