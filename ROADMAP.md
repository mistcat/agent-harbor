# Roadmap

Nothing queued. See Later.

## Later

- Move campaignmonitor-rails partly onto the shared `agent-session` (its controller's view, 2026-11-17). Keep one script, with per-repo hooks for what is Rails-specific. Not before its release 1.15.9 has deployed: a changed teardown or inbox path mid-release is risk for no gain.
  1. Bring into the shared script: #331's teardown hardening (one delete guard, TERM only, 3 retries, always prune and delete the branch), which every repo's `done` should have; `--brief`, fixed so its reports don't land untracked in the main checkout (a dirty tree blocks `bin/deploy-staging`); `--model`/`--advisor` on `new` and `controller`; controller resume (`--fresh`, the recorded conversation id, the `controller-claude` pane check, the Stop hook's controller role); agent Rex ids recorded per worktree, so renamed sessions are still found (done in the shared script on 2026-11-23: `AGENT_SESSION_REX_ID` in the worktree's `.env`, as there, or the worktree's git dir).
  2. Add per-project `setup` and `teardown` hooks under `.agent-session/` for the per-agent test database and the port (3100 to 3199, plus `--server`). Teardown must read the same port that setup chose.
  3. Keep what that repo relies on: `<repo>-worktrees/<name>` and the name rule (Claude's scratchpad and project memory follow the path), the `pwd`/branch check in the preamble, rollback when setup fails, the Agent/Tests/Server tabs, `done` deleting a branch only when it is merged into origin/main and never for `--brief`, and the output format of `new` (the controller reads session ids from it). `COPY_FILES` covers `config/master.key`, `.env` and `.secrets/`.
  4. Switch the repo behind a throwaway-agent test, changing every consumer and doc of the inbox path (`tmp/agent-inbox` there) at once. The controller stays `captains-chair`, found by its recorded id.

## Known minor issues

None open.

## Done

- The 2026-11-13 review's minor issues (fixed 2026-11-17). The pier pile fans its cards three columns apart from a common edge, so each covered card shows a closed `\_/` hull whatever its size, and the top card shows its whole hull. Two subagents that claim each other as parent show up: one goes under main, unlinked, and the other hangs from it. `--session` with a missing transcript names the session instead of the generic waiting text. A boat that grows at the right edge moves left just enough instead of re-slotting at x=0. A transcript replaced by another file, even a larger one, is re-read from the start (checked by inode). The header goes through the unchanged-update cache. `config_dir()`/`project_dir()` are gone (`FileStats.last_entry_at` is used now, for a finished subagent's time). The README mentions ctrl+q and that cache reads are collected but not shown. The clips are still the v0.3 ones (the README says so); the phone clips moor two boats, a workaround for the old pile, and three would read fine if they are remade.
- The controller hears when an agent stops (2026-11-17). It runs its one `inbox --follow` under the Monitor tool, which wakes it on each report (a plain background command never wakes it, because `--follow` never exits). `inbox --peek` and `inbox --count` let a watcher look without eating reports. The Stop hook falls back to the transcript's last assistant text and writes no report when there is no message. `controller` records its Rex session ID (`controller-rex-id` beside the inbox), so a renamed controller is still found. Typing into the controller's pane with `rex send` was not built: its Enter would answer a permission prompt or submit whatever the user was typing.
- crm uses the shared `agent-session`: its `bin/agent-session` is a thin wrapper, and `crm/.agent-session/` matches `examples/crm/.agent-session/`.
- Finished subagents leave the tree and harbor 180s after they finish (`--keep-done`), counted in the header; running boats are laid out first.
- Boats never overlap each other or the captain; finished subagents moor in a fanned pile at a pier.
- Watch several Claude sessions at once: the whole fleet a controller is running (agent-panel follows every worktree of the repo).
