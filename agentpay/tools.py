"""
Single-call helpers for bots and adapters.

pay_agent() = create wallet from env + hire_agent. One entry point so the bot
doesn't need to reason about AgentWallet or hire_agent parameters.
"""

from typing import Any, Dict, Optional

from agentpay.schema import JobResult
from agentpay.wallet import AgentWallet
from agentpay.flow import hire_agent
from agentpay.payments import get_pay_fn


def pay_agent(
    worker_ens_name: str,
    task_type: str,
    input_data: Dict[str, Any],
    job_id: Optional[str] = None,
    pay_fn=None,
    **kwargs: Any,
) -> JobResult:
    """
    Hire an agent and pay them. Uses CLIENT_PRIVATE_KEY from env (no wallet arg).

    One call for bots/adapters: resolve worker by ENS, send job, pay, return result.

    Args:
        worker_ens_name: Worker's ENS name (e.g. "bob.eth").
        task_type: e.g. "analyze-data", "summarize".
        input_data: Job input dict.
        job_id: Optional; default auto-generated.
        pay_fn: Optional; default is yellow_chunked_full.
        **kwargs: Passed to hire_agent (e.g. mainnet, rpc_url).

    Returns:
        JobResult with status, result, error.
    """
    wallet = AgentWallet()
    if pay_fn is None:
        pay_fn = get_pay_fn("yellow_chunked_full")
    return hire_agent(
        wallet,
        task_type=task_type,
        input_data=input_data,
        worker_ens_name=worker_ens_name.strip().removesuffix(".eth") + ".eth"
        if not worker_ens_name.strip().endswith(".eth")
        else worker_ens_name.strip(),
        job_id=job_id,
        pay_fn=pay_fn,
        **kwargs,
    )
