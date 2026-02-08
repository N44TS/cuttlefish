#!/usr/bin/env bash
# Start OpenClaw with this repo's .env loaded (PATH, CLIENT_PRIVATE_KEY, etc.)
# so the bot can see the skill and run agentpay commands.
# Usage: ./scripts/run-openclaw.sh gateway   or   ./scripts/run-openclaw.sh tui
# Run from repo root, or: ./scripts/run-openclaw.sh tui
set -e
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"
if [ -f .env ]; then
  set -a
  source .env
  set +a
fi
# So agentpay is on PATH when the bot runs it (e.g. pip install -e . in venv)
[ -d "$REPO_ROOT/.venv/bin" ] && export PATH="$REPO_ROOT/.venv/bin:$PATH"
exec openclaw "$@"
