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
- Optional: `afplay` (built into macOS) plays the cannon and attention sounds, and `say` speaks the attention call with `--attention-sound say`; where either is missing that sound is silently skipped.
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

A live, read-only terminal panel for a Rex pane. It follows a Claude Code session and shows its agents twice. Beside
an `agent-session` controller it shows the whole fleet: every other worktree's session sails in the same harbor as a
ship of its own, with its own flotilla.

- **Top, the tree:** one row per agent, nested by parent, with model, effort, token burn and status.
- **Bottom, the harbor:** the same agents as boats on the water. Running boats sail with a wake, idle ships anchor and snooze, finished subagents moor at a pier, and children sail behind their parent as a flotilla. An advisor call makes the main ship fire a cannon, with a sound.
- **The captain:** a small pirate in a white tricorn with a yellow skull stands on the main ship's deck, at any size of boat. Arms down while idle (with `zzz` when the whole flotilla is anchored), an arm raised while any subagent runs, and a "Fire!" call-out during the cannon flash. Subagent boats have no captain. It is dropped, not clipped, when it doesn't fit; `--no-captain` turns it off.
- **The attention call:** when the main session ends a turn and is waiting on you, a deeper, longer cannon booms once. `--attention-sound ahoy` plays a deep, gravelly recorded "Ahoy, matey" instead, `say` speaks it with macOS `say`, and `off` silences it. Only the main session ending a turn arms it, at most one call per turn. It waits until nothing else has run for 6 seconds (no subagent, no other worktree's session), so a controller that is about to carry on by itself stays quiet; a new turn cancels it. Calls are at least 30 seconds apart, and a call that comes sooner is delayed, not dropped. It never sounds on the first look at a session that is already idle. A turn that ends without `end_turn`, such as one you interrupt, doesn't call.

## Read-only promise

agent-panel only reads transcript files under the Claude config dir. It never writes there, installs hooks, edits settings, sends input to a session or touches the network. It runs three commands: `git worktree list`, read-only, every few seconds to find the fleet; `afplay` to play the bundled cannon and attention WAVs; and, only with `--attention-sound say`, `say` to speak the attention call (`--no-sound` turns all sound off). Playing sound is its one side effect besides drawing.

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

**The fleet.** That directory's session is the flagship (the one with the captain). If it is in a git repo,
agent-panel also runs `git worktree list` every few seconds and follows the newest session in each other worktree
of the repo, the main checkout included: beside the controller you see every agent, beside an agent you see the
controller and the other agents. Worktrees appear and leave as `agent-session new` and `done` add and remove them;
a worktree with no Claude session yet adds nothing. Outside a git repo, or in a repo with no other worktrees (a
`--solo` session, say), it shows the one session exactly as before. Reading the worktree list changes nothing; the
read-only promise is unchanged.

A controller working across two repos adds the other with `--also-repo PATH` (repeatable; any folder in that repo
will do). Each of that repo's worktrees adds a ship labelled `<repo>:<worktree>`, for example `agent-harbor:harbor-prune`,
so a worktree name both repos use stays unambiguous. Its main checkout is left out, since that is usually the
other repo's own controller. A path that is not a git repo, or can't be read, adds nothing.

Rex split panes do not inherit `CLAUDE_CONFIG_DIR`. When it is unset, agent-panel looks in `~/.claude` and every `~/.claude-*` folder and follows the one whose copy of the project has the most recently written transcript. Pin one with `--config-dir PATH`; an explicit `--config-dir` beats the environment variable, which beats the search.

## Options

| Flag | Meaning |
| --- | --- |
| `--cwd PATH` | project directory to follow (default: current directory) |
| `--session ID` | pin one session instead of following the newest |
| `--also-repo PATH` | also show the worktree sessions of another git repo (repeatable) |
| `--config-dir PATH` | Claude config dir to read |
| `--no-sound` | no sound at all (cannon and attention call) |
| `--attention-sound {boom,ahoy,say,off}` | the sound when the main session waits on you (default `boom`) |
| `--no-captain` | no pirate captain on the main ship |
| `--keep-done SECONDS` | how long a finished subagent stays on screen (default 180) |

Without `--session` it follows the newest session in the project and only switches away from one that has been quiet for 60 seconds. A pinned session never switches. `--session` and `--config-dir` apply to the flagship; each other ship follows its worktree's newest session, in the config dir found the same way (the flag, then `CLAUDE_CONFIG_DIR`, then the newest of `~/.claude*`).

## Reading the display

Works at 50 columns. With a fleet the tree has one top-level row per ship: the flagship first as `main`, then each
other ship labelled with its worktree folder name, each followed by its own subagents, and the header adds
`· N ships`. A worktree folder named `main` is labelled `main-2`, and two folders with the same name get `-2`, `-3`
in worktree-list order. Other ships are plain boats (no captain, no Jolly Roger), and their sessions don't raise
the captain's arm. Only the flagship fires the cannon; its advisor line closes the flagship's rows, before the
other ships. Boats never overlap: one that meets another boat in its lane turns around (a follower holds
its place instead; a child that shares its leader's lane, as in the top lane, sails on its own), and every lane keeps a row of clear water above its tallest boat. The bottom lane is the
flagship's own, so nothing sails over the captain or into the cannon's arc; other boats use it only when the
harbor has a single lane. When space runs out the label is cut first (`…`), then the effort, then the burn bar; model and burn always stay. The harbor hides when it would get fewer than 8 rows. More sailing boats than fit show as `+N more` (top right); the flagship is placed first, then every running agent and its leaders, then the rest in tree order. That order holds on every frame: a boat keeps its place from the last frame only while no higher-priority boat needs the water.

Finished subagents (ones not leading a running one) stop sailing and moor at a pier at the right end of the bottom lane, fanned like a deck of cards with the most recently finished on top. The pile shows 5 boats at 80 columns and up, 3 from 40 columns, and the rest as `+N` over the pier. Below 40 columns there is no pier, only `+N docked` at the top left (shortened to `+N`, or left out, when `+N more` needs the row). So there are three counts: `+N more` for sailing boats with no room, `+N` at the pier for finished boats under the pile, and `· N done` in the header for retired ones.

With more than one ship on screen, every boat carries a dim label under its hull naming the ship it belongs to, so subagent boats can be told apart across ships: `Captain` for the flagship itself and `crew` for its subagents. Every other ship, and its subagents, carries the ticket id its worktree name starts with, `def-<digits>` or `feat-<digits>` in any case (`def-127-grading` becomes `def-127`, `feat-255-wizard` becomes `feat-255`), or else the name up to its first `-` (`harbor-ahoy` becomes `harbor`), cut to 8 characters with `…`. Two ships never share a label, ignoring case: ones that still would (the same worktree name in two repos, or `def-127-a` beside `def-127-b`) are numbered instead, `harbor-1` and `harbor-2` (a ticket id keeps all its digits, `def-127-1`, even past 8 characters), and only the flagship's own fleet reads `Captain` or `crew` (a worktree named `crew-x` gets a numbered label). A label counts as part of its boat, so labels never touch another boat or label, and the pile is named once under it when its ships' names fit. Labels are the first thing to go: none below 50 columns, and none when their extra row per lane would cost the harbor one of its first two lanes. With a single ship nothing changes.

A finished subagent leaves both the tree and the harbor 180 seconds after its last transcript entry (`--keep-done` changes this), and the header counts them, e.g. `· 20 done`. Ships never leave, and neither does a subagent that is running, leads a running one, or has a finished subagent of its own still on screen.

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

Fixtures are synthetic; no real transcript content is committed. The cannon and the deeper attention call are generated by `scripts/make_cannon.py`. `ahoy.wav` comes from `scripts/make_ahoy.sh`, which needs macOS `say` with the Daniel voice and ffmpeg; `say` output can differ between macOS versions, so the committed take is the reference.

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

A project whose `.claude/settings.json` or `.claude/settings.local.json` runs its own copy of the hook from
its `hooks` keeps it: the user-level hook stands down there, so each stop reports once. Only commands under
`hooks` count, and only ones that run a different file: a bare `agent-stop-hook`, `~/.local/bin/agent-stop-hook`
and any path that resolves to the installed hook are the user-level install, not a copy, and a `permissions`
entry or any other mention never counts. So a `bin/agent-stop-hook` that the project's settings don't run,
such as the one in each of this repo's worktrees, changes nothing. Two layouts still report twice per stop:
project settings that run the installed hook (by `~/.local/bin` or by its real path) on top of the user-level
wiring, and a project copy that is only a symlink to the installed hook. Both wire the same hook twice; drop
one of the two wirings.

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
