"""
E2E: Client hires worker (by ENS or URL), pays via Yellow. For moltbot / HackMoney.

Set WORKER_ENS_NAME=worker.eth to resolve endpoint from ENS (hire_agent).
Else uses WORKER_ENDPOINT or http://localhost:8000/submit-job (request_job).

Terminal 1 (worker): AGENTPAY_WORKER_WALLET=0x..., AGENTPAY_PAYMENT_METHOD=yellow_full (or yellow_channel)
Terminal 2 (client): CLIENT_PRIVATE_KEY=0x... + ytest.usd + Sepolia ETH. Optional: AGENTPAY_CLIENT_ADDRESS, WORKER_ENS_NAME.

Important: Client and worker must be DIFFERENT addresses (different wallets). Payment fails if they are the same.
ENS registration takes about 2.5 minutes to complete; wait before using a newly registered name.
"""

import os
import sys
from pathlib import Path

if "agentpay" not in sys.modules:
    _root = Path(__file__).resolve().parent.parent.parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

from agentpay import Job, AgentWallet, request_job, hire_agent


def main():
    if not os.getenv("CLIENT_PRIVATE_KEY") and not os.getenv("AGENTPAY_PRIVATE_KEY"):
        print("[CLIENT] Set CLIENT_PRIVATE_KEY")
        return

    wallet = AgentWallet()
    task_type = "analyze-data"
    input_data = {"query": "Summarize this document"}

    worker_ens = os.getenv("WORKER_ENS_NAME", "").strip()
    endpoint = os.getenv("WORKER_ENDPOINT", "http://localhost:8000/submit-job")

    try:
        if worker_ens:
            print("[CLIENT] Resolving worker via ENS:", worker_ens, flush=True)
            result = hire_agent(
                wallet,
                task_type=task_type,
                input_data=input_data,
                worker_ens_name=worker_ens,
                job_id="yellow_job_001",
            )
        else:
            print("[CLIENT] Sending job to worker (URL)...")
            job = Job(
                job_id="yellow_job_001",
                requester=wallet.address,
                task_type=task_type,
                input_data=input_data,
            )
            result = request_job(job, endpoint, wallet, pay_fn=None)
        print("[CLIENT] ---", flush=True)
        print("[CLIENT] Status:", result.status, flush=True)
        if result.result:
            print("[CLIENT] Result:", result.result)
        if getattr(result, "payment_tx_hash", None):
            print("[CLIENT] Settlement tx:", result.payment_tx_hash)
            print("[CLIENT] Etherscan: https://sepolia.etherscan.io/tx/" + result.payment_tx_hash)
        if result.error:
            print("[CLIENT] Error:", result.error, flush=True)
        if result.status == "completed":
            if getattr(result, "yellow_session_id", None) and getattr(result, "payment_tx_hash", None):
                print("[CLIENT] OK – job done (session + on-chain settlement).")
            else:
                print("[CLIENT] OK – job done, payment on-chain.")
    except Exception as e:
        print("[CLIENT] Error:", e)
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
