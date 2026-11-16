import time
from pathlib import Path

from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets import Static

from agent_panel.effects import FLASH_FRAMES, Shot, advance, fire
from agent_panel.harbor import Boat, layout, render_harbor, step
from agent_panel.model import Agent
from agent_panel.fleet import Fleet
from agent_panel.session import Snapshot, Watcher
from agent_panel.sound import Boomer
from agent_panel.tree import render_tree

POLL_S = 0.5
MIN_HARBOR_ROWS = 8
TREE_MAX_FRAC = 0.6


def fps_for(agents: list[Agent]) -> float:
    return 10 if any(a.status == "running" for a in agents) else 2


class AgentPanelApp(App):
    CSS = """
    #header { height: 1; background: $boost; color: $text; padding: 0 1; }
    #tree { height: auto; max-height: 60%; overflow-y: auto; }
    #harbor { height: 1fr; }
    """

    def __init__(self, watcher: Watcher | Fleet | None, waiting_dir: Path, boomer: Boomer | None = None, captain: bool = True):
        super().__init__()
        self.captain = captain
        self.boomer = boomer if boomer is not None else Boomer(True)
        self.shots: list[Shot] = []
        self.flash = 0
        self.watcher = watcher
        self.waiting_dir = waiting_dir
        self.snapshot: Snapshot | None = None
        self.frame = 0
        self.boats: dict[str, Boat] = {}
        self._fps = 2.0
        self._dt = 0.0
        self._timer = None
        self._last_tick = time.monotonic()
        self._shown: dict[str, Text] = {}  # last content per widget, so unchanged frames cost nothing

    def compose(self) -> ComposeResult:
        yield Static("agent-panel", id="header")
        yield Static("", id="tree")
        yield Static("", id="harbor")

    def on_mount(self) -> None:
        self.poll()
        self.set_interval(POLL_S, self.poll)
        self._timer = self.set_interval(1 / self._fps, self.tick)

    def poll(self) -> None:
        try:
            self.snapshot = self.watcher.poll() if self.watcher else None
        except Exception:  # a transcript shape we didn't expect: keep the last view, retry next tick
            pass
        self.paint()  # first, so the main boat exists to fire from
        if self.snapshot and self.snapshot.new_shots:
            self.fire_shots(self.snapshot.new_shots)
        self.set_fps(10 if self.shots or self.flash else fps_for(self.snapshot.agents) if self.snapshot else 2)

    def set_fps(self, fps: float) -> None:
        if fps != self._fps and self._timer is not None:
            self._fps = fps
            self._timer.stop()
            self._timer = self.set_interval(1 / fps, self.tick)

    def fire_shots(self, n: int) -> None:
        """One shot per new advisor call, one boom in total (the Boomer rate-limits anyway)."""
        main = self.boats.get("main")
        if main:
            self.shots += [fire(main, i) for i in range(n)]
            self.flash = FLASH_FRAMES
        self.boomer.boom(time.monotonic())

    def tick(self) -> None:
        now = time.monotonic()
        self._dt, self._last_tick = now - self._last_tick, now
        self.frame += 1
        self.shots = advance(self.shots)
        self.paint()
        self.flash = max(self.flash - 1, 0)
        self._dt = 0.0

    def paint(self) -> None:
        if not self.query("#tree"):  # a timer can fire before compose finishes or during shutdown
            return
        snap = self.snapshot
        header = self.query_one("#header", Static)
        tree = self.query_one("#tree", Static)
        if snap is None:
            header.update(f"agent-panel · {self.waiting_dir.name}")
            self._show(tree, Text(f" waiting for a Claude session in {self.waiting_dir}", style="dim"))
            self.query_one("#harbor", Static).display = False
            return
        ships = sum(a.parent_id is None for a in snap.agents)
        fleet = f" · {ships} ships" if ships > 1 else ""
        header.update(f"agent-panel · {snap.session_id[:8]} · {self.waiting_dir.name}{fleet}")
        width = tree.size.width or self.size.width
        rendered = render_tree(snap.agents, width, self.frame, snap.advisor_model)
        self._show(tree, rendered)
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
        step(self.boats, snap.agents, self._dt, width)
        self._show(harbor, render_harbor(snap.agents, self.boats, width, rows, self.frame, self.shots, self.flash > 0, self.captain))

    def _show(self, widget: Static, text: Text) -> None:
        if self._shown.get(widget.id) != text:
            self._shown[widget.id] = text
            widget.update(text)
