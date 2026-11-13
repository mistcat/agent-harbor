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
