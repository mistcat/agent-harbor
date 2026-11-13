# Roadmap

1. **Pirate captain for the main session.** A small captain figure in the harbor standing in for the main
   session, on the main ship's deck or on the dock giving orders. The main ship's sprite is already kept
   separate from the subagent boats (`MAIN_SPRITE_KEY` in `agent_panel/boats.py`) so the captain can replace
   it without reworking them.
2. **`agent-session panel` command.** Open `agent-panel` in a Rex split beside the controller (or beside a
   named agent session) with one command, instead of the long `rex split ... -- agent-panel` line.

## Later

- Watch several Claude sessions at once: the whole fleet a controller is running.
- Switch the crm repo from its own copy of `bin/agent-session` to the shared one here (copy `examples/crm/.agent-session/`).

## Known minor issues

From the final review on 2026-11-13, not yet fixed:

- Two subagents that each claim the other as parent disappear instead of showing under main.
- `--session` with a missing file shows the generic "waiting" text.
- A tier upgrade near the right edge re-slots the boat to x=0.
- A transcript replaced by a larger file between polls is misread.
- The header re-lays out every tick (skips the unchanged-update cache).
- Dead code: `FileStats.last_entry_at`; `config_dir()`/`project_dir()` are unused outside tests.
- README doesn't mention quitting (ctrl+q) or that `cache_read` is collected but not shown.
- `build/` is not in `.gitignore`.
