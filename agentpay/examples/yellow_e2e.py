"""
E2E: Client pays via Yellow channel (on-chain). For moltbot / HackMoney.

Terminal 1 (worker): AGENTPAY_WORKER_WALLET=0x... (or worker key). Run worker_server.py
Terminal 2 (client): CLIENT_PRIVATE_KEY=0x... + ytest.usd + Sepolia ETH. Run this script.
"""

import os
import sys
from pathlib import Path

if "agentpay" not in sys.modules:
    _root = Path(__file__).resolve().parent.parent.parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

from agentpay import Job, AgentWallet, request_job
from agentpay.payments import get_pay_fn


def main():
    if not os.getenv("CLIENT_PRIVATE_KEY") and not os.getenv("AGENTPAY_PRIVATE_KEY"):
        print("[CLIENT] Set CLIENT_PRIVATE_KEY")
        return

    wallet = AgentWallet()
    job = Job(
        job_id="yellow_job_001",
        requester=wallet.address,
        task_type="analyze-data",
        input_data={"query": "Summarize this document"},
    )
    endpoint = os.getenv("WORKER_ENDPOINT", "http://localhost:8000/submit-job")

    print("[CLIENT] Sending job to worker...")
    pay_fn = get_pay_fn("yellow_channel")
    try:
        result = request_job(job, endpoint, wallet, pay_fn=pay_fn)
        print("[CLIENT] ---")
        print("[CLIENT] Status:", result.status)
        if result.result:
            print("[CLIENT] Result:", result.result)
        if getattr(result, "payment_tx_hash", None):
            print("[CLIENT] Settlement tx:", result.payment_tx_hash)
            print("[CLIENT] Etherscan: https://sepolia.etherscan.io/tx/" + result.payment_tx_hash)
        if result.error:
            print("[CLIENT] Error:", result.error)
        if result.status == "completed":
            print("[CLIENT] OK – job done, payment on-chain.")
    except Exception as e:
        print("[CLIENT] Error:", e)
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
