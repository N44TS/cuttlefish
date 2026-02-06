"""
Optional Circle/Arc payment backend.

If CIRCLE_API_KEY (and optionally CIRCLE_ENTITY_SECRET) is set, use Circle Wallets
and Arc for payments. Else the SDK uses local wallet + Sepolia (pay_onchain).

Full implementation requires Circle Developer account and Circle Wallets API.
See: https://developers.circle.com/wallets, https://docs.arc.network/
"""

import os
from typing import Optional

from agentpay.schema import Bill
from agentpay.wallet import AgentWallet

CIRCLE_API_KEY = "CIRCLE_API_KEY"
CIRCLE_ENTITY_SECRET = "CIRCLE_ENTITY_SECRET"
CIRCLE_WALLET_ID = "CIRCLE_WALLET_ID"  # Optional: specific wallet ID for this agent


def is_circle_configured() -> bool:
    """True if Circle config is present (use Circle Wallets + Arc for payments)."""
    return bool(os.getenv(CIRCLE_API_KEY))


def pay_circle_arc(
    bill: Bill,
    wallet: AgentWallet,
    wallet_id: Optional[str] = None,
    worker_endpoint: Optional[str] = None,
    **kwargs: object,
) -> str:
    """
    Pay a bill using Circle Wallets on Arc. Returns tx_hash or proof for worker to verify.

    Requires CIRCLE_API_KEY (and typically CIRCLE_ENTITY_SECRET) to be set.
    Optional: CIRCLE_WALLET_ID for the agent's Circle wallet; else use wallet_id arg.
    Full implementation requires circle SDK / Circle Wallets API integration.
    """
    if not is_circle_configured():
        raise RuntimeError(
            "Circle is not configured. Set CIRCLE_API_KEY (and CIRCLE_ENTITY_SECRET) "
            "to use Circle Wallets + Arc, or use default pay_onchain (Sepolia)."
        )
    # Stub: full implementation would call Circle Wallets API to create/sign transaction
    # on Arc (e.g. ARC-TESTNET). See developers.circle.com/wallets and docs.arc.network
    raise NotImplementedError(
        "Circle/Arc payment requires Circle Wallets API integration. "
        "For now use pay_onchain (default). Set pay_fn=pay_onchain in request_job."
    )
