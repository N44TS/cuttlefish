"""
Yellow/Nitrolite payment: Micro-escrow via app sessions.

Uses the TypeScript bridge (yellow_test/bridge.ts) to create sessions,
submit state updates, and close sessions. Returns session proofs for worker verification.
"""

import json
import os
import subprocess
from pathlib import Path
from typing import Optional

from agentpay.schema import Bill
from agentpay.wallet import AgentWallet

# Path to bridge.ts (relative to this file)
BRIDGE_TS = Path(__file__).parent.parent.parent / "yellow_test" / "bridge.ts"

# Yellow uses ytest.usd with 6 decimals (same as USDC)
YELLOW_DECIMALS = 6


def _to_units(amount_usdc: float) -> str:
    """Convert USDC amount to ytest.usd units (6 decimals, as string)."""
    return str(int(amount_usdc * (10**YELLOW_DECIMALS)))


def _call_bridge(command: dict, timeout: int = 35) -> dict:
    """Call the TypeScript bridge and return parsed response."""
    if not BRIDGE_TS.exists():
        raise FileNotFoundError(
            f"Bridge not found at {BRIDGE_TS}. Make sure yellow_test/bridge.ts exists."
        )

    try:
        result = subprocess.run(
            ["npx", "tsx", str(BRIDGE_TS)],
            input=json.dumps(command),
            capture_output=True,
            text=True,
            cwd=BRIDGE_TS.parent,
            check=True,
            timeout=timeout,
        )

        if result.stderr:
            # Log stderr but don't fail (might be debug output)
            pass

        return json.loads(result.stdout)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            f"Bridge execution failed: {e.stderr or e.stdout or 'Unknown error'}"
        )
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Failed to parse bridge response: {e}. Output: {result.stdout}")
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Bridge timeout after {timeout}s")


def pay_yellow(
    bill: Bill,
    wallet: AgentWallet,
    app_session_id: Optional[str] = None,
    worker_address: Optional[str] = None,
) -> str:
    """
    Pay a bill using Yellow/Nitrolite escrow.

    Args:
        bill: Payment bill with amount and recipient
        wallet: Agent wallet (must have private key)
        app_session_id: Existing app session ID (optional, creates new if not provided)
        worker_address: Worker address (uses bill.recipient if not provided)

    Returns:
        Session proof string (format: "session:<session_id>:version:<version>")
        This can be used by the worker to verify payment.

    Note:
        - Creates a new app session if app_session_id not provided
        - Currently supports quorum-1 sessions (single-party operations)
        - submit_state is not yet working (needs debugging)
        - For MVP, you can create_session and return the session_id as proof
    """
    worker_addr = worker_address or bill.recipient
    amount_units = _to_units(bill.amount)

    # Get private key from wallet
    if not hasattr(wallet, "account"):
        raise ValueError("Wallet must have an account for Yellow payments")

    # Extract private key (eth_account format)
    # wallet.account.key is a HexBytes, convert to hex string
    private_key = wallet.account.key.hex()
    if not private_key.startswith("0x"):
        private_key = "0x" + private_key

    # If no session provided, create one
    if not app_session_id:
        create_cmd = {
            "command": "create_session",
            "client_private_key": private_key,
            "worker_address": worker_addr,
            "quorum": 1,  # Single-party for MVP
        }

        response = _call_bridge(create_cmd)
        if not response.get("success"):
            raise RuntimeError(f"Failed to create session: {response.get('error')}")

        session_data = response.get("data", {})
        app_session_id = session_data.get("app_session_id")
        if not app_session_id:
            raise RuntimeError("Bridge returned success but no app_session_id")

        # For MVP: return session creation proof
        # TODO: Once submit_state works, submit payment here
        return f"session:{app_session_id}:created"

    # TODO: Once submit_state is working, submit payment here
    # For now, just return the session ID as proof
    return f"session:{app_session_id}:pending"


def close_yellow_session(
    app_session_id: str,
    wallet: AgentWallet,
    worker_address: str,
) -> bool:
    """
    Close a Yellow app session.

    Args:
        app_session_id: Session ID to close
        wallet: Agent wallet
        worker_address: Worker address

    Returns:
        True if closed successfully
    """
    if not hasattr(wallet, "account"):
        raise ValueError("Wallet must have an account")

    # Extract private key (eth_account format)
    private_key = wallet.account.key.hex()
    if not private_key.startswith("0x"):
        private_key = "0x" + private_key

    close_cmd = {
        "command": "close_session",
        "app_session_id": app_session_id,
        "client_private_key": private_key,
        "worker_address": worker_address,
    }

    response = _call_bridge(close_cmd, timeout=35)
    if not response.get("success"):
        raise RuntimeError(f"Failed to close session: {response.get('error')}")

    return True
