from dataclasses import dataclass
from typing import Literal


@dataclass
class Agent:
    id: str
    parent_id: str | None
    depth: int
    label: str
    agent_type: str
    model: str  # short form, e.g. "sonnet 5.5"
    effort: str | None
    status: Literal["running", "done", "idle"]
    burn: int
    cache_read: int
    advisor_calls: int
    last_advisor_at: str | None
    linked: bool = True
    ship: str = ""  # the worktree ship this agent sails with; "" is the flagship's flotilla
    finished_at: float | None = None  # epoch seconds a done subagent last wrote to its transcript

    @property
    def flagship(self) -> bool:
        """The followed session itself: the root of the flagship's flotilla (captain, cannon, advisor line)."""
        return self.parent_id is None and not self.ship
