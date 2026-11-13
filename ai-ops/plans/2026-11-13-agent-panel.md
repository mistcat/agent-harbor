# agent-panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A read-only Textual app, `agent-panel`, that runs in a Rex pane and shows a Claude Code session's agents as a live tree (top) and an animated harbor of boats (bottom).

**Architecture:** A polling reader tails the session's JSONL transcripts (main and subagents) by byte offset and folds them into one `list[Agent]`. Two pure render functions turn that list into Rich `Text` (tree, harbor), and a thin Textual app calls them on a timer. Rendering logic stays pure so it is unit-testable without a terminal.

**Tech Stack:** Python ≥ 3.11 (verified working on the machine's 3.15.2), textual 8.2.8, rich 15.0.0, pytest 9.2.0. All four versions were installed and a headless `App.run_test(size=(50,20))` was run on 2026-11-13.

**Spec:** `ai-ops/specs/2026-11-13-agent-panel-design.md` (read it first; "decided" marks in it are binding).

## Global Constraints

- Read-only: never write under the Claude config dir, no hooks, no settings edits, no input sent to sessions, no network calls. The one allowed side effect besides drawing is playing the cannon WAV with `afplay`.
- Config dir: `$CLAUDE_CONFIG_DIR`, else `~/.claude`.
- Token usage counted once per `message.id`; skip `isSidechain: true` entries in the main file.
- `burn` = `input_tokens + cache_creation_input_tokens + output_tokens`; `cache_read_input_tokens` kept separately.
- Must render at 50 columns. Truncate order: label → effort → burn bar; model and burn number always stay. The harbor hides when it would get fewer than 8 rows.
- Session switch: only away from a session quiet ≥ 60 s, to a newer active file; `--session` pins.
- Unlinked subagents attach under main with `linked=False` (shown with `?`).
- Cannon fires on new `advisor` `server_tool_use` entries only, never for ones present at first load.
- Animation 8–10 fps while anything runs, about 2 fps when all idle.
- Model colors: opus purple, sonnet orange, haiku blue, everything else (fable, unknown) a fourth color.
- Test fixtures are synthetic. Never commit real transcript content.
- Package layout and install follow `~/Code/claude_tools/fetchr/` (`pyproject.toml` with `[project.scripts]`, `.venv`, `install.sh` symlinking into `~/.local/bin`, `.gitignore` the same as fetchr's).

## Review Focus

1. **A transcript truncated or replaced (size < saved offset)** → the reader resets that file's offset to 0 and its stats, not crash or read garbage. Test in Task 2.
2. **Subagent `.jsonl` exists without its `.meta.json` yet (or the reverse)** → the agent still shows, with model from its entries, status `running`, and the description falls back to the agent id. Test in Task 3.
3. **No project dir or no session yet** (fresh project, wrong cwd) → the app shows "waiting for a Claude session in <dir>" and keeps polling. Test in Task 4.
4. **Pane resized below 50 cols or under 8 rows mid-run** → no exception; the tree truncates, the harbor hides. Test in Task 4 (tree) and Task 5 (harbor).
5. **Many agents (20+)** → the tree scrolls or clips without crashing, and the harbor shows as many boats as fit plus a `+N` marker. Test in Task 5.

## OPEN QUESTIONS / ASSUMPTIONS (verify during the build)

- **ASSUMPTION:** project slug = absolute path with `/` replaced by `-` (verified only for `/Users/nate/Code/crm` → `-Users-nate-Code-crm`). Task 3 Step 1 checks `ls "$CLAUDE_CONFIG_DIR/projects"` for a path containing `.` or `_` and pins the rule in a test. If no rule fits, fall back to matching a project dir whose transcripts' `cwd` field equals the target cwd.
- **ASSUMPTION:** main session "running" = transcript modified within the last 10 s; otherwise `idle`.
- **OPEN:** where nested subagents (`spawnDepth` > 1) and Workflow-tool agents are stored. Linking by `toolUseId` across every known transcript covers nesting if the files land in the same `subagents/` dir. Otherwise they show unlinked under main, which the spec accepts.

---

### Task 1: Package scaffold and install

**Files:**
- Create: `pyproject.toml` (name `agent-panel`, `requires-python = ">=3.11"`, script `agent-panel = "agent_panel.cli:main"`), `requirements.txt` (`textual==8.2.8`, `rich==15.0.0`, `pytest==9.2.0`), `install.sh` (fetchr's minus the crawl4ai and `doctor` lines; final check `agent-panel --help`), `.gitignore`, `agent_panel/__init__.py`, `agent_panel/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Produces: `agent_panel.cli.main(argv: list[str] | None = None) -> int` with args `--cwd PATH` (default cwd), `--session ID`, `--help`. In this task, `main` only parses the args and returns 0. Task 4 wires it to the app.

- [ ] **Step 1:** Write `test_help_exits_zero` (`main(["--help"])` raises `SystemExit` with code 0) and `test_parses_session_and_cwd` (expose `parse_args(argv) -> argparse.Namespace`; assert `.session == "abc"` and `.cwd == Path("/x")`).
- [ ] **Step 2:** `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt -e . && .venv/bin/pytest -q` → FAIL (module missing).
- [ ] **Step 3:** Implement the scaffold files above.
- [ ] **Step 4:** `.venv/bin/pytest -q` → PASS. Then run `./install.sh` and `agent-panel --help` → shows usage.
- [ ] **Step 5:** Commit `feat: package scaffold and install`.

### Task 2: Transcript reader

**Files:**
- Create: `agent_panel/transcript.py`, `tests/helpers.py` (synthetic entry builders), `tests/test_transcript.py`

**Interfaces:**
- Produces:
  - `class Tail(path: Path)` with `.poll() -> list[dict]`: parsed new complete lines since the last call. Skips lines that aren't valid JSON, keeps a partial last line buffered, and resets if the file shrank.
  - `@dataclass class FileStats`: `model: str | None`, `effort: str | None`, `advisor_model: str | None`, `burn: int`, `cache_read: int`, `advisor_calls: int`, `last_advisor_at: str | None`, `agent_calls: dict[str, dict]` (tool_use id → `{"description","model","subagent_type"}`), `seen_ids: set[str]`, `last_entry_at: str | None`.
  - `fold(stats: FileStats, entries: list[dict], skip_sidechain: bool) -> int`: updates stats in place and returns the number of **new** advisor calls in these entries.
  - `short_model(model_id: str | None) -> str`: e.g. `"claude-sonnet-5-5"` → `"sonnet 5.5"`, `"claude-opus-5-5"` → `"opus 5.5"`, `"claude-fable-5-1"` → `"fable 5.1"`, `None` → `"?"`, unknown shape → unchanged.
  - `tests/helpers.py`: `assistant(msg_id, model, usage, effort="medium", blocks=(), sidechain=False, ts=...) -> dict`, `agent_call(tool_id, description, model) -> dict` (a content block), `advisor_call(ts) -> dict` (block), `write_jsonl(path, entries, partial_tail: str = "")`.

- [ ] **Step 1: Inspect a real sample.** Run a short `python3 -I` script over one real transcript in `$CLAUDE_CONFIG_DIR/projects/*/` and its `subagents/*.meta.json`. Confirm these field paths exist as the spec states (print only key names and types, never content): `type`, `message.id`, `message.model`, `message.usage.*`, `effort`, `advisorModel`, `isSidechain`, `timestamp`; content blocks `{type: tool_use, name: Agent, id, input.description, input.model}`; `{type: server_tool_use, name: advisor}`. Note any difference at the top of `transcript.py` and in the test helpers.
- [ ] **Step 2: Write failing tests:**
  - `test_usage_counted_once_per_message_id`: two entries with id `m1` and the same usage `{input 10, cache_creation 100, cache_read 1000, output 5}` plus one `m2` with `{1, 0, 0, 2}` → `burn == 118`, `cache_read == 1000`.
  - `test_sidechain_skipped_when_asked`: a sidechain entry adds nothing with `skip_sidechain=True`.
  - `test_latest_model_and_effort_win`: a later entry's model or effort replaces the earlier one.
  - `test_agent_calls_indexed_by_tool_id`: `agent_calls["toolu_1"]["description"] == "grep"`.
  - `test_advisor_calls_counted_and_new_returned`: the first fold of 2 advisor blocks returns 2; a later fold of 1 more returns 1; `advisor_calls == 3`; `last_advisor_at` is the newest timestamp.
  - `test_tail_keeps_partial_line`: a file ending in a half line → poll returns only complete entries; after appending the rest, the next poll returns it.
  - `test_tail_resets_when_file_shrinks` (Review Focus 1).
  - `test_tail_skips_bad_json`.
  - `test_short_model` covering the cases above.
- [ ] **Step 3:** `.venv/bin/pytest tests/test_transcript.py -q` → FAIL.
- [ ] **Step 4:** Implement. `Tail` opens, seeks to the offset and reads to EOF on each poll (no long-lived handle).
- [ ] **Step 5:** Run → PASS. Commit `feat: transcript reader with per-message dedupe`.

### Task 3: Session model (discovery, subagents, linking, switching)

**Files:**
- Create: `agent_panel/model.py`, `agent_panel/session.py`, `tests/test_session.py`

**Interfaces:**
- Consumes: `Tail`, `FileStats`, `fold`, `short_model` (Task 2).
- Produces:
  - `model.py`: `@dataclass class Agent`: `id: str`, `parent_id: str | None`, `depth: int`, `label: str`, `agent_type: str`, `model: str` (short), `effort: str | None`, `status: Literal["running","done","idle"]`, `burn: int`, `cache_read: int`, `advisor_calls: int`, `last_advisor_at: str | None`, `linked: bool`.
  - `session.py`:
    - `config_dir() -> Path`
    - `project_dir(cwd: Path, cfg: Path) -> Path | None` (slug rule per OPEN QUESTIONS; `None` if missing)
    - `pick_session(proj: Path, current: Path | None, now: float, quiet_s: float = 60) -> Path | None`
    - `@dataclass class Snapshot`: `session_id: str`, `agents: list[Agent]` (tree order: parent before children, siblings by start time), `new_shots: int`, `advisor_model: str | None` (short form of main's latest `advisorModel`).
    - `class Watcher(proj: Path, pinned: str | None = None)` with `.poll(now: float | None = None) -> Snapshot | None` (`None` = no session yet). Main is `id "main"`, `label "main"`, `depth 0`.

- [ ] **Step 1:** Check the slug rule (OPEN QUESTIONS) with `ls "$CLAUDE_CONFIG_DIR/projects"`, and pin what you find in `test_project_dir_slug`.
- [ ] **Step 2: Write failing tests** (temp dirs built with `tests/helpers.py`):
  - `test_subagent_linked_to_main_by_tool_use_id`: main has an `agent_call("toolu_1", ...)`, and `subagents/agent-a1.meta.json` has `toolUseId "toolu_1"`, `model "sonnet"`, `finished false` → agent `a1` with `parent_id == "main"`, `depth == 1`, `status == "running"`, `linked`.
  - `test_nested_subagent_links_to_its_parent_agent`: `a2`'s toolUseId is found in `agent-a1.jsonl` → `parent_id == "a1"`, `depth == 2`, ordered after `a1`.
  - `test_unlinked_subagent_attaches_to_main`: no matching call → `parent_id == "main"`, `linked is False`.
  - `test_jsonl_without_meta_still_shown` (Review Focus 2): label falls back to the agent id, status `running`, model from its entries.
  - `test_finished_meta_is_done`.
  - `test_main_running_vs_idle`: mtime within 10 s → `running`; older → `idle` (pass `now`).
  - `test_new_shots_zero_on_first_poll_then_counts_new`.
  - `test_pick_session_stays_until_quiet_60s` and `test_pick_session_switches_after_quiet`, plus `test_pinned_session_never_switches`.
  - `test_no_project_dir_returns_none`.
- [ ] **Step 3:** Run → FAIL.
- [ ] **Step 4:** Implement. On each poll: re-pick the session; glob `subagents/agent-*.jsonl` and `*.meta.json`; tail and fold each file (main with `skip_sidechain=True`); build a `toolUseId → owner id` map from every file's `agent_calls`; build the agents and order them depth-first. On a session switch, discard all tails and stats. `new_shots` counts only main-file advisor calls after the first poll.
- [ ] **Step 5:** Run → PASS. Also run `Watcher` once against this real project dir in a REPL and eyeball the output. Then commit `feat: session watcher builds the agent tree`.

### Task 4: Tree view and the running app

**Files:**
- Create: `agent_panel/colors.py`, `agent_panel/tree.py`, `agent_panel/app.py`, `tests/test_tree.py`, `tests/test_app.py`
- Modify: `agent_panel/cli.py` (run the app)

**Interfaces:**
- Consumes: `Agent`, `Snapshot`, `Watcher`, `project_dir`, `config_dir` (Task 3).
- Produces:
  - `colors.py`: `model_color(model: str) -> str` (a Rich color for each family) and `FAMILIES = ("opus","sonnet","haiku","other")`.
  - `tree.py`: `render_tree(agents: list[Agent], width: int, frame: int, advisor_model: str | None) -> rich.text.Text`.
  - `app.py`: `class AgentPanelApp(App)`, built with `(watcher: Watcher | None, waiting_dir: Path)`. It has widget ids `#header`, `#tree` and `#harbor` (`#harbor` is a placeholder `Static` until Task 5), and a timer that polls the watcher about every 0.5 s and repaints every frame.

- [ ] **Step 1: Write failing tests:**
  - `test_tree_nests_children_under_parent`: a line for `a2` is indented more than `a1`, which is indented more than main.
  - `test_tree_shows_model_burn_and_status`: contains `sonnet 5.5`, `10k` (burn 10_288 formatted as `10k`; 1_250_000 → `1.2M`), `✓` for done, and a running marker for running agents.
  - `test_tree_marks_unlinked_with_question_mark`.
  - `test_tree_advisor_line`: when main has `advisor_calls == 2`, a line contains `advisor` and `2 calls`.
  - `test_tree_truncates_at_50_cols`: a 200-char label → every line ≤ 50 chars, model and burn still present, label ends with `…`.
  - `test_tree_pulse_moves_with_frame`: the running connector differs between `frame=0` and `frame=1`; a done connector does not.
  - `test_app_waiting_message` (Review Focus 3): `watcher=None` → `#tree` text contains `waiting for a Claude session`.
  - `test_app_survives_resize` (Review Focus 4): `run_test(size=(80,30))`, then `pilot.resize_terminal(30, 6)`, then pause → no exception.
  - App tests use `asyncio.run(...)` inside a plain test function (no pytest-asyncio).
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement. Header: `agent-panel · <session id first 8> · <project name>`.
- [ ] **Step 4:** Run → PASS. Manual check: launch it in Rex beside this session with `rex split -s "$REX_SESSION" -b "$REX_BLOCK" --split=right --ratio 35 --label Agents --focus=false -- agent-panel`, start a subagent, and confirm its row appears and finishes with ✓. Then `rex capture` the pane.
- [ ] **Step 5:** Commit `feat: live agent tree in a Textual app`. **This is the first usable stopping point.**

### Task 5: Harbor, static boats in three tiers

**Files:**
- Create: `agent_panel/boats.py`, `agent_panel/harbor.py`, `tests/test_harbor.py`
- Modify: `agent_panel/app.py` (replace the `#harbor` placeholder; hide it under 8 rows)

**Interfaces:**
- Consumes: `Agent`, `model_color`.
- Produces:
  - `boats.py`: `TIER_SLOOP = 50_000`, `TIER_GALLEON = 500_000` (adjust by eye), `tier(burn: int) -> Literal["rowboat","sloop","galleon"]`, `SPRITES: dict[str, list[str]]` for `rowboat`/`sloop`/`galleon` (each 3–5 lines; the sail characters marked so they can be colored), and a separate `MAIN_SPRITE_KEY` hook so a future captain can replace main's sprite (spec "Future ideas").
  - `harbor.py`: `@dataclass class Boat`: `agent_id: str`, `x: float`, `lane: int`, `direction: int`, `tier: str`. Then `layout(agents: list[Agent], width: int, height: int, prev: dict[str, Boat]) -> tuple[dict[str, Boat], int]` (boats and the overflow count) and `render_harbor(agents, boats, width, height, frame) -> rich.text.Text`.

- [ ] **Step 1: Write failing tests:**
  - `test_tier_thresholds`: 0 → rowboat, 50_000 → sloop, 500_000 → galleon.
  - `test_upgrade_keeps_position`: an agent crossing a tier keeps its `x` and lane from `prev`.
  - `test_overflow_marker` (Review Focus 5): 25 agents in a 50×10 harbor → overflow > 0, and the render contains `+N`.
  - `test_render_fits_box`: every rendered line ≤ width, and the line count == height.
  - `test_harbor_hidden_under_8_rows`: the app at height where the harbor gets < 8 rows → `#harbor` not displayed.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement (water line of `~`, boats placed in lanes, sail colored by model). **Step 4:** Run → PASS, then look at it in the Rex pane.
- [ ] **Step 5:** Commit `feat: harbor with tiered boats`.

### Task 6: Motion, wake, anchored zzz, frame rate

**Files:**
- Modify: `agent_panel/harbor.py`, `agent_panel/app.py`
- Test: `tests/test_harbor.py`

**Interfaces:**
- Produces: `step(boats: dict[str, Boat], agents: list[Agent], dt: float, width: int) -> None` (moves running boats and turns them at the edges; done and idle boats stay put). `render_harbor` adds a fading wake behind moving boats, plus bobbing (an offset on alternate frames) and `zzz` for anchored boats. App: `fps_for(agents) -> float` returns 10 if any agent is running, else 2.

- [ ] **Step 1: Write failing tests:** `test_running_boat_moves_done_boat_stays`, `test_boat_turns_at_edge`, `test_wake_behind_moving_boat` (wake characters on the trailing side only), `test_anchored_boat_shows_zzz`, `test_fps_for`.
- [ ] **Step 2–4:** FAIL → implement → PASS. Check by eye that CPU stays low when idle (`top -pid <pid>`, roughly ≤ 2% when idle).
- [ ] **Step 5:** Commit `feat: sailing, wakes and anchored boats`.

### Task 7: Cannon fire on advisor calls

**Files:**
- Create: `agent_panel/effects.py`, `agent_panel/sound.py`, `scripts/make_cannon.py`, `agent_panel/assets/cannon.wav` (generated), `tests/test_effects.py`, `tests/test_sound.py`
- Modify: `pyproject.toml` (package data for `assets/*.wav`), `agent_panel/cli.py` (`--no-sound`)
- Modify: `agent_panel/app.py`, `agent_panel/harbor.py`

**Interfaces:**
- Consumes: `Snapshot.new_shots`.
- Produces: `@dataclass class Shot`: `x: float`, `y: float`, `vx: float`, `age: int`. Plus `fire(main_boat: Boat) -> Shot`, `advance(shots: list[Shot]) -> list[Shot]` (gravity arc; returns surviving shots and adds a splash state when one hits the waterline), and `overlay(text_lines, shots, flash: bool)` for the gunport flash on the main ship for about 3 frames.

- Also produces (sound): `scripts/make_cannon.py` (stdlib `wave`/`math`/`random` only) writes `agent_panel/assets/cannon.wav` (about 0.8 s, 22050 Hz mono, a 50–60 Hz thump plus a noise burst with an exponential decay). The generated WAV is committed and included as package data. `agent_panel/sound.py`: `class Boomer(enabled: bool, min_gap_s: float = 2.0, player: str = "afplay")` with `.boom(now: float) -> bool`. It starts `subprocess.Popen([player, wav], stdout=DEVNULL, stderr=DEVNULL)` without waiting, returns `False` when disabled, rate-limited or the player is missing (`shutil.which`), and never raises. CLI: `--no-sound`.

- [ ] **Step 1: Write failing tests:** `test_shot_arcs_and_splashes` (y rises, then falls, and the shot ends as a splash then disappears), `test_one_shot_per_new_advisor_call`, `test_no_fire_on_first_load` (an app fed a snapshot with past advisor calls and `new_shots == 0` creates no shots), `test_boomer_rate_limits` (`boom(0)` True, `boom(1)` False, `boom(2.5)` True; use `player="true"` so nothing plays), `test_boomer_disabled_and_missing_player` (`enabled=False` → False; `player="no-such-binary"` → False, no exception), and `test_cannon_wav_valid` (the `wave` module opens it: 1 channel, 22050 Hz, 0.5–1.2 s).
- [ ] **Step 2–4:** FAIL → implement → PASS. Check by eye and ear: an advisor call in the watched session fires the cannon and booms once.
- [ ] **Step 5:** Commit `feat: cannon fire on advisor calls`.

### Task 8: Flotilla grouping, README, final check

**Files:**
- Modify: `agent_panel/harbor.py`
- Create: `README.md` (what it is, read-only promise, install, the `rex split` launch line, `--session`/`--cwd`, the tier and color key)
- Test: `tests/test_harbor.py`

- [ ] **Step 1:** Write failing `test_children_sail_behind_parent`: a child boat's lane is next to its parent's, and its x trails the parent's on the side opposite the parent's direction, within a small gap.
- [ ] **Step 2–4:** FAIL → implement (children follow the parent's x with an offset instead of free-sailing) → PASS.
- [ ] **Step 5:** Run the full suite: `.venv/bin/pytest -q` → all pass. Read-only check: `grep -rnE "open\([^)]*['\"][wa]|write_text|unlink|rmtree|requests|urllib|socket" agent_panel/` → no hits. Do a final by-eye run in Rex during a session that spawns 2+ subagents and calls the advisor.
- [ ] **Step 6:** Commit `feat: flotillas and README`.
