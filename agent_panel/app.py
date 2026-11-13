from pathlib import Path

from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets import Static

from agent_panel.session import Snapshot, Watcher
from agent_panel.tree import render_tree

POLL_S = 0.5
FRAME_S = 0.1


class AgentPanelApp(App):
    CSS = """
    #header { height: 1; background: $boost; color: $text; padding: 0 1; }
    #tree { height: auto; max-height: 60%; overflow-y: auto; }
    #harbor { height: 1fr; }
    """

    def __init__(self, watcher: Watcher | None, waiting_dir: Path):
        super().__init__()
        self.watcher = watcher
        self.waiting_dir = waiting_dir
        self.snapshot: Snapshot | None = None
        self.frame = 0

    def compose(self) -> ComposeResult:
        yield Static("agent-panel", id="header")
        yield Static("", id="tree")
        yield Static("", id="harbor")  # placeholder until the harbor view exists

    def on_mount(self) -> None:
        self.poll()
        self.set_interval(POLL_S, self.poll)
        self.set_interval(FRAME_S, self.tick)

    def poll(self) -> None:
        self.snapshot = self.watcher.poll() if self.watcher else None
        self.paint()

    def tick(self) -> None:
        self.frame += 1
        self.paint()

    def paint(self) -> None:
        snap = self.snapshot
        header = self.query_one("#header", Static)
        tree = self.query_one("#tree", Static)
        if snap is None:
            header.update(f"agent-panel · {self.waiting_dir.name}")
            tree.update(Text(f" waiting for a Claude session in {self.waiting_dir}", style="dim"))
            return
        header.update(f"agent-panel · {snap.session_id[:8]} · {self.waiting_dir.name}")
        width = tree.size.width or self.size.width
        tree.update(render_tree(snap.agents, width, self.frame, snap.advisor_model))
