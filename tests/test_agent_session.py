"""Run the real bin/agent-session and bin/agent-stop-hook against a temp git repo.

`rex` and `claude` are fakes first on PATH: the fake rex appends each call's argv as one JSON
line to rex.log and prints canned JSON, so tests read back exactly what the script asked for.
"""
import json
import os
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
    assert "agent-session inbox --wait" in prompt
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
    assert str(BIN.parent / "docs" / "controller-practice.md") in prompt
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


def test_hook_defers_to_a_project_hook(world, tmp_path):
    """A project that wires its own bin/agent-stop-hook gets one report, not two."""
    inbox = tmp_path / "hookbox"
    proj = tmp_path / "proj-with-hook"
    (proj / "bin").mkdir(parents=True)
    own = proj / "bin" / "agent-stop-hook"
    own.write_text("#!/usr/bin/env bash\nexit 0\n")
    own.chmod(0o755)
    payload = json.dumps({"last_assistant_message": "x"})
    vars = dict(AGENT_SESSION_NAME="a", AGENT_SESSION_INBOX=str(inbox))
    assert hook(world.env, payload, CLAUDE_PROJECT_DIR=str(proj), **vars).returncode == 0
    assert not inbox.exists()
    assert hook(world.env, payload, CLAUDE_PROJECT_DIR=str(tmp_path / "plain"), **vars).returncode == 0
    assert len(list(inbox.iterdir())) == 1
