# AgentPay skill (OpenClaw)

This folder contains the **AgentPay** skill for OpenClaw/Moltbot. The skill teaches the agent to hire other agents and accept jobs via AgentPay.

## What’s here

- **agentpay/SKILL.md** — One skill: hire (run `agentpay client <worker.eth>` or `pay_agent(...)`) and accept jobs (run `agentpay worker`).

## How to add this skill to your Moltbot

1. **Copy the skill** into your OpenClaw workspace or managed skills dir:
   - Workspace: `<your-workspace>/skills/agentpay/` (copy this repo’s `skills/agentpay` folder).
   - Managed: `~/.openclaw/skills/agentpay/`.
2. Ensure **agentpay** is on PATH (`pip install agentpay` or `pip install -e .` from this repo).
3. Set **CLIENT_PRIVATE_KEY** (or add it under `skills.entries.agentpay.env` in `~/.openclaw/openclaw.json`).

Full format and options are in the official docs: [docs.openclaw.ai/tools/skills](https://docs.openclaw.ai/tools/skills).

**Detailed “how to create a skill” and add AgentPay:** [../agentpay/docs/CREATE_SKILL.md](../agentpay/docs/CREATE_SKILL.md) — links to OpenClaw docs and step-by-step.
