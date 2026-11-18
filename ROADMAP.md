# Roadmap

Nothing queued here; one follow-up in another repo under Later.

## Later

- campaignmonitor-rails runs its own `bin/agent-session` and `bin/agent-stop-hook`. The inbox changes (`inbox --peek`/`--count`, the hook's transcript fallback and empty-report skip) and the report lines its `brief_preamble` lacked are in mistcat/campaignmonitor-rails#333, awaiting review. Its controller keeps waking on a re-armed `inbox --wait`, which already works.

## Known minor issues

None open.

## Done

- The 2026-11-13 review's minor issues (fixed 2026-11-17). The pier pile fans its cards three columns apart from a common edge, so each covered card shows a closed `\_/` hull whatever its size, and the top card shows its whole hull. Two subagents that claim each other as parent show up: one goes under main, unlinked, and the other hangs from it. `--session` with a missing transcript names the session instead of the generic waiting text. A boat that grows at the right edge moves left just enough instead of re-slotting at x=0. A transcript replaced by another file, even a larger one, is re-read from the start (checked by inode). The header goes through the unchanged-update cache. `config_dir()`/`project_dir()` are gone (`FileStats.last_entry_at` is used now, for a finished subagent's time). The README mentions ctrl+q and that cache reads are collected but not shown. The phone clips still moor two boats, a workaround for the old pile; three would now read fine if they are remade.
- The controller hears when an agent stops (2026-11-17). It runs its one `inbox --follow` under the Monitor tool, which wakes it on each report (a plain background command never wakes it, because `--follow` never exits). `inbox --peek` and `inbox --count` let a watcher look without eating reports. The Stop hook falls back to the transcript's last assistant text and writes no report when there is no message. `controller` records its Rex session ID (`controller-rex-id` beside the inbox), so a renamed controller is still found. Typing into the controller's pane with `rex send` was not built: its Enter would answer a permission prompt or submit whatever the user was typing.
- crm uses the shared `agent-session`: its `bin/agent-session` is a thin wrapper, and `crm/.agent-session/` matches `examples/crm/.agent-session/`.
- Finished subagents leave the tree and harbor 180s after they finish (`--keep-done`), counted in the header; running boats are laid out first.
- Boats never overlap each other or the captain; finished subagents moor in a fanned pile at a pier.
- Watch several Claude sessions at once: the whole fleet a controller is running (agent-panel follows every worktree of the repo).
