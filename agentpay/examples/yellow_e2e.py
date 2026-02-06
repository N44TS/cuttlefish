"""
E2E: Client hires worker via ENS (required for ENS prize), pays via Yellow.

ENS: Set WORKER_ENS_NAME=hahahagg.eth so the client resolves the worker URL from ENS
(agentpay.endpoint). No hardcoded worker URL.

Yellow: Worker can set AGENTPAY_PAYMENT_METHOD=yellow_channel (default) or yellow_full
so payment settles on-chain (money moves; tx on Etherscan).

Terminal 1 (worker): Provision ENS with endpoint (e.g. http://YOUR_IP:8000). Then:
  AGENTPAY_PAYMENT_METHOD=yellow_channel AGENTPAY_WORKER_WALLET=0x... python agentpay/examples/worker_server.py
Terminal 2 (client):
  CLIENT_PRIVATE_KEY=0x... WORKER_ENS_NAME=hahahagg.eth python agentpay/examples/yellow_e2e.py

For local testing only you can set WORKER_ENDPOINT=http://localhost:8000/submit-job
instead of WORKER_ENS_NAME (ENS not used).
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
        sys.exit(1)

    wallet = AgentWallet()
    task_type = "analyze-data"
    input_data = {"query": "Summarize this document"}

    worker_ens = os.getenv("WORKER_ENS_NAME", "").strip()
    endpoint = os.getenv("WORKER_ENDPOINT", "").strip()

    # ENS required for prize: prefer WORKER_ENS_NAME so client discovers worker from ENS.
    if not worker_ens and not endpoint:
        print("[CLIENT] Set WORKER_ENS_NAME (e.g. hahahagg.eth) for ENS prize, or WORKER_ENDPOINT for URL-only.")
        sys.exit(1)

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
            if "submit-job" not in endpoint:
                endpoint = endpoint.rstrip("/") + "/submit-job"
            if not endpoint.startswith("http"):
                endpoint = "http://" + endpoint
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
            sys.exit(1)
        if result.status == "completed":
            if getattr(result, "yellow_session_id", None) and getattr(result, "payment_tx_hash", None):
                print("[CLIENT] OK – job done (session + on-chain settlement).")
            elif getattr(result, "payment_tx_hash", None):
                print("[CLIENT] OK – job done, payment on-chain (money moved).")
            else:
                print("[CLIENT] OK – job done.")
    except Exception as e:
        print("[CLIENT] Error:", e)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
