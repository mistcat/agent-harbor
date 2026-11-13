import argparse
from pathlib import Path

from agent_panel.session import Watcher, resolve_project


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="agent-panel",
        description="Read-only live view of a Claude Code session's agents.",
    )
    p.add_argument("--cwd", type=Path, default=Path.cwd(), help="project directory to follow (default: current)")
    p.add_argument("--config-dir", type=Path, default=None, help="Claude config dir (default: $CLAUDE_CONFIG_DIR, else the newest of ~/.claude*)")
    p.add_argument("--session", help="pin one session id instead of following the newest")
    p.add_argument("--no-sound", action="store_true", help="don't play the cannon sound on advisor calls")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    from agent_panel.app import AgentPanelApp
    from agent_panel.sound import Boomer

    args = parse_args(argv)
    cwd = args.cwd.resolve()
    # The watcher tolerates a project dir that doesn't exist yet and keeps polling for it.
    watcher = Watcher(lambda: resolve_project(cwd, args.config_dir, session=args.session), pinned=args.session)
    AgentPanelApp(watcher, cwd, Boomer(not args.no_sound)).run()
    return 0
