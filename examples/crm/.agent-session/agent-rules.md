- The worktree isolates the code, not the CRM. .env here holds the live CRM key and
  Slack token. Unless this task grants it by name, never run anything that writes to
  the CRM, posts to Slack or deploys: no `./flowlu.py create|update|delete`, no
  `./invoice.py create|set-pricing`, no `./notify.py` without `--dry-run`, no deploy,
  no curl to the worker's webhook. Read-only calls (`./flowlu.py list|get`) are fine.
  If the task needs a live write, don't make it: put the exact command and what it would
  change (from a dry run where the tool has one) in your report, and stop.
- Done means: a failing test committed before the fix, then green
  `python3 -m unittest discover -s tests` and `(cd worker && npm test)`. Report those
  results with your summary.
