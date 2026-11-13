#!/usr/bin/env bash
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found. Install it (e.g. 'brew install python') and re-run." >&2
  exit 1
fi

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
.venv/bin/python -m pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install -e .

mkdir -p "$HOME/.local/bin"
ln -sf "$REPO/.venv/bin/agent-panel" "$HOME/.local/bin/agent-panel"
ln -sf "$REPO/bin/agent-session" "$HOME/.local/bin/agent-session"
ln -sf "$REPO/bin/agent-stop-hook" "$HOME/.local/bin/agent-stop-hook"
ln -sf "$REPO/bin/rexclaude" "$HOME/.local/bin/rexclaude"

if ! echo ":$PATH:" | grep -q ":$HOME/.local/bin:"; then
  echo ""
  echo "Add ~/.local/bin to your PATH. For zsh (default on macOS):"
  echo "  echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.zshrc && source ~/.zshrc"
fi

echo ""
echo "Done. Verifying:"
"$HOME/.local/bin/agent-panel" --help
