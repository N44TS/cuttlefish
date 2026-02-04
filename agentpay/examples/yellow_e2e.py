"""
Yellow end-to-end example: Full 402 flow with Yellow escrow.

Run from agentpay directory (path fix below allows import agentpay without pip install).

This demonstrates the complete flow:
1. Client requests job → Worker returns 402 + Bill (payment_method: "yellow")
2. Client creates Yellow session (quorum 2) and submits state (client signs)
3. Client resubmits with session proof
4. Worker receives proof → calls sign_state_worker (worker signs)
5. Both signatures applied → Worker verifies and returns result

Prerequisites:
- Worker server running with Yellow env (Terminal 1).
- In Terminal 2 (client): set AGENTPAY_PRIVATE_KEY to the **client's** private key.
  The address for that key must match AGENTPAY_CLIENT_ADDRESS on the worker.

Run:
  # Terminal 1: Worker
  export AGENTPAY_PAYMENT_METHOD=yellow
  export AGENTPAY_WORKER_PRIVATE_KEY=0x...   # Worker's key
  export AGENTPAY_CLIENT_ADDRESS=0x...      # Client's address (same as Terminal 2 wallet)
  python examples/worker_server.py

  # Terminal 2: Client (must set client key)
  export AGENTPAY_PRIVATE_KEY=0x...         # Client's key (address = AGENTPAY_CLIENT_ADDRESS)
  python examples/yellow_e2e.py
"""

import os
import sys
from pathlib import Path
if "agentpay" not in sys.modules:
    _root = Path(__file__).resolve().parent.parent.parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

from agentpay import Job, AgentWallet, request_job


def main():
    print("=" * 70)
    print("Yellow End-to-End Example")
    print("=" * 70)
    print()

    if not os.getenv("AGENTPAY_PRIVATE_KEY"):
        print("ERROR: Set AGENTPAY_PRIVATE_KEY in this terminal (client's private key).")
        print("  Example: export AGENTPAY_PRIVATE_KEY=0x...")
        print("  The address for that key must match AGENTPAY_CLIENT_ADDRESS on the worker.")
        return

    # Create client wallet
    wallet = AgentWallet()
    client_address = wallet.address
    print(f"Client address: {client_address}")
    print("(Set AGENTPAY_CLIENT_ADDRESS={} in worker server env)".format(client_address))
    print()

    # Create job
    job = Job(
        job_id="yellow_job_001",
        requester=client_address,
        task_type="analyze-data",
        input_data={"query": "Summarize this document"},
    )

    print(f"Requesting job: {job.job_id}")
    print(f"Task: {job.task_type}")
    print()

    # Request job (will use Yellow if worker returns payment_method: "yellow")
    worker_endpoint = os.getenv("WORKER_ENDPOINT", "http://localhost:8000/submit-job")
    print(f"Worker endpoint: {worker_endpoint}")
    print()

    try:
        result = request_job(job, worker_endpoint, wallet)
        print("=" * 70)
        print("Result:")
        print("=" * 70)
        print(f"Status: {result.status}")
        if result.result:
            print(f"Result: {result.result}")
        if result.worker:
            print(f"Worker: {result.worker}")
        if result.attestation_uid:
            print(f"Attestation UID: {result.attestation_uid}")
        if result.error:
            print(f"Error: {result.error}")
        print()

        if result.status == "completed":
            print("✅ Job completed successfully!")
            print("✅ Payment verified via Yellow escrow (two-party signatures)")
        else:
            print("❌ Job failed or incomplete")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
