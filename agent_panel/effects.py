"""Cannon shots: a gravity arc ending in a splash. Pure state, no terminal.

Coordinates: x in cells, y in cells *above the waterline* (0 = water).
"""
from dataclasses import dataclass

from agent_panel.boats import sprite_key, sprite_width
from agent_panel.harbor import Boat, lane_h

GRAVITY = 0.1
SPLASH_FRAMES = 4
FLASH_FRAMES = 3


@dataclass
class Shot:
    x: float
    y: float
    vx: float
    age: int = 0
    vy: float = 0.8
    splash: int = 0  # 0 = in flight; 1.. = splash animation


def fire(main_boat: Boat, index: int = 0) -> Shot:
    """A shot leaving the gunport on the side the boat faces. `index` fans out simultaneous shots."""
    w = sprite_width(sprite_key(main_boat.flagship, main_boat.tier))
    d = main_boat.direction
    x = main_boat.x + w if d > 0 else main_boat.x - 1
    return Shot(x=x, y=_hull_y(main_boat) + 0.5, vx=d * (1.4 + 0.25 * index), vy=0.8 + 0.15 * index)


def advance(shots: list[Shot]) -> list[Shot]:
    out = []
    for s in shots:
        s.age += 1
        if s.splash:
            s.splash += 1
            if s.splash > SPLASH_FRAMES:
                continue
        else:
            s.x += s.vx
            s.y += s.vy
            s.vy -= GRAVITY
            if s.y <= 0:
                s.y, s.splash = 0.0, 1
        out.append(s)
    return out


def gunport(boat: Boat) -> tuple[int, int]:
    """(x, y above waterline) of the gunport cell."""
    w = sprite_width(sprite_key(boat.flagship, boat.tier))
    return (int(round(boat.x)) + (w if boat.direction > 0 else -1), _hull_y(boat))


def _hull_y(boat: Boat) -> int:
    """The hull's height above the waterline: one more when a label row sits under it."""
    labelled = bool(boat.label)
    return boat.lane * lane_h(labelled) + 1 + labelled


def overlay(grid: list[list[tuple[str, str]]], shots: list[Shot], flash_at: tuple[int, int] | None) -> None:
    """Draw shots, splashes and the gunport flash onto a (char, style) grid; the last row is the water."""
    height, width = len(grid), len(grid[0])

    def put(x: int, y_above: int, ch: str, style: str) -> None:
        row = height - 1 - y_above
        if 0 <= row < height and 0 <= x < width:
            grid[row][x] = (ch, style)

    if flash_at:
        put(flash_at[0], flash_at[1], "✸", "bold bright_yellow")
    for s in shots:
        x = int(round(s.x))
        if s.splash:
            for dx, ch in ((0, "|") if s.splash == 1 else (-1, "'"), (0, "o") if s.splash > 1 else (1, ".")):
                put(x + dx, 1, ch, "bright_cyan")
        else:
            put(x, int(round(s.y)), "*", "bold bright_yellow")
