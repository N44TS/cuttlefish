"""
Trigger AgentPay from parsed intent (offer/accept).

Call pay_agent() when the poster sees an accept; or surface instructions
for the worker to start agentpay worker.
"""

from typing import Any, Dict, Optional

try:
    from agentpay.tools import pay_agent
    from agentpay.schema import JobResult
except ImportError:
    pay_agent = None
    JobResult = None


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
    """
    worker_ens = (accept.get("worker_ens") or "").strip()
    if not worker_ens:
        raise ValueError("accept must have worker_ens")
    return trigger_hire(
        worker_ens_name=worker_ens,
        task_type=task_type,
        input_data=input_data,
        job_id=job_id,
    )
