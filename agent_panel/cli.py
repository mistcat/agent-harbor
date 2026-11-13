import argparse
from pathlib import Path

from agent_panel.session import Watcher, config_dir, slug_dir


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="agent-panel",
        description="Read-only live view of a Claude Code session's agents.",
    )
    p.add_argument("--cwd", type=Path, default=Path.cwd(), help="project directory to follow (default: current)")
    p.add_argument("--session", help="pin one session id instead of following the newest")
    p.add_argument("--no-sound", action="store_true", help="don't play the cannon sound on advisor calls")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    from agent_panel.app import AgentPanelApp
    from agent_panel.sound import Boomer

    args = parse_args(argv)
    cwd = args.cwd.resolve()
    # The watcher tolerates a project dir that doesn't exist yet and keeps polling for it.
    watcher = Watcher(slug_dir(cwd, config_dir()), pinned=args.session)
    AgentPanelApp(watcher, cwd, Boomer(not args.no_sound)).run()
    return 0
