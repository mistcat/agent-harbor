"""Pure harbor layout and rendering: agents -> boats -> Rich Text."""
from dataclasses import dataclass

from rich.cells import cell_len
from rich.text import Text

from agent_panel.boats import EMBLEM, SAIL, SPRITES, STERN_W, mirror, sprite_key, sprite_width, tier
from agent_panel.colors import model_color
from agent_panel.model import Agent

SPEED = 6.0  # cells per second for a running boat
WAKE = "~-."  # nearest to farthest behind the hull
LANE_H = 7  # tallest sprite plus a row of clear water above it
SLOT_W = 10  # widest sprite plus a gap
PILE_STEP = 2  # docked boats fan out like a deck of cards, this many columns apart
PILE_W = 7  # the widest subagent sprite: the first card of the pile
LABEL_MAX = 8  # a ship label under a boat, ellipsis included
LABEL_MIN_W = 50  # narrower harbors drop the labels first
FLAGSHIP_LABEL = "Captain"
LABEL_STYLE = "dim"
CAPTAIN_COLOR = "yellow"  # the skull; not used by any model family
HAT_STYLE = "bold bright_white"
CAPTAIN_W = STERN_W
SKULL = "☠" if cell_len("☠") == 1 else "x"
CALL_OUT = "Fire!"
KEEP_DONE_S = 180  # a done subagent leaves the tree and the harbor this long after it finished
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
    label: str = ""  # the owning ship's name, shown under the hull when there are several ships
    labelled: bool = False  # the harbor shows label rows (see `labelled`), so the hull sits a row higher


def footprint(flagship: bool, boat_tier: str, label: str = "") -> int:
    """Columns a boat takes: its sprite, or its label when that is wider."""
    return max(sprite_width(sprite_key(flagship, boat_tier)), len(label))


def _width(b: Boat) -> int:
    return footprint(b.flagship, b.tier, b.label)


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


def _lanes(width: int, height: int, labelled: bool = False) -> tuple[int, int]:
    return max(0, (height - 1) // lane_h(labelled)), max(0, width // SLOT_W)


def lane_h(labelled: bool) -> int:
    """A lane's rows: with labels, one more for the label row under the hulls."""
    return LANE_H + labelled


def hull_row(height: int, lane: int, labelled: bool) -> int:
    """The grid row of a lane's hulls (bob lifts a sprite above it); its label row is the one below."""
    return (height - 2) - lane * lane_h(labelled) - labelled


def ship_labels(agents: list[Agent]) -> dict[str, str]:
    """Each ship's short label: "Captain" for the flagship's; for the others, the first word of the worktree
    name (after any "<repo>:") that no other ship on screen shares, cut to LABEL_MAX with an ellipsis.
    Labels are unique, ignoring case, and never read "Captain": ships that would still share one (the same
    worktree name in two repos, say) get a numbered label instead, e.g. "harbor-1" and "harbor-2"."""
    names = {a.ship: a.ship.rsplit(":", 1)[-1] for a in agents}
    words = {k: n.split("-") for k, n in names.items() if k}
    full = {}
    for k, name in names.items():
        if not k:
            continue
        w = words[k]
        shared = max((next((i for i, (x, y) in enumerate(zip(w, o)) if x != y), min(len(w), len(o)))
                      for j, o in words.items() if j != k), default=0)
        full[k] = (w[shared] if shared < len(w) else "") or name or k  # never empty: the word, the name, the key

    def cut(label: str) -> str:
        return label if len(label) <= LABEL_MAX else label[:LABEL_MAX - 1] + "…"

    out = {"": FLAGSHIP_LABEL} if "" in names else {}
    taken = {FLAGSHIP_LABEL.lower()}
    groups: dict[str, list[str]] = {}
    for k, label in full.items():
        groups.setdefault(cut(label).lower(), []).append(k)
    clashes = []
    for low, keys in groups.items():
        if len(keys) == 1 and low not in taken:
            out[keys[0]] = cut(full[keys[0]])
            taken.add(low)
        else:
            clashes += keys
    for k in clashes:
        n = 1
        while (label := full[k][:LABEL_MAX - len(f"-{n}")] + f"-{n}").lower() in taken:
            n += 1
        out[k] = label
        taken.add(label.lower())
    return {k: out[k] for k in names}


def labelled(agents: list[Agent], width: int, height: int) -> bool:
    """Labels show with more than one ship, at LABEL_MIN_W columns and up, and only while the harbor still has
    a lane with them and their extra row per lane doesn't cost it one of its first two lanes."""
    lanes, _ = _lanes(width, height)
    return (len({a.ship for a in agents}) > 1 and width >= LABEL_MIN_W
            and _lanes(width, height, True)[0] >= max(1, min(lanes, 2)))


def dock_size(width: int) -> tuple[int, int]:
    """(cards shown in the pile, pier width). Below 40 columns there is no dock, only a count."""
    if width >= 80:
        return 5, 6
    if width >= 40:
        return 3, 4
    return 0, 0


def dock_x(width: int) -> int:
    """Where the dock starts: the right end of lane 0's open water."""
    cards, pier = dock_size(width)
    return width - (PILE_W + PILE_STEP * (cards - 1) + 1 + pier) if cards else width


def lane_width(lane: int, width: int) -> int:
    """Open water in a lane: lane 0 ends at the dock."""
    return dock_x(width) if lane == 0 else width


def docked(agents: list[Agent]) -> list[Agent]:
    """Finished subagents that lead no running one: moored in the pile, oldest first, newest on top."""
    active = active_ids(agents)
    done = [a for a in agents if a.parent_id is not None and a.status == "done" and a.id not in active]
    return sorted(done, key=lambda a: a.finished_at if a.finished_at is not None else float("inf"))


def _apart(x: float, w: int, other: Boat) -> bool:
    """Whether a boat of width w at x clears `other` (its sprite and its label) by a blank cell, also after
    both positions are rounded to whole cells."""
    return x + w + 1 < other.x or other.x + _width(other) + 1 < x


def _clear(x: float, w: int, lane: int, boats, skip: Boat | None = None) -> bool:
    return all(b is skip or b.lane != lane or _apart(x, w, b) for b in boats)


def _blocked(b: Boat, x: float, w: int, boats) -> bool:
    """Whether moving b to x would run it into another boat in its lane. Boats that already overlap
    (after a resize or a tier upgrade) may still move apart."""
    heading = x - b.x
    return any(o is not b and o.lane == b.lane and not _apart(x, w, o) and (_apart(b.x, w, o) or (o.x - b.x) * heading > 0)
               for o in boats)


def layout(agents: list[Agent], width: int, height: int, prev: dict[str, Boat]) -> tuple[dict[str, Boat], int]:
    """Place one boat per sailing agent, keeping earlier positions. Finished subagents dock instead (see
    `docked`). Lane 0 is the flagship's (and the dock's) unless it is the only lane. No two boats in a lane
    ever overlap: an agent with no room left joins the overflow count. Returns (boats, overflow count)."""
    lab = labelled(agents, width, height)
    names = ship_labels(agents) if lab else {}
    lanes, _ = _lanes(width, height, lab)
    moored = {a.id for a in docked(agents)}
    active = active_ids(agents)
    # The flagship first (the cannon fires from it), then running agents and their leaders, so idle boats
    # can't crowd a running one out. The sort is stable: parents stay before their children.
    def rank(a: Agent) -> int:
        return 0 if a.flagship else 1 if a.id in active else 2

    sailors = sorted((a for a in agents if a.id not in moored), key=rank)

    def allowed(a: Agent) -> list[int]:
        return list(range(lanes)) if a.flagship or lanes == 1 else list(range(1, lanes))

    def kept(a: Agent) -> Boat | None:
        """The agent's boat from the last frame, if that position is still legal on its own."""
        old = prev.get(a.id)
        t = tier(a.burn)
        label = names.get(a.ship, "")
        w = footprint(a.flagship, t, label)
        if old and old.lane in allowed(a) and 0 <= old.x <= lane_width(old.lane, width) - w:
            return Boat(a.id, old.x, old.lane, old.direction, t, a.flagship, label, lab)
        return None

    # Tier by tier, each tier keeps its old positions and then places its newcomers before the next tier
    # is seated, so a boat from an earlier frame can't hold water a higher tier needs. A newcomer prefers a
    # slot that leaves lower tiers' old positions free and takes one only when there is no other room.
    tiers = [[a for a in sailors if rank(a) == r] for r in range(3)]
    olds = {a.id: b for a in sailors if (b := kept(a))}
    boats: dict[str, Boat] = {}
    siblings: dict[str, int] = {}
    for n, group in enumerate(tiers):
        for a in group:
            b = olds.get(a.id)
            if b and _clear(b.x, _width(b), b.lane, boats.values()):
                boats[a.id] = b
        later = [olds[a.id] for g in tiers[n + 1:] for a in g if a.id in olds]
        for a in group:
            if a.id in boats:
                continue
            t = tier(a.burn)
            order = allowed(a)  # lowest lane first
            parent = boats.get(a.parent_id) if a.parent_id else None
            if parent:  # siblings fan out over the lanes above their parent, so they never share a lane while one is free
                above = lanes - 1 - parent.lane
                pref = parent.lane + 1 + siblings.get(a.parent_id, 0) % above if above else parent.lane
                siblings[a.parent_id] = siblings.get(a.parent_id, 0) + 1
                order = [pref] + [l for l in order if l != pref] if pref in order else order
            label = names.get(a.ship, "")
            w = footprint(a.flagship, t, label)
            spot = None
            for others in ([*boats.values(), *later], list(boats.values())):
                spot = next(((lane, float(s * SLOT_W)) for lane in order for s in range(lane_width(lane, width) // SLOT_W + 1)
                             if s * SLOT_W + w <= lane_width(lane, width) and _clear(s * SLOT_W, w, lane, others)), None)
                if spot is not None:
                    break
            if spot is not None:
                boats[a.id] = Boat(a.id, spot[1], spot[0], 1, t, a.flagship, label, lab)
    return boats, len(sailors) - len(boats)


def render_harbor(agents: list[Agent], boats: dict[str, Boat], width: int, height: int, frame: int,
                  shots=(), flash: bool = False, captain: bool = True) -> Text:
    width, height = max(width, 1), max(height, 1)
    grid = [[(" ", "")] * width for _ in range(height)]
    grid[height - 1] = [("~", "dodger_blue3")] * width
    by_id = {a.id: a for a in agents}
    active = active_ids(agents)
    lab = labelled(agents, width, height)
    for b in sorted(boats.values(), key=lambda b: b.flagship):  # the flagship last, so a crossing boat can't hide the captain
        a = by_id.get(b.agent_id)
        if a is None:
            continue
        key = sprite_key(b.flagship, b.tier)
        sprite = SPRITES[key] if b.direction > 0 or not b.flagship else mirror(SPRITES[key])
        bob = _bob(b.agent_id, frame, sprite)
        top = hull_row(height, b.lane, lab) - len(sprite) + 1 - bob  # lane 0 sits on the water (or on its labels)
        x0 = int(round(b.x))
        if lab and b.label:  # under the hull, bobbing with it
            y = hull_row(height, b.lane, lab) + 1 - bob
            for i, ch in enumerate(b.label):
                if 0 <= y < height - 1 and 0 <= x0 + i < width:
                    grid[y][x0 + i] = (ch, LABEL_STYLE)
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
    over = len(agents) - len(docked(agents)) - len(boats)
    more = f"+{over} more"[:width] if over > 0 else ""
    _draw_dock(grid, docked(agents), width - len(more) - 1 if more else width, lab, ship_labels(agents) if lab else {})
    if shots or flash:
        from agent_panel.effects import gunport, overlay  # effects imports Boat from here

        main = flagship_boat(boats)
        overlay(grid, list(shots), gunport(main) if flash and main else None)
    for i, ch in enumerate(more):
        grid[0][width - len(more) + i] = (ch, "bold yellow")
    out = Text(no_wrap=True)
    for y, row in enumerate(grid):
        for ch, style in row:
            out.append(ch, style=style or None)
        if y < height - 1:
            out.append("\n")
    return out


def _bob(agent_id: str, frame: int, sprite: list[str]) -> int:
    """Lift a boat one row on alternate beats, but only when that still leaves its lane a clear top row."""
    return ((frame // 4) + sum(map(ord, agent_id))) % 2 if len(sprite) <= LANE_H - 2 else 0


def _draw_dock(grid, moored: list[Agent], room: int, lab: bool = False, names: dict[str, str] | None = None) -> None:
    """The pier at the right end of lane 0, with the newest finished boats fanned against it like a deck of
    cards and a count of the ones that don't fit. Below 40 columns only the count is shown, top left, in at
    most `room` columns (the overflow count holds the right end of that row): shortened to "+N", or dropped.
    With labels, the pile's ships are named once under it when the names fit."""
    height, width = len(grid), len(grid[0])
    cards, pier = dock_size(width)
    hidden = len(moored) - min(len(moored), cards)
    if not cards:
        text = next((t for t in (f"+{hidden} docked", f"+{hidden}") if len(t) <= room), "")
        if hidden and height > 1:
            for i, ch in enumerate(text):
                grid[0][i] = (ch, "green")
        return
    hull_y = hull_row(height, 0, lab)
    x0 = dock_x(width)
    px = width - pier
    if hull_y < 1:
        return
    for x in range(px, width):  # the planks, on posts that stand in the water
        grid[hull_y][x] = ("╤" if (x - px) % 3 == 0 else "═", "tan")
        if (x - px) % 3 == 0:
            for y in range(hull_y + 1, height):
                grid[y][x] = ("║", "tan")
    shown = moored[len(moored) - min(len(moored), cards):]
    for i, a in enumerate(shown):  # oldest first, so the newest lies on top
        sprite = SPRITES[tier(a.burn)]
        x = px - 1 - sprite_width(tier(a.burn)) - PILE_STEP * (len(shown) - 1 - i)
        top = hull_y - len(sprite) + 1
        for dy, line in enumerate(sprite):
            for dx, ch in enumerate(line):
                if ch != " " and top + dy >= 0 and x0 <= x + dx < px:
                    grid[top + dy][x + dx] = (ch, model_color(a.model) if ch == SAIL else "grey50")
    if lab and shown:
        text = " ".join(dict.fromkeys((names or {}).get(a.ship, "") for a in shown))
        if 0 < len(text) <= px - x0:
            for i, ch in enumerate(text):
                grid[hull_y + 1][px - 1 - len(text) + i + 1] = (ch, LABEL_STYLE)
    if hidden:
        label = f"+{hidden}"[:pier]
        for i, ch in enumerate(label):
            grid[hull_y - 1][px + i] = (ch, "green")


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
    """Move sailing boats; running children follow their parent. Idle boats stay put.

    No move ever makes two boats in a lane overlap. A lead boat (a ship, a boat whose parent is anchored,
    or a child sharing its parent's lane) turns around when it meets another boat or the end of its open
    water; a follower that is blocked holds its place. Followers rank by how far astern they are, so after
    the leader turns they never have to sail through each other."""
    active = active_ids(agents)
    by_parent: dict[str, list[Boat]] = {}
    for a in agents:  # parents come before their children
        b = boats.get(a.id)
        if b is None or a.id not in active:
            continue
        parent = boats.get(a.parent_id) if a.parent_id else None
        if not parent or a.parent_id not in active or parent.lane == b.lane:
            _sail(b, dt, lane_width(b.lane, width), boats.values())
        else:
            by_parent.setdefault(a.parent_id, []).append(b)
    for pid, kids in by_parent.items():
        parent = boats[pid]
        lead = max(_width(parent) - SLOT_W, 0)  # a long flagship
        for k, b in enumerate(sorted(kids, key=lambda b: -b.x * parent.direction), start=1):
            w = _width(b)
            b.direction = parent.direction
            target = parent.x - parent.direction * SLOT_W * k + (lead if parent.direction < 0 else 0)
            room = lane_width(b.lane, width) - w
            if not 0 <= target <= room:  # out of range (leader at an edge): hold, don't pile up
                continue
            x = min(max(b.x + (target - b.x) * min(1.0, 4 * dt), 0.0), float(max(room, 0)))
            if not _blocked(b, x, w, boats.values()):
                b.x = x


def _sail(b: Boat, dt: float, room: int, others) -> None:
    w = _width(b)
    x = b.x + b.direction * SPEED * dt
    if x > room - w:
        x, turn = float(max(room - w, 0)), True
    elif x < 0:
        x, turn = 0.0, True
    else:
        turn = False
    if _blocked(b, x, w, others):  # another boat ahead: turn around, as at an edge
        b.direction = -b.direction
        return
    b.x = x
    if turn:
        b.direction = -1 if x > 0 else 1
