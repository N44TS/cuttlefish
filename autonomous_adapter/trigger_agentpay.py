"""
Trigger AgentPay from parsed intent (offer/accept).

Call pay_agent() when the poster sees an accept; or surface instructions
for the worker to start agentpay worker.
"""

import os
from typing import Any, Dict, List, Optional

try:
    from agentpay.tools import pay_agent
    from agentpay.schema import JobResult
    from agentpay import hire_agent, AgentWallet
    from agentpay.payments import get_pay_fn
except ImportError:
    pay_agent = None
    JobResult = None
    hire_agent = None
    AgentWallet = None
    get_pay_fn = None


def trigger_hire_by_capability(
    capability: str,
    known_agents: List[str],
    task_type: str,
    input_data: Dict[str, Any],
    job_id: Optional[str] = None,
) -> "JobResult":
    """
    Hire by capability: discover first agent that offers the capability, then run 402 flow.
    Set AGENTPAY_KNOWN_AGENTS=ens1.eth,ens2.eth (worker ENS names must have agentpay.capabilities set).
    """
    if hire_agent is None or AgentWallet is None or get_pay_fn is None:
        raise RuntimeError("agentpay not installed. pip install agentpay")
    wallet = AgentWallet()
    return hire_agent(
        wallet,
        task_type=task_type,
        input_data=input_data,
        capability=capability,
        known_agents=known_agents,
        job_id=job_id,
        pay_fn=get_pay_fn("yellow_full"),
    )


def trigger_hire(
    worker_ens_name: str,
    task_type: str,
    input_data: Dict[str, Any],
    job_id: Optional[str] = None,
) -> "JobResult":
    """
    After poster sees an accept: hire that worker via AgentPay.

    Uses CLIENT_PRIVATE_KEY from env. worker_ens_name should be the replier's ENS.
    """
    if pay_agent is None:
        raise RuntimeError("agentpay not installed. pip install agentpay")
    return pay_agent(
        worker_ens_name=worker_ens_name,
        task_type=task_type,
        input_data=input_data,
        job_id=job_id,
    )


def trigger_hire_from_accept(
    accept: Dict[str, Any],
    task_type: str,
    input_data: Dict[str, Any],
    job_id: Optional[str] = None,
) -> "JobResult":
    """
    Convenience: accept dict from parse_accept -> trigger_hire.
    If AGENTPAY_WORKER_BASE_URL is set (e.g. http://localhost:8000), use it and skip ENS (local testing).
    """
    worker_base_url = (os.getenv("AGENTPAY_WORKER_BASE_URL") or "").strip().rstrip("/")
    if worker_base_url:
        return pay_agent(
            task_type=task_type,
            input_data=input_data,
            job_id=job_id,
            worker_endpoint=worker_base_url,
        )
    worker_ens = (accept.get("worker_ens") or "").strip()
    if not worker_ens:
        raise ValueError("accept must have worker_ens")
    return trigger_hire(
        worker_ens_name=worker_ens,
        task_type=task_type,
        input_data=input_data,
        job_id=job_id,
    )
