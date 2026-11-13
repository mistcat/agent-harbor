import argparse
from pathlib import Path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="agent-panel",
        description="Read-only live view of a Claude Code session's agents.",
    )
    p.add_argument("--cwd", type=Path, default=Path.cwd(), help="project directory to follow (default: current)")
    p.add_argument("--session", help="pin one session id instead of following the newest")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    parse_args(argv)
    return 0
