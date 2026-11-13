"""Boat sprites and size tiers. Sail cells are drawn with SAIL so they can be colored by model."""
from typing import Literal

from rich.cells import cell_len

TIER_SLOOP = 50_000
TIER_GALLEON = 300_000  # main sessions pass this quickly, so the flagship looks it

SAIL = "▲"
CROSSBONES = "╳" if cell_len("╳") == 1 else "X"
SAIL_SKULL = "☠" if cell_len("☠") == 1 else "o"
EMBLEM = {CROSSBONES, SAIL_SKULL}  # Jolly Roger on the main ship's sail

_RAW = {
    "rowboat": ["  ▲  ", "  |  ", "\\___/"],
    "sloop": ["   ▲   ", "  ▲▲▲  ", "   |   ", "\\_____/"],
    "galleon": ["   ▲   ", "  ▲▲▲  ", " ▲▲▲▲▲ ", "▲▲▲▲▲▲▲", "   |   ", "\\_____/"],  # one tall sail
}
SPRITES: dict[str, list[str]] = {k: [l.ljust(max(map(len, v))) for l in v] for k, v in _RAW.items()}

# The main ship is longer: a clear stern deck (STERN_W columns plus a gap) behind the sails, where the captain stands.
STERN_W = 5
STERN_GAP = 1
MAIN_ROWS = 5  # captain (4 rows) plus the hull


def _jolly_roger(lines: list[str]) -> list[str]:
    """Crossbones in a middle sail row, a skull in the row above when that row is 3+ sail cells wide."""
    sail_rows = [i for i, l in enumerate(lines) if SAIL in l]
    cross = sail_rows[len(sail_rows) // 2]
    out = list(lines)
    mid = len(lines[0]) // 2
    out[cross] = out[cross][:mid] + CROSSBONES + out[cross][mid + 1:]
    if cross - 1 in sail_rows and lines[cross - 1].count(SAIL) >= 3:
        out[cross - 1] = out[cross - 1][:mid] + SAIL_SKULL + out[cross - 1][mid + 1:]
    return out


def _main_sprite(lines: list[str]) -> list[str]:
    lines = _jolly_roger(lines)
    pad = " " * (STERN_W + STERN_GAP)
    w = len(lines[0]) + len(pad)
    rows = [" " * w] * (MAIN_ROWS - len(lines)) + [pad + l for l in lines[:-1]]
    return rows + ["\\" + "_" * (w - 2) + "/"]


for _k in list(SPRITES):
    SPRITES["main_" + _k] = _main_sprite(SPRITES[_k])

_FLIP = str.maketrans("/\\", "\\/")


def mirror(lines: list[str]) -> list[str]:
    """The sprite seen from the other side (a boat sailing left)."""
    return [l.translate(_FLIP)[::-1] for l in lines]


def tier(burn: int) -> Literal["rowboat", "sloop", "galleon"]:
    if burn >= TIER_GALLEON:
        return "galleon"
    return "sloop" if burn >= TIER_SLOOP else "rowboat"


def sprite_key(agent_id: str, boat_tier: str) -> str:
    return "main_" + boat_tier if agent_id == "main" else boat_tier


def sprite_width(key: str) -> int:
    return len(SPRITES[key][0])
