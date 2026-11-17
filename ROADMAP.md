# Roadmap

Nothing queued. See Later.

## Later

- Switch the crm repo from its own copy of `bin/agent-session` to the shared one here (copy `examples/crm/.agent-session/`).

## Known minor issues

From the final review on 2026-11-13, not yet fixed:

- Three or more finished boats in the pier's pile: `_draw_dock` fans the cards two columns apart, so each middle card's hull is covered by the next card (a pile of three reads as two hulls with three masts; the mobile busy-morning clip shows two moored boats because of it). Found 2026-11-16 while making the phone clips.
- Two subagents that each claim the other as parent disappear instead of showing under main.
- `--session` with a missing file shows the generic "waiting" text.
- A tier upgrade near the right edge re-slots the boat to x=0.
- A transcript replaced by a larger file between polls is misread.
- The header re-lays out every tick (skips the unchanged-update cache).
- Dead code: `FileStats.last_entry_at`; `config_dir()`/`project_dir()` are unused outside tests.
- README doesn't mention quitting (ctrl+q) or that `cache_read` is collected but not shown.

## Done

- Finished subagents leave the tree and harbor 180s after they finish (`--keep-done`), counted in the header; running boats are laid out first.
- Boats never overlap each other or the captain; finished subagents moor in a fanned pile at a pier.
- Watch several Claude sessions at once: the whole fleet a controller is running (agent-panel follows every worktree of the repo).
