# Roadmap

Nothing queued.

## Later

- Port the 2026-11-17 inbox changes (Monitor in the controller prompt, `inbox --peek`/`--count`, the hook's transcript fallback and empty-report skip) to campaignmonitor-rails, which runs its own `bin/agent-session` and `bin/agent-stop-hook`. Also give its `brief_preamble` the two report lines the normal preamble has (end with your report; never type into another Rex session). Without them a `--brief` agent improvises and typed its report into a guessed Rex session instead of `captains-chair`.

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

- The controller hears when an agent stops (2026-11-17). It runs its one `inbox --follow` under the Monitor tool, which wakes it on each report (a plain background command never wakes it, because `--follow` never exits). `inbox --peek` and `inbox --count` let a watcher look without eating reports. The Stop hook falls back to the transcript's last assistant text and writes no report when there is no message. `controller` records its Rex session ID (`controller-rex-id` beside the inbox), so a renamed controller is still found. Typing into the controller's pane with `rex send` was not built: its Enter would answer a permission prompt or submit whatever the user was typing.
- crm uses the shared `agent-session`: its `bin/agent-session` is a thin wrapper, and `crm/.agent-session/` matches `examples/crm/.agent-session/`.
- Finished subagents leave the tree and harbor 180s after they finish (`--keep-done`), counted in the header; running boats are laid out first.
- Boats never overlap each other or the captain; finished subagents moor in a fanned pile at a pier.
- Watch several Claude sessions at once: the whole fleet a controller is running (agent-panel follows every worktree of the repo).
