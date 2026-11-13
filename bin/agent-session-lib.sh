# Shared by bin/agent-session and bin/rexclaude (sourced, never run). Needs $PROG set.

# Refuse a model name that could break out of the --settings JSON or the command line.
check_model() { # check_model <what> <value>
  [[ "$2" =~ ^[][a-z0-9.-]+$ ]] || { echo "$PROG: $1 may only use a-z 0-9 . [ ] -: '$2'" >&2; exit 1; }
}

rex_session_id() { # rex_session_id <label>
  rex ls --json | jq -r --arg l "$1" '.sessions[] | select(.label == $l) | .session_id' | head -1
}

# Open agent-panel in a split beside <block> of <session>, following the checkout <dir>.
# Best effort: it never returns non-zero, so a panel problem can't fail (or roll back) a command.
open_panel() { # open_panel <session> <block> <dir>
  if ! command -v agent-panel >/dev/null; then
    echo "$PROG: agent-panel not on PATH, skipping the panel" >&2
    return 0
  fi
  if [[ -z "$2" ]]; then
    echo "$PROG: couldn't find the Agent pane, skipping the panel" >&2
    return 0
  fi
  rex split -s "$1" -b "$2" --split=right --ratio 35 --label Agents --focus=false -c "$3" -- agent-panel >/dev/null ||
    echo "$PROG: couldn't open the panel (rex split failed)" >&2
  return 0
}

# Pass the launching profile through so an agent runs under the same Claude account as
# whoever started it; Rex panes don't run ~/.zshrc or direnv.
CLAUDE_ENV=(env CLAUDE_CONFIG_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}")

show_in_app() { # show_in_app <session> — bring it up in the first connected Rex app, if any
  local client
  client="$(rex client ls --json | jq -r '[.clients[] | select(.info.kind == "app" and .connection_state == "connected")][0].client_id // empty')"
  [[ -n "$client" ]] && rex -C "$client" do session.select session_id="$1" >/dev/null 2>&1 || true
}
