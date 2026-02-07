#!/usr/bin/env bash
# Copy agentpay skill into ~/.openclaw/skills and ensure it's in openclaw.json.
# Run from repo root (e.g. by postCreateCommand).
set -e
OPENCLAW_HOME="${OPENCLAW_HOME:-$HOME/.openclaw}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

mkdir -p "$OPENCLAW_HOME/skills"
cp -r "$REPO_ROOT/skills/agentpay" "$OPENCLAW_HOME/skills/"

CONFIG_FILE="$OPENCLAW_HOME/openclaw.json"
mkdir -p "$(dirname "$CONFIG_FILE")"
if [ -f "$CONFIG_FILE" ]; then
  CONFIG="$(cat "$CONFIG_FILE")"
else
  CONFIG="{}"
fi

# Merge skills.entries.agentpay using Node (already in container)
node -e "
const fs = require('fs');
let config = {};
try { config = JSON.parse(process.env.CONFIG); } catch (e) {}
if (!config.skills) config.skills = {};
if (!config.skills.entries) config.skills.entries = {};
config.skills.entries.agentpay = { enabled: true };
fs.writeFileSync(process.env.CONFIG_FILE, JSON.stringify(config, null, 2));
" CONFIG="$CONFIG" CONFIG_FILE="$CONFIG_FILE"

echo "AgentPay skill installed at $OPENCLAW_HOME/skills/agentpay and enabled in openclaw.json"
