"""
Two Agents Demo: Agent A hires Agent B via ENS + Yellow.

Shows how two AI agents can work together autonomously after pip install.

Agent A (Client): Discovers Agent B by ENS name, sends job, pays via Yellow.
Agent B (Worker): Receives job, returns 402, verifies payment, does work, returns result.

Run:
  Terminal 1 (Agent B - Worker):
    AGENTPAY_PAYMENT_METHOD=yellow_chunked_full \
    AGENTPAY_WORKER_WALLET=0x9D81b753B71E47Bd17cfD0cA52B80bB6D3cA2836 \
    AGENTPAY_WORKER_PRIVATE_KEY=0xd2db2dd62bd7e2de8cbfb5d9f7ae783da521860bdb53aeaf503400344ff5f677 \
    python agentpay/examples/worker_server.py

  Terminal 2 (Agent A - Client):
    CLIENT_PRIVATE_KEY=0xf09d06af8f6da650ceb389b34eca48df7a6db356373e812ba560a77403d134ac \
    WORKER_ENS_NAME=hahahagg.eth \
    python agentpay/examples/two_agents_demo.py

What happens:
1. Agent A resolves Agent B's URL from ENS (hahahagg.eth)
2. Agent A sends job → Agent B returns 402 + Bill
3. Lock: Both bots create channels (on-chain)
4. Handshake: Create Nitrolite session (off-chain)
5. Micro-payments: 10 chunks (worker sends 10% → client signs → repeat)
6. Settlement: Channel close (on-chain tx = money moved)
7. Agent B verifies payment → does work → returns result
8. Agent A gets result

No humans involved. No API keys. Just agents working together.
"""
import os
import sys
from pathlib import Path

if "agentpay" not in sys.modules:
    _root = Path(__file__).resolve().parent.parent.parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

from agentpay import AgentWallet, hire_agent
from agentpay.payments import get_pay_fn


def main():
    print("=" * 70)
    print("Two Agents Demo: Agent A hires Agent B")
    print("=" * 70)

    worker_ens = os.getenv("WORKER_ENS_NAME", "").strip()
    if not worker_ens:
        print("\n❌ Set WORKER_ENS_NAME (e.g. hahahagg.eth)")
        print("   This is Agent B's ENS name. Agent A will discover Agent B's URL from ENS.")
        sys.exit(1)

    if not os.getenv("CLIENT_PRIVATE_KEY") and not os.getenv("AGENTPAY_PRIVATE_KEY"):
        print("\n❌ Set CLIENT_PRIVATE_KEY (Agent A's wallet key)")
        sys.exit(1)

    wallet = AgentWallet()
    print(f"\n[Agent A] Wallet: {wallet.address}")
    print(f"[Agent A] Discovering Agent B via ENS: {worker_ens}")

    # Agent A hires Agent B with chunked micropayments + on-chain settlement
    print("\n[Agent A] Sending job to Agent B...")
    print("  → Agent B will return 402 + Bill")
    print("  → Agent A will pay via Yellow (chunked micropayments + on-chain settlement)")
    print("  → Agent B will verify payment, do work, return result")

    result = hire_agent(
        wallet,
        task_type="analyze-data",
        input_data={"query": "Summarize this document for the demo"},
        worker_ens_name=worker_ens,
        job_id="agent_a_to_b_001",
        pay_fn=get_pay_fn("yellow_chunked_full"),  # Chunked micropayments + on-chain settlement
    )

    print("\n" + "=" * 70)
    print("Result")
    print("=" * 70)

    if result.status != "completed":
        print(f"\n❌ Failed: {result.error}")
        sys.exit(1)

    print(f"\n✅ Status: {result.status}")
    print(f"✅ Result: {result.result}")
    print(f"✅ Worker: {result.worker}")

    tx_hash = getattr(result, "payment_tx_hash", None)
    session_id = getattr(result, "yellow_session_id", None)

    if tx_hash:
        print(f"\n✅ Settlement tx (money moved on-chain): {tx_hash}")
        print(f"   Etherscan: https://sepolia.etherscan.io/tx/{tx_hash}")

    if session_id:
        print(f"\n✅ Session ID: {session_id}")
        print("   (Chunked micropayments: 10 chunks signed off-chain)")

    print("\n" + "=" * 70)
    print("✅ Success: Agent A hired Agent B, paid via Yellow, got result")
    print("=" * 70)
    print("\nWhat happened automatically:")
    print("  1. ✅ ENS lookup: Agent A found Agent B's URL from ENS")
    print("  2. ✅ Lock: Both bots locked funds (channels created)")
    print("  3. ✅ Handshake: Nitrolite session created")
    print("  4. ✅ Micro-payments: 10 chunks (worker sends 10% → client signs → repeat)")
    print("  5. ✅ Settlement: Channel closed, money moved on-chain")
    print("  6. ✅ Agent B verified payment, did work, returned result")
    print("\nNo humans. No API keys. Just agents working together.")


if __name__ == "__main__":
    main()
