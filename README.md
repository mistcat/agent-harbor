# agent-harbor

Tooling for watching and running Claude Code agents in [Rex](https://www.superlogical.com/rex/docs/installation)
panes. Rex is a terminal app by [Superlogical](https://www.superlogical.com/), currently in public testing
([announcement](https://www.superlogical.com/updates/public-testing-beginning)).

## Requirements

Developed and tested on macOS. I haven't tested other platforms.

- [Rex](https://www.superlogical.com/rex/docs/installation), a terminal app by
  [Superlogical](https://www.superlogical.com/) currently in public testing
  ([announcement](https://www.superlogical.com/updates/public-testing-beginning)). Install it first and make sure the
  `rex` command is on your PATH: `agent-panel` and `agent-session` open and control Rex panes through it.
- Claude Code (`claude` on PATH).
- Python 3.11+, `git` and `jq`.
- [uv](https://docs.astral.sh/uv/), for the `uv tool install` path below.
- Optional: `afplay` (built into macOS) plays the cannon sound; where it is missing the sound is silently skipped.
  `direnv` is optional too.

- **`agent-panel`**: a live, read-only view of a Claude session's agents (below).
- **`agent-session`**: run parallel agents, one git worktree and Rex session each, coordinated by a controller
  session (below).
- **`rexclaude`**: start Claude in a Rex session with the panel beside it: the controller in a git repo, or a
  plain working session (below).

## rexclaude

```bash
rexclaude [prompt...]         # in a git repo: open (or switch to) the agent-session controller
rexclaude --solo [prompt...]  # a normal session "<dir>-solo" in the current directory
```

Both run Claude on `AGENT_SESSION_CONTROLLER_MODEL` (default sonnet) with the advisor on
`AGENT_SESSION_ADVISOR_MODEL` (default fable), under the same `CLAUDE_CONFIG_DIR`, and open `agent-panel` beside
it (`AGENT_SESSION_PANEL=0` skips that). In controller mode the prompt words are appended to the controller's
prompt. Outside a git repo the default is `--solo`, with a note. A solo session that is already open is switched
to instead of duplicated.

**Using a repo's own `agent-session`.** If a repo ships its own `bin/agent-session` (say, one that also sets up a
database per agent), opt that repo in once, in your own checkout:

```bash
git config agent-session.useProjectScript true   # writes to the repo's local .git/config
```

From then on, plain `rexclaude [prompt...]` in that repo prints `rexclaude: using this repo's bin/agent-session`
and runs `<repo>/bin/agent-session controller [prompt...]` instead of the shared script (it errors if that file
isn't an executable regular file). `--solo` is unaffected. The opt-in is read only from local git config on
purpose: `.git/config` is never part of a clone, so a repo you clone can't opt itself in and get its script
run when you type `rexclaude`.

## agent-panel

A live, read-only terminal panel for a Rex pane. It follows a Claude Code session and shows its agents twice:

- **Top, the tree:** one row per agent, nested by parent, with model, effort, token burn and status.
- **Bottom, the harbor:** the same agents as boats on the water. Running boats sail with a wake, finished ones anchor and snooze, children sail behind their parent as a flotilla. An advisor call makes the main ship fire a cannon, with a sound.
- **The captain:** a small pirate in a white tricorn with a yellow skull stands on the main ship's deck, at any size of boat. Arms down while idle (with `zzz` when the whole flotilla is anchored), an arm raised while any subagent runs, and a "Fire!" call-out during the cannon flash. Subagent boats have no captain. It is dropped, not clipped, when it doesn't fit; `--no-captain` turns it off.

## Read-only promise

agent-panel only reads transcript files under the Claude config dir. It never writes there, installs hooks, edits settings, sends input to a session or touches the network. The one side effect besides drawing is playing the bundled cannon WAV with `afplay` (turn it off with `--no-sound`).

## Install

**To use it:**

```bash
uv tool install git+https://github.com/mistcat/agent-harbor
uv tool upgrade agent-harbor   # later, to update
```

This puts `agent-panel`, `agent-session`, `rexclaude` and `agent-stop-hook` on your PATH (via uv's tool bin
directory; `uv tool update-shell` adds it to your PATH if needed). `agent-session-lib.sh`, the helper the scripts
source, is linked there too; ignore it.

**To hack on it:**

```bash
git clone https://github.com/mistcat/agent-harbor && cd agent-harbor
./install.sh   # makes .venv, installs editable, links the four commands into ~/.local/bin
```

Edits to the clone take effect immediately. Dependencies: textual, rich (pytest for tests).

## Launch beside a Claude session

```bash
rex split -s "$REX_SESSION" -b "$REX_BLOCK" --split=right --ratio 35 --label Agents --focus=false -- agent-panel
```

Run it from the project directory you are working in, or pass `--cwd`.

Rex split panes do not inherit `CLAUDE_CONFIG_DIR`. When it is unset, agent-panel looks in `~/.claude` and every `~/.claude-*` folder and follows the one whose copy of the project has the most recently written transcript. Pin one with `--config-dir PATH`; an explicit `--config-dir` beats the environment variable, which beats the search.

## Options

| Flag | Meaning |
| --- | --- |
| `--cwd PATH` | project directory to follow (default: current directory) |
| `--session ID` | pin one session instead of following the newest |
| `--config-dir PATH` | Claude config dir to read |
| `--no-sound` | no cannon boom |
| `--no-captain` | no pirate captain on the main ship |

Without `--session` it follows the newest session in the project and only switches away from one that has been quiet for 60 seconds. A pinned session never switches.

## Reading the display

Works at 50 columns. When space runs out the label is cut first (`…`), then the effort, then the burn bar; model and burn always stay. The harbor hides when it would get fewer than 8 rows. More agents than fit show as `+N more`.

Model colors: **opus** purple, **sonnet** orange, **haiku** blue, everything else (fable, unknown) green. Yellow is reserved for the captain's skull. The main ship's sail carries a white Jolly Roger (crossed bones, plus a skull on the bigger sails).

Boat size follows token burn (input + cache creation + output, counted once per message):

| Burn | Boat |
| --- | --- |
| under 50k | rowboat |
| 50k to 300k | sloop |
| 300k and up | galleon |

Row marks: `✓` done, a spinner for running, `·` idle. A `?` after a label means the subagent could not be matched to a parent call and is shown under main.

## Tests

```bash
.venv/bin/pytest -q
```

Fixtures are synthetic; no real transcript content is committed. The cannon WAV is generated by `scripts/make_cannon.py`.

## agent-session

Run parallel Claude agents on one repo from any git repo. Each agent gets its own worktree
(`../<repo>-worktrees/<name>`, branch `agent/<name>` off origin's default branch) and Rex session; a
controller session coordinates them.

```bash
agent-session new <name> [--branch B] [--prompt TEXT | --prompt-file FILE]
agent-session done <name> [--force]
agent-session ls
agent-session peek <name> [lines]
agent-session inbox [--wait] [--timeout SECONDS]
agent-session controller
agent-session panel [name]
```

`new` and `controller` also open `agent-panel` in a split beside the Agent tab's Claude, following that
checkout. Turn it off with `AGENT_SESSION_PANEL=0` or `PANEL=0` in `.agent-session/config`; if `agent-panel`
isn't on PATH it is skipped with a note, and a panel problem never fails the command. `agent-session panel`
opens one by hand beside the controller, or beside agent session `<name>`.

Agents report back through a Claude Code Stop hook. `agent-stop-hook` does nothing unless `agent-session`
started the Claude, so wire it once in your user-level Claude settings:

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "command -v agent-stop-hook >/dev/null && agent-stop-hook || true",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

Reports land in `${XDG_STATE_HOME:-~/.local/state}/agent-session/<prefix>/inbox` (override with
`AGENT_SESSION_INBOX`); `agent-session inbox` prints and archives them.

The controller runs on Sonnet with a Fable advisor. Override with `AGENT_SESSION_CONTROLLER_MODEL` and
`AGENT_SESSION_ADVISOR_MODEL`, or set `CONTROLLER_MODEL` / `ADVISOR_MODEL` in the project config. Its standing
practice is [agent_panel/assets/controller-practice.md](agent_panel/assets/controller-practice.md).

### Per-project config

Everything is optional, in `<repo root>/.agent-session/`:

| File | Purpose |
| --- | --- |
| `config` | Plain `KEY=value` lines (never executed; unknown keys warn). `PREFIX` (default `<repo dir>-`; lowercase letters, digits, dashes), `COPY_FILES` (space-separated git-ignored files copied into each new worktree, default `.env`; relative paths, no `..`), `PRACTICE_DOC` (default `ai-ops/local-config/agent-sessions.md` if present, else the shipped doc), `CONTROLLER_MODEL`, `ADVISOR_MODEL`, `PANEL` (`0` or `1`, default `1`: open the panel) |
| `agent-rules.md` | Bullets inserted into every agent's preamble (live-write rules, the project's test commands) |
| `controller-rules.md` | Text added to the controller's prompt |

`examples/crm/.agent-session/` is a worked example. The base branch is detected from `origin/HEAD`, falling back
to `master`.

## License

MIT. See `LICENSE`.
