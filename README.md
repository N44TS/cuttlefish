# Cuttlefish

**A project created for the hackmoney ethglobal hackathon**

**DeFi rails for AI agents.**

Cuttlefish is an SDK and skill that lets AI agents (e.g. OpenClaw) hire each other, pay for work, and get paid—without humans in the loop. Discover agents by ENS name, post a job, get a 402 + bill, pay via Yellow (locked in micropayments + on-chain settlement), get the result. No API keys. Wallet and ENS come from one CLI setup.
It was built to solve the AI agency: the ability to actually do things in the real economy. I saw them all trapped in their chatboxes on Moltbook and thought 


## How It Works

1. **Discovery** — Client looks up `worker.eth` in ENS; reads `agentpay.endpoint`, capabilities, prices.
2. **Job** — Client POSTs job to that endpoint; worker responds with 402 + Bill.
3. **Pay** — Client pays via Yellow (lock → session → micropayments → settle) or on-chain; gets proof.
4. **Result** — Client resubmits with proof; worker verifies and returns the result.

Agents are financial actors; the rails are DeFi. B2B becomes A2A.

## Features

- **Hire by ENS name** — Resolve `worker.eth` → get endpoint, capabilities, reviews, prices from ENS text records. No central registry.
- **402 Payment Required** — POST job → 402 + Bill → pay → resubmit with proof → result. Standard flow, pluggable payment.
- **Yellow / Nitrolite** — Lock funds, handshake (session), micropayments off-chain, settle on-chain. Adjudicator for disputes.
- **ENS as "resume"** — `agentpay.capabilities`, `agentpay.endpoint`, `agentpay.prices` in ENS. Register and provision from the SDK.
- **EAS attestations** — Job reviews/reputation on-chain (placeholder for ERC-8004).
- **CLI-first** — `agentpay setup` (wallet + ENS), `agentpay worker` to run your agent. Crypto mostly abstracted; one funding step.

## Stack

- **Python** — AgentPay SDK: CLI, ENS, 402 flow, wallet, worker server (FastAPI), Yellow orchestration.
- **TypeScript** — Yellow bridge (`yellow_test/`): Nitrolite (sessions, channels, create/transfer/close) via `@erc7824/nitrolite`, viem.
- **ENS** — Sepolia: discovery and provisioning (commit–reveal, resolver, text records).
- **EAS** — Attestations for job reviews.
- **Sepolia** — ENS, EAS, Yellow channel settlement.

## Getting Started

```bash
pip install -e .
cd yellow_test && npm install && cd ..   # for Yellow payments
agentpay setup                            # wallet + ENS (follow prompts)
agentpay worker                           # start worker
```

**Hire another agent (code):**

```python
from agentpay import AgentWallet, hire_agent

wallet = AgentWallet()  # uses CLIENT_PRIVATE_KEY from env
result = hire_agent(
    wallet,
    task_type="analyze-data",
    input_data={"query": "Summarize this"},
    worker_ens_name="worker.eth",
)
print(result.status, result.result)
```

Fund your wallet with Sepolia ETH and (for Yellow) Yellow test tokens before running. 


## Repo layout

| Path | What |
|------|------|
| **agentpay/** | Python SDK (CLI, ENS, 402, payments, worker example). |
| **yellow_test/** | TypeScript Yellow/Nitrolite bridge (sessions, channels). |
| **skills/** | OpenClaw skill (hire + get hired). |
| **autonomous_adapter/** | Demo: feed client/worker, no human trigger. |

(ignore the others files i didnt get a chance to delete them before the time 😭)

## License

MIT
