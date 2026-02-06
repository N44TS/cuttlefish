"""
AgentPay — DeFi rails for AI agents.

Enables Moltbot/Moltbook agents to:
- Discover other agents via ENS
- Request tasks (402 Payment Required flow)
- Pay for work (on-chain or Yellow off-chain)
- Emit EAS attestations as job receipts (reputation/reviews)

No API keys required by default: agent wallet is a local keypair.
pip install agentpay  # then agent generates/loads key and pays from its address
"""

__version__ = "0.1.0"

from agentpay.schema import Job, Bill, JobResult
from agentpay.wallet import AgentWallet
from agentpay.flow import request_job, request_job_by_ens, hire_agent
from agentpay.ens2 import (
    discover_agents,
    get_agent_info,
    get_ens_name_for_registration,
    get_ens_registration_quote,
    get_agent_provisioning_from_env,
    provision_ens_identity,
    register_ens_name,
    register_and_provision_ens,
    register_and_provision_ens_from_env,
    setup_new_agent,
)
from agentpay.faucet import ensure_funded, check_eth_balance, check_yellow_balance, prompt_funding_choice

__all__ = [
    "__version__",
    "Job",
    "Bill",
    "JobResult",
    "AgentWallet",
    "request_job",
    "request_job_by_ens",
    "hire_agent",
    "discover_agents",
    "get_agent_info",
    "get_agent_provisioning_from_env",
    "provision_ens_identity",
    "get_ens_name_for_registration",
    "get_ens_registration_quote",
    "register_ens_name",
    "register_and_provision_ens",
    "register_and_provision_ens_from_env",
    "setup_new_agent",
    "ensure_funded",
    "check_eth_balance",
    "check_yellow_balance",
    "prompt_funding_choice",
]
