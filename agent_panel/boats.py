"""Boat sprites and size tiers. Sail cells are drawn with SAIL so they can be colored by model."""
from typing import Literal

TIER_SLOOP = 50_000
TIER_GALLEON = 300_000  # main sessions pass this quickly, so the flagship looks it

SAIL = "▲"

_RAW = {
    "rowboat": ["  ▲  ", "  |  ", "\\___/"],
    "sloop": ["   ▲   ", "  ▲▲▲  ", "   |   ", "\\_____/"],
    "galleon": ["  ▲   ▲  ", " ▲▲▲ ▲▲▲ ", "▲▲▲▲▲▲▲▲▲", "   | |   ", "\\_______/"],
}
SPRITES: dict[str, list[str]] = {k: [l.ljust(max(map(len, v))) for l in v] for k, v in _RAW.items()}

# Future captain hook: set to a SPRITES key (e.g. "captain") to give the main session its own sprite.
MAIN_SPRITE_KEY: str | None = None


def tier(burn: int) -> Literal["rowboat", "sloop", "galleon"]:
    if burn >= TIER_GALLEON:
        return "galleon"
    return "sloop" if burn >= TIER_SLOOP else "rowboat"


def sprite_key(agent_id: str, boat_tier: str) -> str:
    return MAIN_SPRITE_KEY if agent_id == "main" and MAIN_SPRITE_KEY else boat_tier


def sprite_width(key: str) -> int:
    return len(SPRITES[key][0])
