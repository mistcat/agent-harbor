"""Run the real bin/agent-session and bin/agent-stop-hook against a temp git repo.

`rex` and `claude` are fakes first on PATH: the fake rex appends each call's argv as one JSON
line to rex.log and prints canned JSON, so tests read back exactly what the script asked for.
"""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

BIN = Path(__file__).resolve().parent.parent / "bin"
SESSION = BIN / "agent-session"
HOOK = BIN / "agent-stop-hook"

FAKE_REX = """#!/usr/bin/env python3
import json, os, sys
with open(os.environ["REX_LOG"], "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\\n")
a = sys.argv[1:]
if a[:1] == ["new"] or a[:2] == ["window", "new"]:
    print(json.dumps({"session_id": "sess-1", "block_ids": ["b1"],
                      "initial_windows": [{"window_id": "w1", "block_ids": ["agent-b"]}]}))
elif a[:1] == ["split"]:
    print(json.dumps({"block_ids": ["panel-b"]}))
elif a[:2] == ["window", "ls"]:
    sid = a[a.index("-s") + 1]
    def win(label, block):
        return {"window_id": "w-" + label, "label": label,
                "layers": [{"blocks": [{"block_id": block}]}]}
    print(json.dumps({"session_id": sid, "windows": [win("Tests", "tests-" + sid), win("Agent", "agentblock-" + sid)]}))
elif a[:2] == ["ls", "--json"]:
    print(os.environ.get("FAKE_SESSIONS", json.dumps({"sessions": []})))
elif a[:3] == ["client", "ls", "--json"]:
    print(json.dumps({"clients": []}))
"""


def run(cmd, cwd, env=None, **kw):
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, **kw)


def git(cwd, *args):
    r = run(["git", *args], cwd)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


@pytest.fixture
def world(tmp_path):
    fake = tmp_path / "fakebin"
    fake.mkdir()
    for name, body in (("rex", FAKE_REX), ("claude", "#!/bin/sh\nexit 0\n")):
        p = fake / name
        p.write_text(body)
        p.chmod(0o755)

    origin = tmp_path / "origin.git"
    repo = tmp_path / "proj"
    run(["git", "init", "-q", "--bare", str(origin)], tmp_path)
    run(["git", "init", "-q", "-b", "trunk", str(repo)], tmp_path)
    for k, v in (("user.name", "t"), ("user.email", "t@example.com")):
        git(repo, "config", k, v)
    (repo / ".gitignore").write_text(".env\n.dev.vars\n.agent-session/\n")
    (repo / "README").write_text("hi\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "init")
    git(repo, "remote", "add", "origin", str(origin))
    git(repo, "push", "-q", "-u", "origin", "trunk")
    git(repo, "remote", "set-head", "origin", "trunk")
    (repo / ".env").write_text("SECRET=1\n")

    state = tmp_path / "state"
    env = {
        **os.environ,
        "PATH": f"{fake}:{os.environ['PATH']}",
        "REX_LOG": str(tmp_path / "rex.log"),
        "XDG_STATE_HOME": str(state),
        "HOME": str(tmp_path),
        "SHELL": "/bin/sh",
    }
    for k in ("AGENT_SESSION_INBOX", "AGENT_SESSION_CONTROLLER_MODEL", "AGENT_SESSION_ADVISOR_MODEL"):
        env.pop(k, None)

    class W:
        pass

    w = W()
    w.repo, w.env, w.state, w.tmp = repo, env, state, tmp_path
    w.session = lambda *args: run([str(SESSION), *args], repo, env)
    w.config = lambda name, text: (
        (repo / ".agent-session").mkdir(exist_ok=True),
        (repo / ".agent-session" / name).write_text(text),
    )

    def calls():
        log = tmp_path / "rex.log"
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    w.calls = calls
    w.rex_call = lambda verb: next(c for c in calls() if c[0] == verb)
    return w


def agent_args(call):
    """Everything after the `--` that separates rex flags from the command to run."""
    return call[call.index("--") + 1:]


def test_new_branches_from_detected_base_and_copies_files(world):
    world.config("config", "COPY_FILES=.env worker/.dev.vars missing.txt\n")
    (world.repo / "worker").mkdir()
    (world.repo / "worker" / ".dev.vars").write_text("X=1\n")
    r = world.session("new", "alpha")
    assert r.returncode == 0, r.stderr
    wt = world.tmp / "proj-worktrees" / "alpha"
    assert git(wt, "branch", "--show-current") == "agent/alpha"
    assert git(wt, "rev-parse", "HEAD") == git(world.repo, "rev-parse", "origin/trunk")
    assert (wt / ".env").read_text() == "SECRET=1\n"
    assert (wt / "worker" / ".dev.vars").read_text() == "X=1\n"
    assert not (wt / "missing.txt").exists()
    assert "missing.txt not found" in r.stderr


def test_config_is_never_executed(world):
    pwned = world.tmp / "pwned"
    bt = world.tmp / "pwned2"
    world.config(
        "config",
        f'PREFIX="zz-"\nCOPY_FILES=$(touch {pwned})\nPRACTICE_DOC=`touch {bt}`\n$(touch {pwned})\n',
    )
    world.session("new", "alpha", "--prompt", "x")
    assert not pwned.exists() and not bt.exists()


@pytest.mark.parametrize("entry", ["../x", "/etc/passwd", "a/../b"])
def test_copy_files_rejects_escaping_paths(world, entry):
    world.config("config", f"COPY_FILES=.env {entry}\n")
    r = world.session("new", "alpha")
    assert r.returncode != 0
    assert "COPY_FILES" in r.stderr
    assert not (world.tmp / "proj-worktrees" / "alpha").exists()


@pytest.mark.parametrize("line", ["PRACTICE_DOC=/etc/passwd", "PRACTICE_DOC=../x.md", "PREFIX=Bad_Prefix",
                                  "CONTROLLER_MODEL=a\"b", "ADVISOR_MODEL=x\",\"y"])
def test_invalid_values_are_refused(world, line):
    world.config("config", line + "\n")
    r = world.session("controller")
    assert r.returncode != 0
    assert world.calls() == []


def test_unknown_key_warns_but_runs(world):
    world.config("config", "# comment\n\nBOGUS=1\nPREFIX='qq-'\n")
    r = world.session("new", "alpha", "--prompt", "x")
    assert r.returncode == 0, r.stderr
    assert "BOGUS" in r.stderr
    assert world.rex_call("new")[1] == "qq-alpha"


def test_new_falls_back_to_master_without_origin_head(world):
    git(world.repo, "remote", "set-head", "origin", "-d")
    git(world.repo, "push", "-q", "origin", "trunk:master")
    r = world.session("new", "beta")
    assert r.returncode == 0, r.stderr
    wt = world.tmp / "proj-worktrees" / "beta"
    assert git(wt, "rev-parse", "HEAD") == git(world.repo, "rev-parse", "origin/master")


def test_default_prefix_is_repo_dir_name_and_label_uses_it(world):
    world.session("new", "alpha", "--prompt", "do it")
    assert world.rex_call("new")[1] == "proj-alpha"


def test_prefix_from_config_is_used_in_rex_label(world):
    world.config("config", 'PREFIX="zz-"\n')
    r = world.session("new", "alpha", "--prompt", "do it")
    assert r.returncode == 0, r.stderr
    assert world.rex_call("new")[1] == "zz-alpha"
    assert "(zz-alpha)" in r.stdout


def test_preamble_includes_agent_rules_and_task(world):
    world.config("agent-rules.md", "- MARKER-RULE: never touch the moon.\n")
    world.session("new", "alpha", "--prompt", "build the thing")
    prompt = agent_args(world.rex_call("new"))[-1]
    assert "MARKER-RULE: never touch the moon." in prompt
    assert "git branch --show-current" in prompt
    assert prompt.rstrip().endswith("build the thing")
    assert "master" not in prompt


def test_agent_gets_name_and_xdg_inbox(world):
    world.config("config", 'PREFIX="zz-"\n')
    world.session("new", "alpha", "--prompt", "x")
    args = agent_args(world.rex_call("new"))
    inbox = f"{world.state}/agent-session/zz/inbox"
    assert "AGENT_SESSION_NAME=alpha" in args
    assert f"AGENT_SESSION_INBOX={inbox}" in args


def test_inbox_env_override_and_reading(world):
    inbox = world.state / "agent-session" / "proj" / "inbox"
    inbox.mkdir(parents=True)
    (inbox / "a-200").write_text("second\n")
    (inbox / "b-100").write_text("first\n")
    r = world.session("inbox")
    assert r.returncode == 0, r.stderr
    assert r.stdout.index("first") < r.stdout.index("second")
    assert (inbox / "read" / "a-200").exists()
    assert world.session("inbox").stdout.strip() == "no new agent reports"
    other = world.tmp / "elsewhere"
    other.mkdir()
    (other / "c-1").write_text("override\n")
    world.env["AGENT_SESSION_INBOX"] = str(other)
    assert "override" in world.session("inbox").stdout


def test_controller_passes_model_advisor_and_rules(world):
    world.config("controller-rules.md", "CONTROLLER-MARKER: no live writes.\n")
    r = world.session("controller")
    assert r.returncode == 0, r.stderr
    args = agent_args(world.rex_call("new"))
    assert args[args.index("--model") + 1] == "sonnet"
    assert json.loads(args[args.index("--settings") + 1]) == {"advisorModel": "fable"}
    prompt = args[-1]
    assert "CONTROLLER-MARKER: no live writes." in prompt
    assert "agent-session inbox --follow" in prompt
    assert "inbox --wait" not in prompt
    assert "bin/agent-session" not in prompt
    assert "trunk" in prompt
    assert world.rex_call("new")[1] == "proj-controller"


def test_controller_models_from_config_and_env(world):
    world.config("config", "CONTROLLER_MODEL=opus\nADVISOR_MODEL=sonnet\n")
    world.session("controller")
    args = agent_args(world.rex_call("new"))
    assert args[args.index("--model") + 1] == "opus"
    assert json.loads(args[args.index("--settings") + 1]) == {"advisorModel": "sonnet"}
    (world.tmp / "rex.log").unlink()
    world.env["AGENT_SESSION_CONTROLLER_MODEL"] = "haiku"
    world.env["AGENT_SESSION_ADVISOR_MODEL"] = "opus"
    world.session("controller")
    args = agent_args(world.rex_call("new"))
    assert args[args.index("--model") + 1] == "haiku"
    assert json.loads(args[args.index("--settings") + 1]) == {"advisorModel": "opus"}


def test_controller_practice_doc_defaults(world):
    world.session("controller")
    prompt = agent_args(world.rex_call("new"))[-1]
    assert str(BIN.parent / "agent_panel" / "assets" / "controller-practice.md") in prompt
    (world.tmp / "rex.log").unlink()
    local = world.repo / "ai-ops" / "local-config"
    local.mkdir(parents=True)
    (local / "agent-sessions.md").write_text("mine\n")
    world.session("controller")
    prompt = agent_args(world.rex_call("new"))[-1]
    assert "ai-ops/local-config/agent-sessions.md" in prompt


def split_call(world):
    return next((c for c in world.calls() if c[0] == "split"), None)


def flag(call, name):
    return call[call.index(name) + 1]


def test_new_opens_panel_beside_agent_pane_in_worktree(world):
    r = world.session("new", "alpha")
    assert r.returncode == 0, r.stderr
    c = split_call(world)
    assert c is not None
    wt = str(world.tmp / "proj-worktrees" / "alpha")
    assert flag(c, "-s") == "sess-1" and flag(c, "-b") == "agent-b"
    assert flag(c, "-c") == wt
    assert "--focus=false" in c and "--split=right" in c
    assert flag(c, "--ratio") == "35" and flag(c, "--label") == "Agents"
    assert agent_args(c) == ["agent-panel"]


def test_controller_opens_panel_in_main_checkout(world):
    r = world.session("controller")
    assert r.returncode == 0, r.stderr
    c = split_call(world)
    assert flag(c, "-c") == str(world.repo) and flag(c, "-b") == "agent-b"
    assert agent_args(c) == ["agent-panel"]


@pytest.mark.parametrize("cmd", [("new", "alpha"), ("controller",)])
def test_panel_off_by_config_or_env(world, cmd):
    world.config("config", "PANEL=0\n")
    assert world.session(*cmd).returncode == 0
    assert split_call(world) is None
    (world.tmp / "rex.log").unlink()
    (world.repo / ".agent-session" / "config").unlink()
    world.env["AGENT_SESSION_PANEL"] = "0"
    if cmd[0] == "new":
        git(world.repo, "worktree", "remove", "--force", str(world.tmp / "proj-worktrees" / "alpha"))
        git(world.repo, "branch", "-D", "agent/alpha")
    assert world.session(*cmd).returncode == 0
    assert split_call(world) is None


def test_env_panel_overrides_config(world):
    world.config("config", "PANEL=0\n")
    world.env["AGENT_SESSION_PANEL"] = "1"
    world.session("controller")
    assert split_call(world) is not None


def test_panel_config_value_must_be_0_or_1(world):
    world.config("config", "PANEL=yes\n")
    r = world.session("controller")
    assert r.returncode != 0 and "PANEL" in r.stderr


@pytest.mark.parametrize("cmd", [("new", "alpha"), ("controller",)])
def test_missing_agent_panel_skips_with_note(world, cmd):
    # PATH with only the fakes' dir plus system tools, no agent-panel
    fake = world.tmp / "fakebin"
    bare = world.tmp / "barebin"
    bare.mkdir()
    for n in ("rex", "claude"):
        (bare / n).symlink_to(fake / n)
    for n in ("git", "jq", "env", "bash", "dirname", "basename", "readlink", "awk", "sed", "cat",
              "mkdir", "cp", "head", "sort", "cut", "tail", "python3"):
        w = subprocess.run(["bash", "-c", f"command -v {n}"], capture_output=True, text=True, env=world.env).stdout.strip()
        if w:
            (bare / n).symlink_to(w)
    world.env["PATH"] = str(bare)
    r = world.session(*cmd)
    assert r.returncode == 0, r.stderr
    assert "agent-panel" in r.stderr
    assert split_call(world) is None


def test_failed_split_never_fails_the_command(world):
    fake = world.tmp / "fakebin"
    (fake / "rex").write_text((fake / "rex").read_text().replace(
        'elif a[:1] == ["split"]:', 'elif a[:1] == ["split"]:\n    sys.exit(1)\nelif False:'))
    r = world.session("new", "alpha")
    assert r.returncode == 0, r.stderr
    assert (world.tmp / "proj-worktrees" / "alpha").exists()
    assert "panel" in r.stderr


def sessions(*labels):
    return json.dumps({"sessions": [{"session_id": f"sid-{l}", "label": l} for l in labels]})


def test_panel_command_targets_controller_by_default(world):
    world.env["FAKE_SESSIONS"] = sessions("proj-controller", "proj-alpha")
    r = world.session("panel")
    assert r.returncode == 0, r.stderr
    c = split_call(world)
    assert flag(c, "-s") == "sid-proj-controller"
    assert flag(c, "-b") == "agentblock-sid-proj-controller"
    assert flag(c, "-c") == str(world.repo)
    assert agent_args(c) == ["agent-panel"]


def test_panel_command_targets_named_agent_worktree(world):
    world.env["FAKE_SESSIONS"] = sessions("proj-controller", "proj-alpha")
    (world.tmp / "proj-worktrees" / "alpha").mkdir(parents=True)
    r = world.session("panel", "alpha")
    assert r.returncode == 0, r.stderr
    c = split_call(world)
    assert flag(c, "-s") == "sid-proj-alpha" and flag(c, "-b") == "agentblock-sid-proj-alpha"
    assert flag(c, "-c") == str(world.tmp / "proj-worktrees" / "alpha")


def test_panel_command_ignores_panel_off_and_dies_when_not_open(world):
    world.env["AGENT_SESSION_PANEL"] = "0"
    r = world.session("panel")
    assert r.returncode != 0 and "proj-controller" in r.stderr
    assert split_call(world) is None
    world.env["FAKE_SESSIONS"] = sessions("proj-controller")
    assert world.session("panel").returncode == 0
    assert split_call(world) is not None


def test_usage_lists_panel(world, tmp_path):
    r = run([str(SESSION)], tmp_path, world.env)
    assert "agent-session panel" in r.stderr + r.stdout


def test_done_removes_merged_worktree_and_branch(world):
    world.session("new", "alpha")
    r = world.session("done", "alpha")
    assert r.returncode == 0, r.stderr
    assert not (world.tmp / "proj-worktrees" / "alpha").exists()
    assert "agent/alpha" not in git(world.repo, "branch", "--list")


def test_done_refuses_unmerged_commits(world):
    world.session("new", "alpha")
    wt = world.tmp / "proj-worktrees" / "alpha"
    (wt / "f.txt").write_text("x\n")
    git(wt, "add", "f.txt")
    git(wt, "commit", "-qm", "work")
    r = world.session("done", "alpha")
    assert r.returncode != 0
    assert "trunk" in r.stderr
    assert wt.exists()


def test_usage_runs_from_outside_a_repo(world, tmp_path):
    r = run([str(SESSION)], tmp_path, world.env)
    assert "agent-session new" in r.stderr + r.stdout


def hook(env, stdin, **extra):
    e = {k: v for k, v in env.items() if not k.startswith("AGENT_SESSION_")}
    e.update(extra)
    return run([str(HOOK)], None, e, input=stdin)


def test_hook_writes_report_only_when_both_vars_set(world, tmp_path):
    inbox = tmp_path / "hookbox"
    payload = json.dumps({"last_assistant_message": "all done"})
    assert hook(world.env, payload).returncode == 0
    assert hook(world.env, payload, AGENT_SESSION_NAME="a").returncode == 0
    assert hook(world.env, payload, AGENT_SESSION_INBOX=str(inbox)).returncode == 0
    assert not inbox.exists()
    r = hook(world.env, payload, AGENT_SESSION_NAME="a", AGENT_SESSION_INBOX=str(inbox))
    assert r.returncode == 0
    (report,) = list(inbox.iterdir())
    assert report.name.startswith("a-")
    text = report.read_text()
    assert "agent: a" in text and "all done" in text


def project_with_hook(root, settings=None, settings_file="settings.json"):
    """A project with its own executable bin/agent-stop-hook, a copy of the real one, optionally wired in
    .claude/<settings_file> with the given Stop command."""
    (root / "bin").mkdir(parents=True)
    own = root / "bin" / "agent-stop-hook"
    shutil.copy(HOOK, own)
    own.chmod(0o755)
    if settings is not None:
        (root / ".claude").mkdir()
        hooks = {"Stop": [{"hooks": [{"type": "command", "command": settings}]}]}
        (root / ".claude" / settings_file).write_text(json.dumps({"hooks": hooks}))
    return own


@pytest.mark.parametrize("settings_file", ["settings.json", "settings.local.json"])
def test_hook_defers_to_a_project_that_wires_its_own_copy(world, tmp_path, settings_file):
    """A project whose settings run its own bin/agent-stop-hook gets one report, not two."""
    inbox = tmp_path / "hookbox"
    proj = tmp_path / "proj-with-hook"
    own = project_with_hook(proj, '"$CLAUDE_PROJECT_DIR"/bin/agent-stop-hook', settings_file)
    payload = json.dumps({"last_assistant_message": "x"})
    vars = dict(AGENT_SESSION_NAME="a", AGENT_SESSION_INBOX=str(inbox), CLAUDE_PROJECT_DIR=str(proj))
    assert hook(world.env, payload, **vars).returncode == 0  # the user-level hook stands down
    assert not inbox.exists()
    e = {k: v for k, v in world.env.items() if not k.startswith("AGENT_SESSION_")} | vars
    assert run([str(own)], None, e, input=payload).returncode == 0  # the project's own copy reports
    assert len(list(inbox.iterdir())) == 1
    assert hook(world.env, payload, **(vars | dict(CLAUDE_PROJECT_DIR=str(tmp_path / "plain")))).returncode == 0
    assert len(list(inbox.iterdir())) == 2


@pytest.mark.parametrize("settings", [None, "command -v agent-stop-hook >/dev/null && agent-stop-hook || true"])
def test_hook_reports_from_a_worktree_with_an_unwired_copy(world, tmp_path, settings):
    """An agent-harbor worktree has its own bin/agent-stop-hook, but its settings don't run it (or run only
    the one on PATH), so the user-level hook is the only one reporting and must not stand down."""
    inbox = tmp_path / "hookbox"
    wt = tmp_path / "agent-harbor-worktrees" / "harbor-x"
    project_with_hook(wt, settings)
    payload = json.dumps({"last_assistant_message": "report"})
    r = hook(world.env, payload, AGENT_SESSION_NAME="harbor-x", AGENT_SESSION_INBOX=str(inbox), CLAUDE_PROJECT_DIR=str(wt))
    assert r.returncode == 0
    (report,) = list(inbox.iterdir())
    assert "agent: harbor-x" in report.read_text() and "report" in report.read_text()


USER_STOP = "command -v agent-stop-hook >/dev/null && agent-stop-hook || true"  # as the README wires it


def one_stop(world, tmp_path, proj, user_cmds=(USER_STOP,)):
    """One stop, as Claude runs it: every user-level Stop command, then every command in the project's
    .claude/settings{,.local}.json Stop hooks, from the project dir, with ~/.local/bin/agent-stop-hook a
    symlink to the real hook. Returns how many reports landed."""
    home = tmp_path / "home"
    local = home / ".local" / "bin"
    if not local.exists():
        local.mkdir(parents=True)
        (local / "agent-stop-hook").symlink_to(HOOK)
    inbox = tmp_path / "hookbox"
    shutil.rmtree(inbox, ignore_errors=True)
    env = {k: v for k, v in world.env.items() if not k.startswith("AGENT_SESSION_")}
    env.update(HOME=str(home), PATH=f"{local}:{env['PATH']}", CLAUDE_PROJECT_DIR=str(proj),
               AGENT_SESSION_NAME="a", AGENT_SESSION_INBOX=str(inbox))
    cmds = list(user_cmds)
    for f in ("settings.json", "settings.local.json"):
        if (proj / ".claude" / f).exists():
            data = json.loads((proj / ".claude" / f).read_text())
            cmds += [h["command"] for m in data.get("hooks", {}).get("Stop", []) for h in m["hooks"]]
    for cmd in cmds:
        assert run(["bash", "-c", cmd], proj, env, input=json.dumps({"last_assistant_message": "x"})).returncode == 0
    return len(list(inbox.iterdir())) if inbox.exists() else 0


def worktree(tmp_path, settings=None, settings_file="settings.json"):
    """A worktree-like project carrying its own copy of the hook, with optional .claude settings."""
    wt = tmp_path / "agent-harbor-worktrees" / "harbor-x"
    (wt / "bin").mkdir(parents=True)
    shutil.copy(HOOK, wt / "bin" / "agent-stop-hook")
    (wt / "bin" / "agent-stop-hook").chmod(0o755)
    if settings is not None:
        (wt / ".claude").mkdir()
        (wt / ".claude" / settings_file).write_text(json.dumps(settings))
    return wt


def stop_hooks(*cmds):
    return {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": c} for c in cmds]}]}}


@pytest.mark.parametrize("settings_file", ["settings.json", "settings.local.json"])
def test_one_report_when_the_project_wires_its_own_copy(world, tmp_path, settings_file):
    wt = worktree(tmp_path, stop_hooks('"$CLAUDE_PROJECT_DIR"/bin/agent-stop-hook'), settings_file)
    assert one_stop(world, tmp_path, wt) == 1
    assert one_stop(world, tmp_path, wt, user_cmds=()) == 1  # that one is the project's: the user copy stood down


@pytest.mark.parametrize("cmd", ["~/.local/bin/agent-stop-hook", '"$HOME/.local/bin/agent-stop-hook"'])
def test_one_report_when_the_project_wires_the_user_level_install(world, tmp_path, cmd):
    """X2: the project's hooks run ~/.local/bin/agent-stop-hook (no user-level wiring): that is not a copy."""
    assert one_stop(world, tmp_path, worktree(tmp_path, stop_hooks(cmd)), user_cmds=()) == 1


def test_one_report_when_the_project_wires_a_path_that_resolves_to_the_running_hook(world, tmp_path):
    """5a: the project's hooks run the installed hook by its absolute real path, from a worktree with a copy."""
    assert one_stop(world, tmp_path, worktree(tmp_path, stop_hooks(str(HOOK))), user_cmds=()) == 1


@pytest.mark.parametrize("settings", [
    {"permissions": {"allow": ["Bash(bin/agent-stop-hook:*)", "Bash(./bin/agent-stop-hook)"]}},  # X4
    {"env": {"STOP_HOOK": "$CLAUDE_PROJECT_DIR/bin/agent-stop-hook"}, "statusLine": {"command": "bin/agent-stop-hook"}},
])
def test_mentions_outside_hooks_never_count(world, tmp_path, settings):
    assert one_stop(world, tmp_path, worktree(tmp_path, settings)) == 1


# --- rexclaude ---------------------------------------------------------------------------

REXCLAUDE = BIN / "rexclaude"


def rexclaude(world, *args, cwd=None):
    return run([str(REXCLAUDE), *args], cwd or world.repo, world.env)


@pytest.fixture
def plain(world):
    d = world.tmp / "notrepo"
    d.mkdir()
    return d


def test_rexclaude_default_in_repo_runs_controller(world):
    r = rexclaude(world)
    assert r.returncode == 0, r.stderr
    new = world.rex_call("new")
    assert new[1] == "proj-controller"
    args = agent_args(new)
    assert args[args.index("--model") + 1] == "sonnet"
    assert json.loads(args[args.index("--settings") + 1]) == {"advisorModel": "fable"}
    assert split_call(world) is not None


def test_rexclaude_extra_prompt_is_appended_to_controller_prompt(world):
    assert rexclaude(world, "focus", "on", "billing").returncode == 0
    prompt = agent_args(world.rex_call("new"))[-1]
    assert "agent-session inbox --follow" in prompt
    assert "inbox --wait" not in prompt
    assert prompt.rstrip().endswith("focus on billing")
    assert prompt.index("focus on billing") > prompt.index("Call the advisor")


def test_rexclaude_solo_creates_labeled_session_with_panel(world):
    world.env["CLAUDE_CONFIG_DIR"] = "/cfg/acct"
    r = rexclaude(world, "--solo", "fix", "the", "bug")
    assert r.returncode == 0, r.stderr
    new = world.rex_call("new")
    assert new[1] == "proj-solo" and flag(new, "-c") == str(world.repo)
    assert flag(new, "--window") == "Agent"
    args = agent_args(new)
    assert args[:2] == ["env", "CLAUDE_CONFIG_DIR=/cfg/acct"]
    assert args[args.index("--model") + 1] == "sonnet"
    assert json.loads(args[args.index("--settings") + 1]) == {"advisorModel": "fable"}
    assert args[-1] == "fix the bug"
    c = split_call(world)
    assert flag(c, "-b") == "agent-b" and flag(c, "-c") == str(world.repo)
    assert agent_args(c) == ["agent-panel"]


def test_rexclaude_solo_without_prompt_passes_none(world):
    assert rexclaude(world, "--solo").returncode == 0
    assert agent_args(world.rex_call("new"))[-1].startswith("{")


def test_rexclaude_solo_honors_model_env(world):
    world.env["AGENT_SESSION_CONTROLLER_MODEL"] = "opus"
    world.env["AGENT_SESSION_ADVISOR_MODEL"] = "claude-fable-5"
    assert rexclaude(world, "--solo").returncode == 0
    args = agent_args(world.rex_call("new"))
    assert args[args.index("--model") + 1] == "opus"
    assert json.loads(args[args.index("--settings") + 1]) == {"advisorModel": "claude-fable-5"}


def test_rexclaude_outside_repo_falls_back_to_solo_with_note(world, plain):
    r = rexclaude(world, "hello", cwd=plain)
    assert r.returncode == 0, r.stderr
    assert "not in a git repo" in r.stderr
    new = world.rex_call("new")
    assert new[1] == "notrepo-solo" and agent_args(new)[-1] == "hello"


def test_rexclaude_panel_off_by_env(world):
    world.env["AGENT_SESSION_PANEL"] = "0"
    assert rexclaude(world, "--solo").returncode == 0
    assert split_call(world) is None


def test_rexclaude_missing_agent_panel_never_fails(world):
    fake = world.tmp / "fakebin"
    bare = world.tmp / "barebin"
    bare.mkdir()
    for tool in ("rex", "claude"):
        (bare / tool).symlink_to(fake / tool)
    for tool in ("bash", "env", "jq", "git", "basename", "dirname", "readlink", "head", "sed", "cat", "python3"):
        (bare / tool).symlink_to(shutil.which(tool))
    world.env["PATH"] = str(bare)
    r = rexclaude(world, "--solo")
    assert r.returncode == 0, r.stderr
    assert "agent-panel not on PATH" in r.stderr and split_call(world) is None


def test_rexclaude_open_solo_session_is_switched_to_not_duplicated(world):
    world.env["FAKE_SESSIONS"] = sessions("proj-solo")
    r = rexclaude(world, "--solo", "ignored")
    assert r.returncode == 0, r.stderr
    assert "switched" in r.stdout
    assert not [c for c in world.calls() if c[0] == "new"]


@pytest.mark.parametrize("var", ["AGENT_SESSION_CONTROLLER_MODEL", "AGENT_SESSION_ADVISOR_MODEL"])
@pytest.mark.parametrize("args", [("--solo",), ()])
def test_rexclaude_bad_model_env_refused(world, var, args):
    world.env[var] = 'x","y'
    r = rexclaude(world, *args)
    assert r.returncode != 0 and var in r.stderr
    assert not [c for c in world.calls() if c[0] == "new"]


def test_rexclaude_help(world):
    r = rexclaude(world, "--help", cwd=world.tmp)
    assert r.returncode == 0 and "--solo" in r.stdout and "rexclaude" in r.stdout


def test_rexclaude_works_through_a_symlink(world):
    link = world.tmp / "linkbin" / "rexclaude"
    link.parent.mkdir()
    link.symlink_to(REXCLAUDE)
    r = run([str(link), "--solo"], world.repo, world.env)
    assert r.returncode == 0, r.stderr


# --- rexclaude: opt-in to the repo's own bin/agent-session ----------------------------------

def project_script(world, executable=True):
    d = world.repo / "bin"
    d.mkdir(exist_ok=True)
    out = world.tmp / "project-argv.json"
    script = d / "agent-session"
    script.write_text(f"#!/usr/bin/env python3\nimport json, sys\nopen({str(out)!r}, 'w').write(json.dumps(sys.argv[1:]))\n")
    script.chmod(0o755 if executable else 0o644)
    return out


def test_rexclaude_opted_in_repo_uses_project_script(world):
    out = project_script(world)
    git(world.repo, "config", "--local", "agent-session.useProjectScript", "true")
    r = rexclaude(world, "focus", "on", "billing")
    assert r.returncode == 0, r.stderr
    assert "rexclaude: using this repo's bin/agent-session" in r.stdout + r.stderr
    assert json.loads(out.read_text()) == ["controller", "focus", "on", "billing"]
    assert not world.calls()  # the shared script did not run


def test_rexclaude_repo_script_ignored_without_opt_in(world):
    out = project_script(world)
    assert rexclaude(world).returncode == 0
    assert not out.exists()
    assert world.rex_call("new")[1] == "proj-controller"


def test_rexclaude_opt_in_value_must_be_true(world):
    out = project_script(world)
    git(world.repo, "config", "--local", "agent-session.useProjectScript", "yes")
    assert rexclaude(world).returncode == 0
    assert not out.exists()


def test_rexclaude_opted_in_without_executable_script_errors(world):
    git(world.repo, "config", "--local", "agent-session.useProjectScript", "true")
    r = rexclaude(world)
    assert r.returncode != 0
    assert "bin/agent-session" in r.stderr and "executable" in r.stderr
    assert not world.calls()
    project_script(world, executable=False)
    assert rexclaude(world).returncode != 0


def test_rexclaude_solo_ignores_opt_in(world):
    out = project_script(world)
    git(world.repo, "config", "--local", "agent-session.useProjectScript", "true")
    assert rexclaude(world, "--solo").returncode == 0
    assert not out.exists() and world.rex_call("new")[1] == "proj-solo"


# --- inbox --follow -------------------------------------------------------------------------

import queue
import signal
import threading
import time


class Follower:
    """`agent-session inbox --follow` running in the background, its stdout read line by line."""

    def __init__(self, world, *extra):
        self.proc = subprocess.Popen(
            [str(SESSION), "inbox", "--follow", "--interval", "0.2", *extra],
            cwd=world.repo, env=world.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        self.lines = queue.Queue()
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self):
        for line in self.proc.stdout:
            self.lines.put(line)

    def read(self, n, timeout=5):
        out = []
        for _ in range(n):
            out.append(self.lines.get(timeout=timeout))
        return "".join(out)

    def quiet(self, seconds=0.6):
        time.sleep(seconds)
        return self.lines.empty()

    @staticmethod
    def eventually(check, timeout=5):
        end = time.monotonic() + timeout
        while not check():
            assert time.monotonic() < end, "timed out"
            time.sleep(0.05)
        return True

    def stop(self, sig=signal.SIGTERM):
        if self.proc.poll() is None:
            self.proc.send_signal(sig)
        return self.proc.wait(timeout=5)


@pytest.fixture
def follow(world):
    inbox = world.tmp / "box"
    inbox.mkdir()
    world.env["AGENT_SESSION_INBOX"] = str(inbox)
    started = []

    def start(*extra):
        f = Follower(world, *extra)
        started.append(f)
        return f

    yield inbox, start
    for f in started:
        if f.proc.poll() is None:
            f.proc.kill()
            f.proc.wait()


def test_follow_prints_report_that_arrives_later_and_archives_it(follow):
    inbox, start = follow
    f = start()
    assert f.quiet()  # nothing yet, and no "no new agent reports" line
    (inbox / "alpha-1700000000").write_text("alpha stopped\n")
    assert f.read(3) == "== alpha-1700000000\nalpha stopped\n\n"
    assert f.eventually((inbox / "read" / "alpha-1700000000").exists)
    assert not (inbox / "alpha-1700000000").exists()
    assert f.quiet()
    assert f.proc.poll() is None  # still following
    assert f.stop() == 0


def drop(inbox, name, text):
    """Write a report the way agent-stop-hook does: a dotted temp file, then a rename."""
    tmp = inbox / f".{name}.tmp"
    tmp.write_text(text)
    tmp.rename(inbox / name)


def test_follow_prints_two_reports_in_one_interval_oldest_first_once(follow):
    inbox, start = follow
    inbox.rmdir()
    f = start("--interval", "1")
    time.sleep(0.3)
    # Both reports appear in one rename of the whole folder, so no listing can see just one.
    staging = inbox.with_name("staging")
    staging.mkdir()
    drop(staging, "b-200", "second\n")
    drop(staging, "a-100", "first\n")
    staging.rename(inbox)
    assert f.read(6) == "== a-100\nfirst\n\n== b-200\nsecond\n\n"
    assert f.quiet(1.5)
    assert sorted(p.name for p in (inbox / "read").iterdir()) == ["a-100", "b-200"]
    f.stop()


def test_follow_survives_a_competing_plain_inbox_and_each_report_prints_once(follow, world):
    inbox, start = follow
    f = start("--interval", "0.02")
    names = [f"r{i:02d}-{1000 + i}" for i in range(40)]
    plain = []
    for i, name in enumerate(names):
        drop(inbox, name, f"body {name}\n")
        if i % 2:
            plain.append(world.session("inbox").stdout)
        time.sleep(0.01)
    time.sleep(0.5)
    assert f.proc.poll() is None, f.proc.stderr.read()
    printed = []
    while not f.lines.empty():
        printed.append(f.lines.get())
    out = "".join(printed) + "".join(plain)
    for name in names:
        assert out.count(f"== {name}\n") == 1, name
        assert out.count(f"body {name}\n") == 1, name
    assert sorted(p.name for p in (inbox / "read").iterdir()) == sorted(names)
    assert f.stop() == 0


def test_follow_skips_an_unreadable_report_and_keeps_going(follow):
    inbox, start = follow
    drop(inbox, "bad-100", "secret\n")
    (inbox / "bad-100").chmod(0)
    f = start("--interval", "0.1")
    assert f.quiet(0.8)
    assert f.proc.poll() is None
    drop(inbox, "good-200", "fine\n")
    assert f.read(3) == "== good-200\nfine\n\n"
    assert (inbox / "bad-100").exists()  # left for a human, not archived unprinted
    assert f.stop() == 0
    err = f.proc.stderr.read()
    assert err.count("bad-100") == 1, err  # warned once, not every interval
    (inbox / "bad-100").chmod(0o644)


def test_archiving_never_overwrites_an_earlier_report_of_the_same_name(world):
    inbox = world.tmp / "box"
    (inbox / "read").mkdir(parents=True)
    world.env["AGENT_SESSION_INBOX"] = str(inbox)
    (inbox / "read" / "a-100").write_text("earlier\n")
    (inbox / "read" / "a-100.1").write_text("earlier too\n")
    (inbox / "a-100").write_text("later\n")
    r = world.session("inbox")
    assert (r.returncode, r.stdout) == (0, "== a-100\nlater\n\n")
    assert (inbox / "read" / "a-100").read_text() == "earlier\n"
    assert (inbox / "read" / "a-100.1").read_text() == "earlier too\n"
    assert (inbox / "read" / "a-100.2").read_text() == "later\n"


def test_follow_prints_reports_already_waiting(follow):
    inbox, start = follow
    (inbox / "a-100").write_text("waiting\n")
    f = start()
    assert f.read(3) == "== a-100\nwaiting\n\n"
    f.stop()


def test_follow_waits_for_an_inbox_that_does_not_exist_yet(follow):
    inbox, start = follow
    inbox.rmdir()  # the controller starts the watcher before any agent has stopped
    f = start()
    assert f.quiet()
    assert f.proc.poll() is None
    inbox.mkdir()
    (inbox / "alpha-100").write_text("first stop\n")
    assert f.read(3) == "== alpha-100\nfirst stop\n\n"
    assert f.eventually((inbox / "read" / "alpha-100").exists)
    assert f.stop() == 0


def test_follow_ignores_dotfile_temp_until_renamed(follow):
    inbox, start = follow
    f = start()
    tmp = inbox / ".alpha-300.tmp"
    tmp.write_text("whole report\n")
    assert f.quiet()
    assert tmp.exists()
    tmp.rename(inbox / "alpha-300")
    assert f.read(3) == "== alpha-300\nwhole report\n\n"
    assert f.quiet()
    f.stop()


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGINT])
def test_follow_exits_promptly_on_signal(follow, sig):
    inbox, start = follow
    f = start("--interval", "30")
    time.sleep(0.5)
    t0 = time.monotonic()
    assert f.stop(sig) == 0
    assert time.monotonic() - t0 < 3
    assert f.proc.stderr.read() == ""


def test_follow_and_wait_are_mutually_exclusive(world):
    for args in (("--follow", "--wait"), ("--wait", "--follow")):
        r = world.session("inbox", *args)
        assert r.returncode != 0
        assert "--follow and --wait" in r.stderr
        assert r.stdout == ""


@pytest.mark.parametrize("bad", ["0", "abc", "-1", ""])
def test_follow_rejects_bad_interval(world, bad):
    r = world.session("inbox", "--follow", "--interval", bad)
    assert r.returncode != 0
    assert "--interval" in r.stderr


def test_timeout_does_not_go_with_follow(world):
    r = world.session("inbox", "--follow", "--timeout", "5")
    assert r.returncode != 0
    assert "--timeout" in r.stderr


def test_interval_needs_follow(world):
    r = world.session("inbox", "--interval", "2")
    assert r.returncode != 0
    assert "--interval" in r.stderr


def test_plain_inbox_and_wait_output_unchanged(world):
    inbox = world.tmp / "box"
    inbox.mkdir()
    world.env["AGENT_SESSION_INBOX"] = str(inbox)
    (inbox / "b-200").write_text("second\n")
    (inbox / "a-100").write_text("first\n")
    (inbox / ".c-50.tmp").write_text("partial\n")
    r = world.session("inbox")
    assert (r.returncode, r.stdout, r.stderr) == (0, "== a-100\nfirst\n\n== b-200\nsecond\n\n", "")
    assert (inbox / ".c-50.tmp").exists()
    r = world.session("inbox")
    assert (r.returncode, r.stdout) == (0, "no new agent reports\n")
    (inbox / "d-300").write_text("third\n")
    r = world.session("inbox", "--wait", "--timeout", "5")
    assert (r.returncode, r.stdout, r.stderr) == (0, "== d-300\nthird\n\n", "")
    r = world.session("inbox", "--wait", "--timeout", "0")
    assert (r.returncode, r.stdout) == (2, "")
    assert r.stderr == "agent-session: no agent reports after 0s\n"


def unreadable(inbox, name):
    drop(inbox, name, "secret\n")
    (inbox / name).chmod(0)


@pytest.fixture
def box(world):
    inbox = world.tmp / "box"
    inbox.mkdir()
    world.env["AGENT_SESSION_INBOX"] = str(inbox)
    yield inbox
    for p in inbox.iterdir():
        p.chmod(0o755 if p.is_dir() else 0o644)


def test_wait_keeps_waiting_past_an_unreadable_report(world, box):
    unreadable(box, "bad-100")
    t0 = time.monotonic()
    r = world.session("inbox", "--wait", "--timeout", "3")
    assert time.monotonic() - t0 >= 2.5
    assert (r.returncode, r.stdout) == (2, "")
    assert r.stderr.count("bad-100") == 1, r.stderr  # warned once, not every pass
    assert r.stderr.endswith("agent-session: no agent reports after 3s\n")


def test_wait_prints_a_report_that_arrives_after_an_unreadable_one(world, box):
    unreadable(box, "bad-100")
    p = subprocess.Popen([str(SESSION), "inbox", "--wait", "--timeout", "20"], cwd=world.repo,
                         env=world.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    time.sleep(1)
    assert p.poll() is None
    drop(box, "good-200", "fine\n")
    out, _ = p.communicate(timeout=10)
    assert (p.returncode, out) == (0, "== good-200\nfine\n\n")


def test_plain_inbox_says_no_reports_when_it_could_print_none(world, box):
    unreadable(box, "bad-100")
    r = world.session("inbox")
    assert (r.returncode, r.stdout) == (0, "no new agent reports\n")
    assert "bad-100" in r.stderr


def test_plain_inbox_says_no_reports_when_another_reader_claimed_them(world, box):
    # A report listed but gone before the move: simulate the follower winning the race with a
    # fake mv that archives the file itself and then fails, as a losing mv would.
    drop(box, "a-100", "first\n")
    fake = world.tmp / "racebin"
    fake.mkdir()
    mv = fake / "mv"
    mv.write_text('#!/bin/sh\nmkdir -p "$(dirname "$2")"\n/bin/mv "$1" "$2"\nexit 1\n')
    mv.chmod(0o755)
    world.env["PATH"] = f"{fake}:{world.env['PATH']}"
    r = world.session("inbox")
    assert (r.returncode, r.stdout) == (0, "no new agent reports\n")


def test_closed_output_leaves_reports_unread(world, box):
    drop(box, "a-100", "first\n")
    drop(box, "b-200", "second\n")
    rd, wr = os.pipe()
    os.close(rd)  # the reader is gone before anything is written
    try:
        p = subprocess.run([str(SESSION), "inbox"], cwd=world.repo, env=world.env, stdout=wr,
                           stderr=subprocess.PIPE, text=True, timeout=10)
    finally:
        os.close(wr)
    assert p.returncode == 1
    assert "agent-session: output closed; left a-100 in the inbox\n" in p.stderr
    assert sorted(x.name for x in box.iterdir() if x.name != "read") == ["a-100", "b-200"]
    assert not (box / "read").exists() or not list((box / "read").iterdir())


def test_follow_whose_reader_exits_leaves_the_report_unread(world, box):
    rd, wr = os.pipe()
    p = subprocess.Popen([str(SESSION), "inbox", "--follow", "--interval", "0.1"], cwd=world.repo,
                         env=world.env, stdout=wr, stderr=subprocess.PIPE, text=True)
    os.close(wr)
    time.sleep(0.4)
    os.close(rd)
    drop(box, "a-100", "first\n")
    assert p.wait(timeout=5) == 1
    assert "agent-session: output closed; left a-100 in the inbox\n" in p.stderr.read()
    assert (box / "a-100").read_text() == "first\n"
    assert not list((box / "read").iterdir()) if (box / "read").exists() else True


def test_peek_prints_unread_reports_and_leaves_them(world, box):
    (box / "b-200").write_text("second\n")
    (box / "a-100").write_text("first\n")
    for _ in range(2):
        r = world.session("inbox", "--peek")
        assert (r.returncode, r.stdout, r.stderr) == (0, "== a-100\nfirst\n\n== b-200\nsecond\n\n", "")
    assert sorted(p.name for p in box.iterdir()) == ["a-100", "b-200"]
    assert "first" in world.session("inbox").stdout
    r = world.session("inbox", "--peek")
    assert (r.returncode, r.stdout) == (0, "no new agent reports\n")


def test_count_prints_the_number_of_unread_reports(world, box):
    assert world.session("inbox", "--count").stdout == "0\n"
    (box / "a-100").write_text("first\n")
    (box / "b-200").write_text("second\n")
    (box / ".c-300.tmp").write_text("partial\n")
    r = world.session("inbox", "--count")
    assert (r.returncode, r.stdout, r.stderr) == (0, "2\n", "")
    assert (box / "a-100").exists() and (box / "b-200").exists()


def test_count_works_before_the_inbox_exists(world):
    world.env["AGENT_SESSION_INBOX"] = str(world.tmp / "nowhere")
    assert world.session("inbox", "--count").stdout == "0\n"
    assert not (world.tmp / "nowhere").exists()


@pytest.mark.parametrize("other", [["--wait"], ["--follow"], ["--count"], ["--timeout", "5"], ["--interval", "1"]])
def test_peek_and_count_stand_alone(world, other):
    for flag_ in ("--peek", "--count"):
        if other == [flag_]:
            continue
        r = world.session("inbox", flag_, *other)
        assert r.returncode != 0, (flag_, other)
        assert flag_ in r.stderr


def transcript(path, *entries):
    path.write_text("".join(json.dumps(e) + "\n" for e in entries))
    return str(path)


def said(text):
    return {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}


def test_hook_skips_a_report_with_no_message(world, tmp_path):
    inbox = tmp_path / "hookbox"
    for payload in ({}, {"last_assistant_message": ""}, {"last_assistant_message": "  \n"}):
        r = hook(world.env, json.dumps(payload), AGENT_SESSION_NAME="a", AGENT_SESSION_INBOX=str(inbox))
        assert r.returncode == 0
    assert not inbox.exists() or not list(inbox.iterdir())


def test_hook_falls_back_to_the_transcripts_last_text(world, tmp_path):
    inbox = tmp_path / "hookbox"
    tool_use = {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {}}]}}
    t = transcript(tmp_path / "t.jsonl", said("early words"), {"type": "user", "message": {"content": "go"}},
                   said("Report: tests green, branch ready."), tool_use)
    r = hook(world.env, json.dumps({"transcript_path": t}), AGENT_SESSION_NAME="a", AGENT_SESSION_INBOX=str(inbox))
    assert r.returncode == 0
    (report,) = list(inbox.iterdir())
    text = report.read_text()
    assert "Report: tests green, branch ready." in text and "early words" not in text


def test_hook_skips_when_the_transcript_has_no_text_either(world, tmp_path):
    inbox = tmp_path / "hookbox"
    for t in (transcript(tmp_path / "t.jsonl", {"type": "user", "message": {"content": "go"}}),
              str(tmp_path / "missing.jsonl")):
        hook(world.env, json.dumps({"transcript_path": t}), AGENT_SESSION_NAME="a", AGENT_SESSION_INBOX=str(inbox))
    assert not inbox.exists() or not list(inbox.iterdir())


def controller_id_file(world):
    return world.state / "agent-session" / "proj" / "controller-rex-id"


def test_controller_records_its_rex_session_id(world):
    assert world.session("controller").returncode == 0
    assert controller_id_file(world).read_text().strip() == "sess-1"


def test_a_renamed_controller_is_found_by_its_recorded_id(world):
    world.session("controller")
    world.env["FAKE_SESSIONS"] = json.dumps({"sessions": [{"session_id": "sess-1", "label": "something-else"}]})
    r = world.session("panel")
    assert r.returncode == 0, r.stderr
    assert flag(split_call(world), "-s") == "sess-1"
    before = len([c for c in world.calls() if c[0] == "new"])
    r = world.session("controller")
    assert r.returncode == 0 and "already open" in r.stdout
    assert len([c for c in world.calls() if c[0] == "new"]) == before


def test_a_stale_recorded_id_falls_back_to_the_label(world):
    controller_id_file(world).parent.mkdir(parents=True)
    controller_id_file(world).write_text("gone\n")
    world.env["FAKE_SESSIONS"] = sessions("proj-controller")
    r = world.session("panel")
    assert r.returncode == 0, r.stderr
    assert flag(split_call(world), "-s") == "sid-proj-controller"


def test_controller_is_told_to_watch_the_inbox_with_monitor(world):
    world.session("controller")
    prompt = agent_args(world.rex_call("new"))[-1]
    assert "Monitor" in prompt and "agent-session inbox --follow" in prompt
    assert "--peek" in prompt
