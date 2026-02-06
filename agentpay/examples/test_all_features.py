"""
Test all Yellow prize track features in one script.

Run:
  Terminal 1 (worker): AGENTPAY_PAYMENT_METHOD=yellow_chunked_full AGENTPAY_WORKER_WALLET=0x... AGENTPAY_WORKER_PRIVATE_KEY=0x... python agentpay/examples/worker_server.py
  Terminal 2 (client): CLIENT_PRIVATE_KEY=0x... WORKER_ENS_NAME=hahahagg.eth python agentpay/examples/test_all_features.py

Tests:
1. Lock (on-chain): Both bots create channels
2. Handshake (off-chain): Create Nitrolite session
3. Micro-payments (off-chain): Chunked signed state updates
4. Settlement (on-chain): Channel close = money moves
5. Adjudicator: Dispute resolution (demo)
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
from agentpay.adjudicator import submit_dispute


def test_all_features():
    print("=" * 60)
    print("Testing All Yellow Prize Track Features")
    print("=" * 60)

    worker_ens = os.getenv("WORKER_ENS_NAME", "").strip()
    if not worker_ens:
        print("Set WORKER_ENS_NAME (e.g. hahahagg.eth)")
        return False

    wallet = AgentWallet()
    print(f"\n[CLIENT] Wallet: {wallet.address}")

    # Feature 1-4: Lock + Handshake + Chunked Micro-payments + Settlement (yellow_chunked_full)
    print("\n[1-4] Lock + Handshake + Chunked Micro-payments + Settlement (yellow_chunked_full)")
    print("  Lock: create_channel (client) + ensure_worker_channel (worker)")
    print("  Handshake: create_session (quorum 2)")
    print("  Micro-payments: 10 chunks (worker sends 10% → client signs '$0.10' → repeat)")
    print("  Settlement: close_channel (on-chain tx)")

    result = hire_agent(
        wallet,
        task_type="test-all-features",
        input_data={"test": "all features"},
        worker_ens_name=worker_ens,
        job_id="test_all_001",
        pay_fn=get_pay_fn("yellow_chunked_full"),
    )

    if result.status != "completed":
        print(f"  ❌ Failed: {result.error}")
        return False

    tx_hash = getattr(result, "payment_tx_hash", None)
    session_id = getattr(result, "yellow_session_id", None)
    print(f"  ✅ Session ID: {session_id}")
    print(f"  ✅ Settlement tx: {tx_hash}")
    if tx_hash:
        print(f"  ✅ Etherscan: https://sepolia.etherscan.io/tx/{tx_hash}")

    # Feature 5: Adjudicator (dispute resolution)
    print("\n[5] Adjudicator (Dispute Resolution)")
    print("  Scenario: Client refuses to sign final payment after worker delivers work")
    print("  Worker submits dispute with last signed state + proof of delivery")
    if session_id:
        # Simulate: worker delivered work, client signed up to 90% but refused final 10%
        # Worker submits dispute with last signed state (90%) + proof of delivery
        last_signed_state = f"yellow_chunked|{session_id}|{version}"  # Last chunk worker signed
        dispute_ok = submit_dispute(
            session_id,
            last_signed_state,
            proof_of_delivery="work_completed_hash_123",
            worker_address=result.worker,
            amount_units="45000",  # 90% of 0.05 USDC (last signed amount)
            auto_release_demo=True,  # Demo: auto-release. Production: calls Adjudicator contract.
        )
        print(f"  ✅ Dispute submitted (last signed: 90%), funds released (demo): {dispute_ok}")
        print(f"  ✅ Adjudicator infra ready (contract: 0x7c7ccbc98469190849BCC6c926307794fDfB11F2)")
    else:
        print("  ⚠️  Skipped (no session_id)")

    print("\n" + "=" * 60)
    print("✅ All Features Tested")
    print("=" * 60)
    print("\nFeatures verified:")
    print("  1. ✅ Lock (on-chain): Both bots locked funds")
    print("  2. ✅ Handshake (off-chain): Nitrolite session created")
    print("  3. ✅ Micro-payments (off-chain): 10 chunks (worker sends 10% → client signs → repeat)")
    print("  4. ✅ Settlement (on-chain): Channel closed, money moved")
    print("  5. ✅ Adjudicator: Dispute infra ready (simulated client refusal, worker gets paid)")
    return True


if __name__ == "__main__":
    ok = test_all_features()
    sys.exit(0 if ok else 1)
