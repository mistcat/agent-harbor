# agent-panel: design

Date: 2026-11-13. Status: draft, awaiting approval. Build planned for 2026-11-14.

## Intent

A live, read-only terminal panel that sits in a Rex pane beside a Claude Code session and shows what that
session's agents are doing while Nate waits on them. Inspired by an animated "subagent tip" explainer video
(an Opus advisor, a Sonnet lead, Haiku subagents fanning out). Nate wants to see, at a glance:

1. which agents are children of which,
2. which model each agent runs (and its effort level),
3. each agent's token burn,
4. a fun graphic to watch while agents work.

## Goals

- One command, `agent-panel`, run in a Rex split pane beside a Claude session, follows that session live.
- Two stacked views of the same agent list ("business in front, party in the back"):
  - **Top: the tree.** One row per agent, nested by parent. Model, effort, status, burn, with a small burn bar
    and dots that pulse down the connector lines while a child is running.
  - **Bottom: the harbor.** One boat per agent: the same agents as the tree, drawn as an animated scene.
- Works with a non-standard Claude config dir (`CLAUDE_CONFIG_DIR`, here `~/.claude-personal`).
- General-purpose: not tied to the crm repo; usable from any project.

## Non-goals (v1)

- Watching several Claude sessions at once (the parallel `bin/agent-session` worktrees in crm). Possible v2.
- A scrolling event log. (The tree and harbor carry the events; see advisor flash.)
- Cost in dollars. Burn is tokens only.
- Running inside Claude Code as a mod, or in tmux.

## Anti-goals (a failure even if it works)

- **Never writes** to the Claude config dir, never installs hooks, never edits settings, never sends input to a
  session, never makes a network call. It only reads transcript files.
- Must not slow down the machine or the Claude session: incremental reads, a capped frame rate, near-idle CPU
  when nothing is running.
- Must not be unreadable at a normal side-pane width (about 50–70 columns).

## Constraints and verified facts

Verified on 2026-11-13 against a live session (Claude Code 2.1.311, `~/.claude-personal`):

- Main transcript: `$CLAUDE_CONFIG_DIR/projects/<project-slug>/<session-id>.jsonl`. For `/Users/nate/Code/crm`
  the slug is `-Users-nate-Code-crm`.
- Subagents: `<project-slug>/<session-id>/subagents/agent-<id>.jsonl` plus `agent-<id>.meta.json`, e.g.
  `{"agentType":"general-purpose","description":"Audit Claude Code monitor TUIs","toolUseId":"toolu_…",
  "spawnDepth":1,"model":"sonnet","finished":true}`.
- The parent's `Agent` tool call (`type: tool_use`, `name: "Agent"`) carries `description`, `model` and
  `subagent_type`; its `id` matches the meta file's `toolUseId`.
- Each assistant entry has `message.model` (e.g. `claude-sonnet-5-5`), `message.usage` (`input_tokens`,
  `cache_creation_input_tokens`, `cache_read_input_tokens`, `output_tokens`), and top-level `effort`,
  `perTurnEffort`, `advisorModel` (e.g. `claude-fable-5-1`), `requestedModel`, `isSidechain`.
- Advisor calls appear in the main transcript as `type: server_tool_use`, `name: "advisor"`, with timestamps,
  followed by an advisor result block. No separate token count for the advisor was found.
- Transcripts grow large (this session: 3 MB), so reads must be incremental (remember byte offsets).
- **One API reply is written as several entries (one per content block), each repeating the same `message.id`
  and identical `usage`.** In the sample, 122 assistant entries held 59 unique message ids, and no repeated id
  had different usage. Summing every entry roughly doubles the count, so usage must be counted once per
  `message.id`.
- The main transcript had no `isSidechain: true` entries; subagent usage lives only in the subagent files.

Unverified, for the builder to check: the slug rule for paths with dots or other characters; whether
`spawnDepth` > 1 ever occurs (a subagent spawning its own) and where those files land; how Workflow-tool
agents are stored; what marks the main session as idle vs working.

## Approaches considered

1. **Python + Textual (picked).** Textual (with Rich) supplies boxes, color, layout and timers, so the least code
   is hand-written. One dependency set, installed like `fetchr`. Nate is fine with dependencies.
2. Plain Python with curses, no dependencies. Matches crm's stdlib style but every box, color and animation
   is hand-built: about 1.5× the build effort.
3. Go with Bubble Tea. One fast binary, but a new language in Nate's tools; most build effort and hardest
   for Nate to tweak.

Prior art audited 2026-11-13 and rejected: claudectl (hardcodes `~/.claude`, can act on sessions), ccboard
(general analytics dashboard; no confirmed per-subagent model or advisor view), agent-dashboard (requires tmux,
can act on sessions), rehoboam (repo gone). No Textual-native sprite or particle library exists; asciimatics
has sprites but owns the whole screen, so boats and effects are hand-drawn.

## Design

### Location and install

- New repo `~/Code/claude_tools/agent-panel/`, same pattern as `fetchr`: `pyproject.toml`, `requirements.txt`,
  `.venv`, `install.sh` that symlinks `~/.local/bin/agent-panel`, `README.md`, tests in `tests/`.
- Launch beside the current pane (documented in the README):
  `rex split -s "$REX_SESSION" -b "$REX_BLOCK" --split=right --ratio 35 --label Agents --focus=false -- agent-panel`

### Which session it follows

- Project dir: from `--cwd` (default: the current directory) mapped to its slug under
  `${CLAUDE_CONFIG_DIR:-~/.claude}/projects/`.
- Session: `--session <id>` pins one session. Otherwise follow the most recently modified `*.jsonl` there,
  re-checked every few seconds, but only switch away from the current session once it has been quiet for 60 s
  and a newer file is active. That way a `/clear` or a new session is picked up, without the panel flapping
  between two live sessions in the same directory (decided). The header shows the session id's first 8
  characters so a switch is visible. A switch replaces the whole tree and harbor.
- Unlinked subagents (no matching `Agent` call found, e.g. after compaction, Workflow-tool agents, or a parent
  file not read yet) attach under main with a `?` marker rather than being dropped (decided). Nested agents
  link to whichever transcript holds their `toolUseId`, at any depth.

### Data model (the shared agent list)

One `Agent` record per agent, built by a reader that polls files (about every 0.5 s) and reads only new bytes:

- `id`, `parent_id` (subagent → the transcript holding the matching `Agent` tool call), `depth`
- `label` (main session: "main"; subagent: its description), `agent_type`
- `model` (latest `message.model`, shortened to e.g. "opus 5.5"), `effort` (latest `effort`)
- `status`: running / done (subagents: meta `finished`; main: working if its transcript changed recently,
  else idle; exact rule is the builder's call)
- `burn` = input + cache-creation + output tokens, cumulative, counted **once per `message.id`** (decided:
  dedupe by message id); `cache_read` kept separately and shown small. Each agent's burn comes only from its
  own transcript file; main's number is the main session alone, not a roll-up of its children (decided). Skip
  `isSidechain: true` entries in the main file, so a subagent can never be counted twice.
- `advisor_calls` (count) and `last_advisor_at`

Both views render from this one list, so they can never disagree.

### Top: the tree

```
 OPUS 5.5 · main · medium                ▮▮▮▮▯  49k
   ├──•──▶ sonnet 5.5 · audit TUIs  med   ▮▮▯▯▯  10k ◐
   └─────▶ haiku 5.5 · grep         low   ▮▯▯▯▯   2k ✓
 ◆ advisor (fable 5.1) · 2 calls · last 14:02
```

- Nested by parent, any depth. Colors by model family: Opus purple, Sonnet orange, Haiku blue, Fable (and
  unknown) a fourth color. Running rows have a dot pulsing along their connector; done rows are dimmed with ✓.
- Burn bar scale and the cache-read display are builder's calls.

### Bottom: the harbor

The same agents as boats on a waterline:

- **Size from burn, three tiers:** rowboat → sloop → galleon. An agent is upgraded mid-run when it crosses a
  threshold (thresholds are the builder's call).
- **Sail color by model**, matching the tree.
- **Running:** sails, moving, with a wake (`~ - ~` trail behind, fading).
- **Done:** anchored, bobbing, `zzz`.
- **Advisor call:** the main ship flashes and fires a cannon (flash at the gunport, a `*` arcing out, a splash).
  It fires when the call starts (the `server_tool_use` entry), not when the result arrives (decided). On first
  load, past calls are counted but don't fire; only new ones do.
- **Parent and child:** children sail just behind their parent, as a flotilla.
- Boats sit in lanes; if there are more agents than lanes fit, the builder picks a sensible fallback
  (smaller boats, or a "+3 more" marker). If the pane is too short, the harbor hides and the tree stays.

### Rendering and performance

- Textual app: tree widget on top, harbor widget below. Animation timer about 8–10 fps while anything is
  running, dropping to about 2 fps when all is idle.
- Reads only appended bytes; tolerates a partial last line (JSONL being written).
- Narrow panes (decided): it must work at 50 columns. Truncate in this order: the label (with `…`), then the
  effort column, then the burn bar; the model and burn number always stay. The harbor hides when the pane
  leaves it fewer than 8 rows.
- Its own `.venv`, Python 3.11 or newer (decided); doesn't share `fetchr`'s environment.

### Build order (decided)

All of the above is v1 scope, built in this order so each step is usable: reader and data model with tests →
tree view → harbor with static boats in three tiers → motion and wakes → anchored `zzz` → cannon fire →
flotilla grouping. If the build runs out of budget, stopping after any step leaves a working panel.

### Testing

- Unit tests for the reader against small **synthetic** JSONL and meta fixtures (no real transcript content
  committed): parent linking, model and effort extraction, burn sums, advisor counts, incremental reads,
  a partial last line.
- A headless Textual test (`App.run_test`) that the app starts, renders the tree for a fixture session, and
  survives a narrow pane. Visual polish is checked by eye in a real Rex pane.

## Future ideas (not v1)

- **Pirate captain for the main session** (Nate, 2026-11-13): a small captain figure in the harbor standing in
  for the main session, e.g. on the main ship's deck or on the dock giving orders. Leave room for it: keep the
  main session's sprite separate from the subagent boats so a captain can be added without reworking them.
- Watching several Claude sessions at once (see Non-goals).

## Left to the builder

Burn thresholds and bar scale; exact boat art; idle rule for the main session; colors beyond the four named;
lane layout and overflow; refresh intervals; how `--cwd` handles a path that has no project dir yet.

## Build sizing (rough)

About 300–600k tokens built inline; about 1–2M with the subagent-and-review workflow. The boats add roughly
50–100k over a simpler graphic.
