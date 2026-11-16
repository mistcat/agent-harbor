import asyncio
import subprocess
from pathlib import Path

from agent_panel.app import AgentPanelApp
from agent_panel.fleet import Fleet, git_worktrees
from agent_panel.harbor import layout, render_harbor
from agent_panel.session import Watcher, slug_dir
from agent_panel.tree import render_tree
from tests.helpers import advisor_call, agent_call
from tests.test_session import add_sub, make_session


def git(*args, cwd: Path):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True, capture_output=True)


def repo_with_worktrees(tmp_path: Path, names=("alpha", "beta")) -> tuple[Path, list[Path]]:
    root = tmp_path / "repo"
    root.mkdir()
    git("init", "-q", cwd=root)
    git("commit", "-q", "--allow-empty", "-m", "init", cwd=root)
    wts = []
    for n in names:
        wt = tmp_path / "repo-worktrees" / n
        git("worktree", "add", "-q", "-b", f"agent/{n}", str(wt), cwd=root)
        wts.append(wt.resolve())
    return root.resolve(), wts


def flotilla(cfg: Path, cwd: Path, sid: str, tool="toolu_1", desc="do thing"):
    proj = slug_dir(cwd, cfg)
    make_session(proj, sid, main_blocks=[agent_call(tool, desc)])
    add_sub(proj, sid, "a1", tool, finished=False, desc=desc)
    return proj


def test_git_worktrees_lists_main_and_worktrees(tmp_path):
    root, wts = repo_with_worktrees(tmp_path)
    assert git_worktrees(root) == [root, *wts]
    assert git_worktrees(wts[0]) == [root, *wts]


def test_git_worktrees_outside_a_repo_is_empty(tmp_path):
    assert git_worktrees(tmp_path) == []


def test_no_worktrees_matches_a_single_watcher(tmp_path):
    # --solo, not in a repo: exactly today's one-ship display.
    cfg, cwd = tmp_path / "cfg", tmp_path / "solo"
    cwd.mkdir()
    proj = flotilla(cfg, cwd.resolve(), "s1")
    add_sub(proj, "s1", "a2", "toolu_x")
    fleet, alone = Fleet(cwd, cfg).poll(), Watcher(proj).poll()
    assert fleet == alone
    assert [a.parent_id for a in fleet.agents].count(None) == 1


def test_lone_main_checkout_is_one_ship(tmp_path):
    root, _ = repo_with_worktrees(tmp_path, names=())
    cfg = tmp_path / "cfg"
    proj = flotilla(cfg, root, "s1")
    assert Fleet(root, cfg).poll() == Watcher(proj).poll()


def test_multi_worktree_fleet(tmp_path):
    root, (alpha, beta) = repo_with_worktrees(tmp_path)
    cfg = tmp_path / "cfg"
    flotilla(cfg, root, "ctrl", desc="controller work")
    flotilla(cfg, alpha, "sa", tool="toolu_a", desc="alpha task")
    flotilla(cfg, beta, "sb", tool="toolu_b", desc="beta task")
    snap = Fleet(root, cfg).poll()
    assert snap.session_id == "ctrl"
    ids = [a.id for a in snap.agents]
    assert ids == ["main", "a1", "alpha/main", "alpha/a1", "beta/main", "beta/a1"]
    roots = [a for a in snap.agents if a.parent_id is None]
    assert [(a.id, a.label, a.depth) for a in roots] == [("main", "main", 0), ("alpha/main", "alpha", 0), ("beta/main", "beta", 0)]
    by = {a.id: a for a in snap.agents}
    assert (by["alpha/a1"].parent_id, by["alpha/a1"].label, by["alpha/a1"].depth) == ("alpha/main", "alpha task", 1)
    assert by["beta/a1"].parent_id == "beta/main"


def test_flagship_is_the_cwd_worktree(tmp_path):
    # A panel beside an agent follows that agent; the controller and the other agent are the other ships.
    root, (alpha, beta) = repo_with_worktrees(tmp_path)
    cfg = tmp_path / "cfg"
    for cwd, sid in ((root, "ctrl"), (alpha, "sa"), (beta, "sb")):
        flotilla(cfg, cwd, sid)
    snap = Fleet(alpha, cfg).poll()
    assert snap.session_id == "sa"
    assert [a.label for a in snap.agents if a.parent_id is None] == ["main", "repo", "beta"]


def test_cwd_inside_a_worktree_skips_that_worktree(tmp_path):
    root, (alpha,) = repo_with_worktrees(tmp_path, names=("alpha",))
    cfg = tmp_path / "cfg"
    sub = alpha / "pkg"
    sub.mkdir()
    flotilla(cfg, sub, "inner")
    flotilla(cfg, alpha, "sa")
    flotilla(cfg, root, "ctrl")
    snap = Fleet(sub, cfg).poll()
    assert [a.label for a in snap.agents if a.parent_id is None] == ["main", "repo"]


def test_worktree_without_a_session_adds_no_ship(tmp_path):
    root, _ = repo_with_worktrees(tmp_path)
    cfg = tmp_path / "cfg"
    flotilla(cfg, root, "ctrl")
    assert [a.id for a in Fleet(root, cfg).poll().agents] == ["main", "a1"]


def test_no_flagship_session_is_waiting_even_with_ships(tmp_path):
    root, (alpha, _) = repo_with_worktrees(tmp_path)
    cfg = tmp_path / "cfg"
    flotilla(cfg, alpha, "sa")
    assert Fleet(root, cfg).poll() is None


def test_pin_applies_to_the_flagship_only(tmp_path):
    root, (alpha, _) = repo_with_worktrees(tmp_path)
    cfg = tmp_path / "cfg"
    make_session(slug_dir(root, cfg), "old", mtime=1000)
    make_session(slug_dir(root, cfg), "new", mtime=2000)
    flotilla(cfg, alpha, "sa")
    snap = Fleet(root, cfg, pinned="old").poll()
    assert snap.session_id == "old"
    assert "alpha/a1" in [a.id for a in snap.agents]


def test_ships_rescan_on_a_cadence(tmp_path):
    cfg, root = tmp_path / "cfg", tmp_path / "root"
    others = []
    calls = []

    def lister(cwd):
        calls.append(cwd)
        return [root, *others]

    root.mkdir()
    flotilla(cfg, root, "ctrl")
    fleet = Fleet(root, cfg, list_worktrees=lister)
    assert len(fleet.poll(now=100).agents) == 2
    late = tmp_path / "late"
    late.mkdir()
    flotilla(cfg, late, "sl")
    others.append(late)
    assert len(fleet.poll(now=101).agents) == 2  # not rescanned yet
    assert len(fleet.poll(now=106).agents) == 4
    assert len(calls) == 2
    others.clear()
    assert len(fleet.poll(now=112).agents) == 2  # a removed worktree's ship leaves


def test_duplicate_worktree_names_get_distinct_ids(tmp_path):
    cfg, root = tmp_path / "cfg", tmp_path / "root"
    a, b = tmp_path / "x" / "same", tmp_path / "y" / "same"
    for p, sid in ((root, "ctrl"), (a, "s1"), (b, "s2")):
        p.mkdir(parents=True)
        flotilla(cfg, p, sid)
    snap = Fleet(root, cfg, list_worktrees=lambda _: [root, a, b]).poll()
    ids = [x.id for x in snap.agents]
    assert len(ids) == len(set(ids))
    assert [x.label for x in snap.agents if x.parent_id is None] == ["main", "same", "same-2"]


def test_advisor_stays_with_the_flagship(tmp_path):
    root, (alpha, _) = repo_with_worktrees(tmp_path)
    cfg = tmp_path / "cfg"
    make_session(slug_dir(root, cfg), "ctrl")
    make_session(slug_dir(alpha, cfg), "sa", main_blocks=[advisor_call()])
    snap = Fleet(root, cfg).poll()
    assert snap.agents[0].advisor_calls == 0
    assert "advisor" not in render_tree(snap.agents, 50, 0, None).plain


def test_fleet_renders_at_50_columns(tmp_path):
    root, wts = repo_with_worktrees(tmp_path, names=("alpha", "beta", "a-rather-long-worktree-name"))
    cfg = tmp_path / "cfg"
    flotilla(cfg, root, "ctrl")
    for i, wt in enumerate(wts):
        flotilla(cfg, wt, f"s{i}")
    snap = Fleet(root, cfg).poll()
    tree = render_tree(snap.agents, 50, 0, None)
    lines = tree.plain.split("\n")
    assert len(lines) == 8 and all(len(l) <= 50 for l in lines)
    assert "a-rather-long-wo" in tree.plain or "…" in tree.plain
    boats, over = layout(snap.agents, 50, 20, {})
    assert "main" in boats and "alpha/main" in boats and over == len(snap.agents) - len(boats)
    render_harbor(snap.agents, boats, 50, 20, 0)
    small, over = layout(snap.agents, 50, 8, {})
    assert over > 0 and "main" in small
    assert f"+{over} more" in render_harbor(snap.agents, small, 50, 8, 0).plain


def test_app_header_counts_ships(tmp_path):
    root, (alpha, _) = repo_with_worktrees(tmp_path)
    cfg = tmp_path / "cfg"
    flotilla(cfg, root, "abcdef123456")
    flotilla(cfg, alpha, "sa", desc="alpha task")

    async def go():
        app = AgentPanelApp(Fleet(root, cfg), root)
        async with app.run_test(size=(50, 24)) as pilot:
            await pilot.pause(0.7)
            assert "alpha task" in str(app.query_one("#tree").content)
            assert str(app.query_one("#header").content) == "agent-panel · abcdef12 · repo · 2 ships"
    asyncio.run(go())
