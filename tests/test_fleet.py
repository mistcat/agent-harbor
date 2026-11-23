import asyncio
import subprocess
from pathlib import Path

import pytest

from agent_panel.app import AgentPanelApp
from agent_panel.fleet import Fleet, git_worktrees
from agent_panel.harbor import layout, render_harbor
from agent_panel.session import Watcher, slug_dir
from agent_panel.tree import render_tree
from tests.helpers import advisor_call, agent_call
from tests.test_session import add_sub, make_session


def git(*args, cwd: Path):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True, capture_output=True)


def repo_with_worktrees(tmp_path: Path, names=("alpha", "beta"), repo="repo") -> tuple[Path, list[Path]]:
    root = tmp_path / repo
    root.mkdir(parents=True)
    git("init", "-q", cwd=root)
    git("commit", "-q", "--allow-empty", "-m", "init", cwd=root)
    wts = []
    for n in names:
        wt = tmp_path / f"{repo}-worktrees" / n
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


def test_main_is_reserved_for_the_flagship(tmp_path):
    cfg, root, wt = tmp_path / "cfg", tmp_path / "root", tmp_path / "wts" / "main"
    for p, sid in ((root, "ctrl"), (wt, "s1")):
        p.mkdir(parents=True)
        flotilla(cfg, p, sid)
    snap = Fleet(root, cfg, list_worktrees=lambda _: [root, wt]).poll()
    assert [a.label for a in snap.agents if a.parent_id is None] == ["main", "main-2"]
    assert [a.flagship for a in snap.agents] == [True, False, False, False]


def test_ship_keys_do_not_shift_when_a_namesake_starts_a_session(tmp_path):
    cfg, root = tmp_path / "cfg", tmp_path / "root"
    a, b = tmp_path / "x" / "same", tmp_path / "y" / "same"
    for p in (root, a, b):
        p.mkdir(parents=True)
    flotilla(cfg, root, "ctrl")
    flotilla(cfg, b, "s2")  # only the second namesake has a session yet
    fleet = Fleet(root, cfg, list_worktrees=lambda _: [root, a, b])
    before = [x.id for x in fleet.poll(now=100).agents if x.ship]
    flotilla(cfg, a, "s1")
    after = [x.id for x in fleet.poll(now=106).agents if x.ship]
    assert before == ["same-2/main", "same-2/a1"]
    assert after == ["same/main", "same/a1", "same-2/main", "same-2/a1"]


def test_cwd_in_another_case_is_still_the_flagship(tmp_path):
    cfg, root = tmp_path / "cfg", tmp_path / "Root"
    root.mkdir()
    flipped = root.parent / "rOOT"
    if not flipped.exists():
        pytest.skip("case-sensitive filesystem")
    flotilla(cfg, root.resolve(), "ctrl")
    snap = Fleet(root, cfg, list_worktrees=lambda _: [flipped]).poll()
    assert [a.id for a in snap.agents] == ["main", "a1"]


def test_ship_project_dirs_resolve_once_per_scan(tmp_path, monkeypatch):
    import agent_panel.fleet as fleet_mod
    cfg, root, wt = tmp_path / "cfg", tmp_path / "root", tmp_path / "wt"
    for p, sid in ((root, "ctrl"), (wt, "s1")):
        p.mkdir()
        flotilla(cfg, p, sid)
    calls = []
    real = fleet_mod.resolve_project
    monkeypatch.setattr(fleet_mod, "resolve_project", lambda p, *a, **k: calls.append(p) or real(p, *a, **k))
    fleet = Fleet(root, cfg, list_worktrees=lambda _: [root, wt])
    for t in (100, 100.5, 101, 101.5):
        fleet.poll(now=t)
    assert calls.count(wt) == 1


def test_advisor_line_closes_the_flagship_flotilla(tmp_path):
    root, (alpha, _) = repo_with_worktrees(tmp_path)
    cfg = tmp_path / "cfg"
    proj = slug_dir(root, cfg)
    make_session(proj, "ctrl", main_blocks=[agent_call("toolu_1", "ctrl task"), advisor_call()])
    add_sub(proj, "ctrl", "a1", "toolu_1", desc="ctrl task")
    flotilla(cfg, alpha, "sa", desc="alpha task")
    snap = Fleet(root, cfg).poll()
    ls = render_tree(snap.agents, 50, 0, None).plain.split("\n")
    adv = next(i for i, l in enumerate(ls) if "advisor" in l)
    assert "ctrl task" in ls[adv - 1] and "alpha" in ls[adv + 1]


def test_other_ships_are_plain_boats_and_do_not_command_the_captain(tmp_path):
    from agent_panel.harbor import captain_pose
    root, (alpha, _) = repo_with_worktrees(tmp_path)
    cfg = tmp_path / "cfg"
    make_session(slug_dir(root, cfg), "ctrl")
    make_session(slug_dir(alpha, cfg), "sa")
    snap = Fleet(root, cfg).poll()
    assert [(a.id, a.status) for a in snap.agents] == [("main", "running"), ("alpha/main", "running")]
    assert captain_pose(snap.agents, False) == "idle"
    boats, _ = layout(snap.agents, 50, 20, {})
    assert boats["main"].flagship and not boats["alpha/main"].flagship


# ---- --also-repo ----

def two_repos(tmp_path):
    """Repo `repo` (the controller's, worktree alpha) and repo `harbor` (worktrees alpha and prune), each
    worktree and both main checkouts with a session."""
    a_root, (a_alpha,) = repo_with_worktrees(tmp_path / "a", names=("alpha",))
    b_root, (b_alpha, b_prune) = repo_with_worktrees(tmp_path / "b", names=("alpha", "prune"), repo="harbor")
    cfg = tmp_path / "cfg"
    for cwd, sid in ((a_root, "ctrl"), (a_alpha, "sa"), (b_root, "harbor-ctrl"), (b_alpha, "sb"), (b_prune, "sp")):
        flotilla(cfg, cwd, sid)
    return cfg, a_root, b_root


def ship_labels(snap):
    return [a.label for a in snap.agents if a.parent_id is None]


def test_also_repo_adds_that_repos_worktrees_but_not_its_main_checkout(tmp_path):
    cfg, a_root, b_root = two_repos(tmp_path)
    snap = Fleet(a_root, cfg, also_repos=[b_root]).poll()
    assert snap.session_id == "ctrl"
    # A worktree called alpha in both repos: the other repo's ships carry its name.
    assert ship_labels(snap) == ["main", "alpha", "harbor:alpha", "harbor:prune"]
    assert "harbor:prune/a1" in [a.id for a in snap.agents]


def test_without_the_flag_the_other_repo_is_not_shown(tmp_path):
    cfg, a_root, _ = two_repos(tmp_path)
    assert ship_labels(Fleet(a_root, cfg).poll()) == ["main", "alpha"]
    assert Fleet(a_root, cfg).poll() == Fleet(a_root, cfg, also_repos=[]).poll()


def test_also_repo_from_inside_one_of_its_worktrees_uses_the_main_checkouts_name(tmp_path):
    cfg, a_root, b_root = two_repos(tmp_path)
    prune = [p for p in git_worktrees(b_root) if p.name == "prune"][0]
    assert ship_labels(Fleet(a_root, cfg, also_repos=[prune / "."]).poll())[2:] == ["harbor:alpha", "harbor:prune"]


def test_two_also_repos_with_the_same_name_get_a_suffix(tmp_path):
    me, x, y = tmp_path / "me", tmp_path / "x" / "repo", tmp_path / "y" / "repo"
    listed = {me: [me], x: [x, tmp_path / "x" / "alpha"], y: [y, tmp_path / "y" / "alpha"]}
    for p in [*listed[x], *listed[y], me]:
        p.mkdir(parents=True, exist_ok=True)
    fleet = Fleet(me, tmp_path / "cfg", list_worktrees=lambda p: listed.get(p, []), also_repos=[x, y])
    fleet._rescan()
    assert list(fleet.keys.values()) == ["repo:alpha", "repo:alpha-2"]


def test_unreadable_or_non_git_also_repos_are_skipped(tmp_path):
    cfg, a_root, _ = two_repos(tmp_path)
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    snap = Fleet(a_root, cfg, also_repos=[plain, tmp_path / "missing"]).poll()
    assert ship_labels(snap) == ["main", "alpha"]


def test_also_repo_naming_the_flagships_own_repo_adds_nothing_twice(tmp_path):
    cfg, a_root, _ = two_repos(tmp_path)
    assert ship_labels(Fleet(a_root, cfg, also_repos=[a_root]).poll()) == ["main", "alpha"]


def test_the_main_checkouts_session_is_marked_the_controller(tmp_path):
    root, (alpha, beta) = repo_with_worktrees(tmp_path)
    cfg = tmp_path / "cfg"
    flotilla(cfg, root, "ctrl")
    flotilla(cfg, alpha, "sa", tool="toolu_a")
    flotilla(cfg, beta, "sb", tool="toolu_b")
    roots = {a.id: a for a in Fleet(alpha, cfg).poll().agents if a.parent_id is None}  # the panel beside agent alpha
    assert {k: (a.controller, a.worktree) for k, a in roots.items()} == {
        "main": (False, "alpha"), "repo/main": (True, "repo"), "beta/main": (False, "beta")}
    roots = {a.id: a for a in Fleet(root, cfg).poll().agents if a.parent_id is None}  # beside the controller
    assert roots["main"].controller and not roots["alpha/main"].controller
    assert [a.label for a in roots.values()] == ["main", "alpha", "beta"]  # the tree's labels don't change
