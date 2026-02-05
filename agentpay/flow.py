"""
402 flow: request job → get bill → pay → resubmit with proof → result.

Worker returns 402 + Bill; requester pays; requester resubmits with
X-Payment: <tx_hash or proof>; worker verifies and returns JobResult.
Optionally the requester creates an EAS review (attestation) after success.

ENS integration: request_job_by_ens (resolve worker by ENS name) and
hire_agent (discover by capability or by ENS name, then run 402 flow).
"""

import os
from typing import Any, Callable, Dict, List, Optional

import requests
import time
from web3 import Web3
from web3.exceptions import TransactionNotFound

from agentpay.schema import Job, Bill, JobResult
from agentpay.wallet import AgentWallet
from agentpay.payments import get_pay_fn


def _wait_for_receipt(tx_hash: str, rpc_url: str, max_wait: int = 90) -> None:
    """Poll for tx receipt. Catches TransactionNotFound (tx not indexed yet) and retries."""
    w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 30}))
    step = 3
    for i in range(max_wait // step):
        try:
            receipt = w3.eth.get_transaction_receipt(tx_hash)
            if receipt is not None and receipt.get("status") == 1:
                return
        except TransactionNotFound:
            pass
        time.sleep(step)
    raise RuntimeError(f"Tx {tx_hash} not found after {max_wait}s. Try same RPC as bridge (e.g. SEPOLIA_RPC).")


def request_job(
    job: Job,
    worker_endpoint: str,
    wallet: AgentWallet,
    pay_fn: Optional[Callable[[Bill, AgentWallet], str]] = None,
    headers: Optional[dict] = None,
    create_review: bool = True,
) -> JobResult:
    """
    Execute 402 flow: submit job, if 402 then pay and resubmit with proof.
    If create_review is True and the job completes, the requester creates an
    EAS attestation (review of the worker); requester pays gas for that.

    worker_endpoint: e.g. "https://worker.example.com/submit-job"
    pay_fn: (bill, wallet) -> payment_proof (e.g. tx_hash). Default: get_pay_fn() (Circle if configured, else Sepolia).
    """
    pay_fn = pay_fn or get_pay_fn()
    headers = headers or {}
    payload = job.to_submit_payload()

    # 1) Submit without payment
    r = requests.post(worker_endpoint, json=payload, headers=headers, timeout=30)
    if r.status_code == 200:
        return JobResult(**r.json())
    if r.status_code != 402:
        return JobResult(
            status="error",
            error=f"Worker returned {r.status_code}: {r.text}",
        )

    # 2) Parse bill
    try:
        data = r.json()
        # Support both {"amount", "recipient"} and legacy PAYMENT_REQUIRED|amount|recipient
        if isinstance(data, dict):
            bill = Bill(
                amount=float(data["amount"]),
                recipient=data["recipient"],
                chain_id=data.get("chain_id"),
                message=data.get("message"),
                payment_method=data.get("payment_method"),
            )
        else:
            return JobResult(status="error", error="Invalid 402 response format")
    except Exception as e:
        return JobResult(status="error", error=f"Failed to parse bill: {e}")

    # 3) Yellow only. Use bill's method or default channel (on-chain).
    if pay_fn is None:
        payment_method = bill.payment_method or "yellow_channel"
        pay_fn = get_pay_fn(payment_method)

    # 4) Pay
    try:
        proof = pay_fn(bill, wallet)
        if proof and proof.startswith("0x"):
            print("[CLIENT] Paid. Tx:", proof[:18] + "...")
    except Exception as e:
        return JobResult(status="error", error=f"Payment failed: {e}")

    # 4b) Wait for tx to be mined (tx hash only, or last segment of yellow_full)
    tx_to_wait = None
    if proof and proof.startswith("0x") and len(proof) == 66:
        tx_to_wait = proof
    elif proof and proof.strip().startswith("yellow_full|"):
        parts = proof.strip().split("|")
        if len(parts) >= 5 and parts[-1].startswith("0x") and len(parts[-1]) == 66:
            tx_to_wait = parts[-1]
    if tx_to_wait:
        print("[CLIENT] Waiting for chain confirmation...")
        rpc = os.getenv("SEPOLIA_RPC") or os.getenv("ALCHEMY_RPC_URL") or "https://1rpc.io/sepolia"
        _wait_for_receipt(tx_to_wait, rpc)
        print("[CLIENT] Tx confirmed. Sending proof to worker...")

    # 5) Resubmit with payment proof
    resubmit_headers = {**headers, "X-Payment": proof}
    r2 = requests.post(worker_endpoint, json=payload, headers=resubmit_headers, timeout=90)
    if r2.status_code != 200:
        return JobResult(
            status="error",
            error=f"Resubmit returned {r2.status_code}: {r2.text}",
        )
    result = JobResult(**r2.json())

    # 5b) Attach session_id or tx hash for client to use
    if proof:
        p = proof.strip()
        if p.startswith("yellow_full|"):
            parts = p.split("|")
            if len(parts) >= 5:
                result.payment_tx_hash = parts[-1]
                result.yellow_session_id = parts[2].strip() if len(parts) > 2 else None
        elif p.startswith("0x") and len(p) == 66:
            result.payment_tx_hash = p
        elif p.startswith("yellow|") or p.startswith("session:"):
            if p.startswith("yellow|"):
                parts = p.split("|")
                if len(parts) >= 2:
                    result.yellow_session_id = parts[1].strip()
            elif p.startswith("session:"):
                parts = p.split(":")
                if len(parts) >= 2:
                    result.yellow_session_id = parts[1].strip()

    # 6) Optional: requester creates EAS review (recipient = worker; requester pays gas)
    if create_review and result.status == "completed" and result.worker:
        try:
            from agentpay.eas import create_job_review
            review_tx = create_job_review(
                job_id=job.job_id,
                worker_address=result.worker,
                requester_wallet=wallet,
                amount_usdc=bill.amount,
                task_type=job.task_type,
                success=True,
            )
            if review_tx:
                result.attestation_uid = review_tx
        except Exception:
            pass  # Don't fail the whole result if review creation fails
    return result


def _submit_job_url(endpoint: str) -> str:
    """Ensure endpoint is a full URL to the submit-job path."""
    endpoint = (endpoint or "").strip().rstrip("/")
    if not endpoint:
        raise ValueError("Worker endpoint is empty")
    if "submit-job" not in endpoint:
        endpoint = endpoint + "/submit-job"
    if not endpoint.startswith("http://") and not endpoint.startswith("https://"):
        endpoint = "https://" + endpoint
    return endpoint


def request_job_by_ens(
    worker_ens_name: str,
    job: Job,
    wallet: AgentWallet,
    rpc_url: Optional[str] = None,
    mainnet: bool = False,
    pay_fn: Optional[Callable[[Bill, AgentWallet], str]] = None,
    headers: Optional[dict] = None,
    create_review: bool = True,
) -> JobResult:
    """
    Resolve worker by ENS name, then run the 402 flow (pay, resubmit, result).

    Looks up agentpay.endpoint from ENS text records. If the record is a base URL,
    appends /submit-job. Use this when you know the worker's ENS name.

    worker_ens_name: e.g. "worker.eth" or "search.service.eth"
    job: Job to send
    wallet: Requester wallet (pays the bill)
    rpc_url, mainnet: Passed to get_agent_info for ENS resolution (Sepolia by default)
    """
    from agentpay.ens import get_agent_info

    info = get_agent_info(worker_ens_name, rpc_url=rpc_url, mainnet=mainnet)
    if not info:
        return JobResult(status="error", error=f"ENS lookup failed: no agent info for {worker_ens_name}")
    endpoint = info.get("endpoint") or ""
    if not endpoint.strip():
        return JobResult(
            status="error",
            error=f"Agent {worker_ens_name} has no agentpay.endpoint set in ENS",
        )
    submit_url = _submit_job_url(endpoint)
    return request_job(
        job,
        submit_url,
        wallet,
        pay_fn=pay_fn,
        headers=headers,
        create_review=create_review,
    )


def hire_agent(
    wallet: AgentWallet,
    task_type: str,
    input_data: Dict[str, Any],
    worker_ens_name: Optional[str] = None,
    capability: Optional[str] = None,
    known_agents: Optional[List[str]] = None,
    job_id: Optional[str] = None,
    requester: Optional[str] = None,
    price_usdc: Optional[float] = None,
    rpc_url: Optional[str] = None,
    mainnet: bool = False,
    pay_fn: Optional[Callable[[Bill, AgentWallet], str]] = None,
    headers: Optional[dict] = None,
    create_review: bool = True,
) -> JobResult:
    """
    Discover worker via ENS (by name or by capability), then run 402 flow. One entry point for "hire and pay."

    Call with either:
      - worker_ens_name="worker.eth"  → resolve endpoint from ENS, send job, pay, get result.
      - capability="analyze", known_agents=["a.eth","b.eth"]  → discover_agents, pick first match, same flow.

    wallet: Requester wallet (pays the bill).
    task_type: e.g. "analyze-data", "summarize".
    input_data: Job input (dict).
    job_id: Optional; default is generated from task_type + simple id.
    requester: Optional; default is wallet.address.
    """
    import secrets
    from agentpay.ens import discover_agents, get_agent_info

    if worker_ens_name:
        info = get_agent_info(worker_ens_name, rpc_url=rpc_url, mainnet=mainnet)
        if not info:
            return JobResult(status="error", error=f"ENS lookup failed: no agent info for {worker_ens_name}")
        agent_name = worker_ens_name
        endpoint = (info.get("endpoint") or "").strip()
        if not endpoint:
            return JobResult(
                status="error",
                error=f"Agent {worker_ens_name} has no agentpay.endpoint set in ENS",
            )
        submit_url = _submit_job_url(endpoint)
    elif capability is not None and known_agents:
        matches = discover_agents(capability, known_agents, rpc_url=rpc_url, mainnet=mainnet)
        if not matches:
            return JobResult(
                status="error",
                error=f"No agent found for capability '{capability}' in known_agents ({len(known_agents)} names)",
            )
        info = matches[0]
        agent_name = info.get("name") or "unknown"
        endpoint = (info.get("endpoint") or "").strip()
        if not endpoint:
            return JobResult(status="error", error=f"Agent {agent_name} has no agentpay.endpoint set in ENS")
        submit_url = _submit_job_url(endpoint)
    else:
        return JobResult(
            status="error",
            error="Provide either worker_ens_name or both capability and known_agents",
        )

    job = Job(
        job_id=job_id or f"{task_type}-{secrets.token_hex(4)}",
        requester=requester or wallet.address,
        task_type=task_type,
        input_data=input_data,
        price_usdc=price_usdc,
    )
    return request_job(
        job,
        submit_url,
        wallet,
        pay_fn=pay_fn,
        headers=headers,
        create_review=create_review,
    )
