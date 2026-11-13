from pathlib import Path

from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets import Static

from agent_panel.harbor import Boat, layout, render_harbor
from agent_panel.session import Snapshot, Watcher
from agent_panel.tree import render_tree

POLL_S = 0.5
MIN_HARBOR_ROWS = 8
TREE_MAX_FRAC = 0.6
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
        self.boats: dict[str, Boat] = {}

    def compose(self) -> ComposeResult:
        yield Static("agent-panel", id="header")
        yield Static("", id="tree")
        yield Static("", id="harbor")

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
            self.query_one("#harbor", Static).display = False
            return
        header.update(f"agent-panel · {snap.session_id[:8]} · {self.waiting_dir.name}")
        width = tree.size.width or self.size.width
        rendered = render_tree(snap.agents, width, self.frame, snap.advisor_model)
        tree.update(rendered)
        self.paint_harbor(snap, rendered.plain.count("\n") + 1)

    def paint_harbor(self, snap: Snapshot, tree_lines: int) -> None:
        harbor = self.query_one("#harbor", Static)
        tree_h = min(tree_lines, int(self.size.height * TREE_MAX_FRAC))
        rows = self.size.height - 1 - tree_h
        harbor.display = rows >= MIN_HARBOR_ROWS
        if not harbor.display:
            return
        width = self.size.width
        self.boats, _ = layout(snap.agents, width, rows, self.boats)
        harbor.update(render_harbor(snap.agents, self.boats, width, rows, self.frame))
