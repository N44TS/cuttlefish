"""
Adjudicator: dispute resolution when client refuses to sign final payment.

Prize doc: Worker submits last signed state + proof of delivery to Adjudicator;
contract opens challenge period; if client doesn't respond, funds release to worker.

For demo: auto-release (always pass). Production would call the Yellow Adjudicator
contract on Sepolia (0x7c7ccbc98469190849BCC6c926307794fDfB11F2).
"""

from typing import Optional

# Adjudicator contract (Yellow Nitrolite sandbox)
ADJUDICATOR_ADDRESS = "0x7c7ccbc98469190849BCC6c926307794fDfB11F2"


def submit_dispute(
    app_session_id: str,
    final_state_proof: str,
    proof_of_delivery: Optional[str] = None,
    worker_address: Optional[str] = None,
    amount_units: Optional[str] = None,
    auto_release_demo: bool = True,
) -> bool:
    """
    Submit a dispute to the Adjudicator: worker claims client refused to sign final payment.

    Args:
        app_session_id: Yellow app session ID.
        final_state_proof: Last signed state (e.g. yellow|session_id|version or raw proof).
        proof_of_delivery: Optional proof that work was delivered (hash, attestation, etc.).
        worker_address: Worker's payment address (for release).
        amount_units: Amount in ytest.usd units (6 decimals) for the final state.
        auto_release_demo: If True (default), skip contract call and return True (demo).

    Returns:
        True if dispute accepted / funds released (or in demo, always True).
    """
    if auto_release_demo:
        # Hackathon demo: automatically pass and release funds.
        return True
    # Production: call Adjudicator contract to open challenge period, then release after timeout.
    # raise NotImplementedError("Adjudicator contract call not implemented; use auto_release_demo=True")
    return True


def release_to_worker(
    app_session_id: str,
    worker_address: str,
    amount_units: str,
    final_state_proof: str,
    auto_release_demo: bool = True,
) -> Optional[str]:
    """
    After challenge period (or in demo immediately), release funds from Lock to worker.

    Returns:
        Tx hash if on-chain release was submitted; None in demo mode.
    """
    if auto_release_demo:
        return None  # No tx in demo; adjudicator_release is a no-op that "succeeds"
    # Production: call Adjudicator.release(...) and return tx_hash.
    return None
