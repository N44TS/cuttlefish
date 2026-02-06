"""
Yellow/Nitrolite payment: sessions and channel (on-chain).

Uses the TypeScript bridge (path from AGENTPAY_YELLOW_BRIDGE_DIR or repo yellow_test/)
to create sessions, submit state, and run channel create/transfer/close.
"""

import json
import os
import subprocess
from pathlib import Path
from typing import Optional

import requests

from agentpay.schema import Bill
from agentpay.wallet import AgentWallet

# Yellow uses ytest.usd with 6 decimals (same as USDC)
YELLOW_DECIMALS = 6


def _bridge_path() -> Path:
    """Path to bridge.ts. Prefer AGENTPAY_YELLOW_BRIDGE_DIR (for pip install); else repo layout."""
    env_dir = os.getenv("AGENTPAY_YELLOW_BRIDGE_DIR")
    if env_dir:
        return Path(env_dir).resolve() / "bridge.ts"
    return Path(__file__).resolve().parent.parent.parent / "yellow_test" / "bridge.ts"


def _check_bridge_setup() -> tuple[bool, str]:
    """
    Check if bridge is set up correctly. Returns (ok, error_message).
    Checks: bridge.ts exists, node_modules exists, npx works.
    """
    bridge_ts = _bridge_path()
    if not bridge_ts.exists():
        env_dir = os.getenv("AGENTPAY_YELLOW_BRIDGE_DIR")
        if env_dir:
            return False, (
                f"Bridge not found at {bridge_ts}. "
                f"Set AGENTPAY_YELLOW_BRIDGE_DIR to a directory containing bridge.ts, "
                f"or clone the repo and run from repo root."
            )
        return False, (
            f"Bridge not found at {bridge_ts}. "
            f"Options: (1) Set AGENTPAY_YELLOW_BRIDGE_DIR=/path/to/yellow_test, "
            f"(2) Clone repo and run from repo root, (3) Copy yellow_test/ from repo to your project."
        )
    
    bridge_dir = bridge_ts.parent
    node_modules = bridge_dir / "node_modules"
    if not node_modules.exists():
        return False, (
            f"Bridge found at {bridge_ts}, but node_modules missing. "
            f"Run: cd {bridge_dir} && npm install"
        )
    
    # Check if npx/tsx is available
    import shutil
    if not shutil.which("npx"):
        return False, "npx not found. Install Node.js (https://nodejs.org/) to use Yellow payments."
    
    return True, ""


def _to_units(amount_usdc: float) -> str:
    """Convert USDC amount to ytest.usd units (6 decimals, as string)."""
    return str(int(amount_usdc * (10**YELLOW_DECIMALS)))


def _call_bridge(command: dict, timeout: int = 35) -> dict:
    """Call the TypeScript bridge and return parsed response."""
    ok, error_msg = _check_bridge_setup()
    if not ok:
        raise FileNotFoundError(error_msg)
    
    bridge_ts = _bridge_path()

    try:
        result = subprocess.run(
            ["npx", "tsx", str(bridge_ts)],
            input=json.dumps(command),
            capture_output=True,
            text=True,
            cwd=bridge_ts.parent,
            check=True,
            timeout=timeout,
        )

        if result.stderr:
            # Log stderr but don't fail (might be debug output)
            pass

        return json.loads(result.stdout)
    except subprocess.CalledProcessError as e:
        err = (e.stderr or e.stdout or str(e)).strip() if e.stderr or e.stdout else "Unknown error"
        raise RuntimeError(f"Bridge execution failed: {err}")
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Failed to parse bridge response: {e}. Output: {result.stdout}")
    except subprocess.TimeoutExpired as e:
        err = f"Bridge timeout after {timeout}s. The channel path needs ensureChannel (~90s) + transferAndClose (~120s)."
        if e.stderr:
            err += f" Bridge stderr: {e.stderr[:500]}"
        raise RuntimeError(err)


def pay_yellow(
    bill: Bill,
    wallet: AgentWallet,
    app_session_id: Optional[str] = None,
    worker_address: Optional[str] = None,
    worker_endpoint: Optional[str] = None,
    **kwargs: object,
) -> str:
    """
    Pay a bill using Yellow/Nitrolite escrow (two-party).

    Args:
        bill: Payment bill with amount and recipient
        wallet: Agent wallet (must have private key)
        app_session_id: Existing app session ID (optional, creates new if not provided)
        worker_address: Worker address (uses bill.recipient if not provided)

    Returns:
        Session proof string (format: "session:<session_id>:version:<version>[:client_signed]")
        Worker must call sign_state_worker with this version to complete payment.

    Flow:
        0. Lock: ensure client has a channel (on-chain).
        1. Handshake: create session (quorum 2) if not provided.
        2. Submit state (client signs) - returns version.
        3. Return proof with version for worker to sign.
    """
    worker_addr = worker_address or bill.recipient
    amount_units = _to_units(bill.amount)

    # Lock (on-chain): ensure client has a channel so funds are in the custody layer.
    try:
        create_channel(wallet, timeout=90)
    except RuntimeError:
        pass  # Channel may already exist; continue to session.

    # Get private key from wallet
    if not hasattr(wallet, "account"):
        raise ValueError("Wallet must have an account for Yellow payments")

    # Extract private key (eth_account format)
    # wallet.account.key is a HexBytes, convert to hex string
    private_key = wallet.account.key.hex()
    if not private_key.startswith("0x"):
        private_key = "0x" + private_key

    # If no session provided, create one (quorum 2 for two-party escrow)
    if not app_session_id:
        create_cmd = {
            "command": "create_session",
            "client_private_key": private_key,
            "worker_address": worker_addr,
            "quorum": 2,  # Two-party escrow
        }

        response = _call_bridge(create_cmd)
        if not response.get("success"):
            raise RuntimeError(f"Failed to create session: {response.get('error')}")

        session_data = response.get("data", {})
        app_session_id = session_data.get("app_session_id")
        if not app_session_id:
            raise RuntimeError("Bridge returned success but no app_session_id")

    # Submit state (client signs)
    submit_cmd = {
        "command": "submit_state",
        "app_session_id": app_session_id,
        "client_private_key": private_key,
        "worker_address": worker_addr,
        "amount": amount_units,
    }

    response = _call_bridge(submit_cmd, timeout=30)
    if not response.get("success"):
        raise RuntimeError(f"Failed to submit state: {response.get('error')}")

    data = response.get("data", {})
    version = data.get("version")
    state_proof = data.get("state_proof")
    # Use pipe separator so header value isn't parsed as URL (session:0x... was being stripped to 0x...).
    # Format: yellow|session_id|version
    if isinstance(state_proof, str) and "|" in state_proof and state_proof.strip().startswith("yellow|"):
        return state_proof.strip()
    return f"yellow|{app_session_id}|{version}"


def pay_yellow_chunked(
    bill: Bill,
    wallet: AgentWallet,
    worker_base_url: Optional[str] = None,
    chunks: int = 3,
    worker_endpoint: Optional[str] = None,
    **kwargs: object,
) -> str:
    """
    Micro-payments (off-chain): chunked signed state updates in one session.
    Lock → Handshake → for each chunk: client submit_state(cumulative amount), worker sign_state (POST /sign-state) → return final proof.
    worker_base_url or worker_endpoint: worker URL (e.g. "http://localhost:8000" or "http://localhost:8000/submit-job").
    """
    base = worker_base_url or (worker_endpoint or "").replace("/submit-job", "").rstrip("/") or "http://localhost:8000"
    worker_addr = bill.recipient
    private_key = wallet.account.key.hex() if hasattr(wallet, "account") else ""
    if not private_key.startswith("0x"):
        private_key = "0x" + private_key
    # Lock
    try:
        create_channel(wallet, timeout=90)
    except RuntimeError:
        pass
    # Handshake: create session (quorum 2)
    print("[CLIENT] Creating session (handshake)...", flush=True)
    create_cmd = {
        "command": "create_session",
        "client_private_key": private_key,
        "worker_address": worker_addr,
        "quorum": 2,
    }
    response = _call_bridge(create_cmd)
    if not response.get("success"):
        raise RuntimeError(f"Failed to create session: {response.get('error')}")
    app_session_id = (response.get("data") or {}).get("app_session_id")
    if not app_session_id:
        raise RuntimeError("Bridge returned success but no app_session_id")
    print(f"[CLIENT] Session created: {app_session_id[:18]}...", flush=True)
    sign_state_url = base.rstrip("/") + "/sign-state"
    version = 1
    print(f"[CLIENT] Starting chunked micropayments ({chunks} chunks)...", flush=True)
    for i in range(1, chunks + 1):
        amount_cumulative = bill.amount * i / chunks
        amount_units = _to_units(amount_cumulative)
        submit_cmd = {
            "command": "submit_state",
            "app_session_id": app_session_id,
            "client_private_key": private_key,
            "worker_address": worker_addr,
            "amount": amount_units,
        }
        print(f"[CLIENT] Submitting chunk {i}/{chunks} (cumulative: ${amount_cumulative:.4f})...", flush=True)
        response = _call_bridge(submit_cmd, timeout=30)
        if not response.get("success"):
            raise RuntimeError(f"Chunk {i} submit_state failed: {response.get('error')}")
        data = response.get("data") or {}
        version = data.get("version", version + 1)
        r = requests.post(
            sign_state_url,
            json={
                "app_session_id": app_session_id,
                "version": version,
                "amount": amount_units,
                "client_address": wallet.address,
            },
            timeout=15,
        )
        if r.status_code != 200:
            raise RuntimeError(f"Chunk {i} worker sign-state failed: {r.status_code} {r.text}")
        print(f"[CLIENT] Chunk {i}/{chunks} signed by worker (version {version})", flush=True)
    print(f"[CLIENT] ✅ Chunked micropayments complete ({chunks} chunks, final version {version})", flush=True)
    # Use yellow_chunked| so worker verifies without calling sign_state_worker again (already signed per chunk).
    return f"yellow_chunked|{app_session_id}|{version}"


def pay_yellow_full(bill: Bill, wallet: AgentWallet, worker_endpoint: Optional[str] = None, **kwargs: object) -> str:
    """
    Pay using both Yellow session (off-chain) and channel (on-chain settlement).
    For HackMoney prize: demonstrates session-based + on-chain settlement in one flow.

    1. Session: create_session + submit_state (client signs). Worker signs on verify.
    2. Channel: create_channel → transfer → close (on-chain tx).

    Returns proof string: yellow_full|yellow|session_id|version|tx_hash
    """
    session_proof = pay_yellow(bill, wallet)
    # Normalize: ensure session part is yellow|id|version (no extra :client_signed in version for worker)
    if "|" in session_proof:
        parts = session_proof.split("|")
        if len(parts) >= 3:
            ver = str(parts[2]).split(":")[0]
            session_proof = f"yellow|{parts[1]}|{ver}"
    tx_hash = pay_yellow_channel(bill, wallet)
    return f"yellow_full|{session_proof}|{tx_hash}"


def pay_yellow_chunked_full(
    bill: Bill,
    wallet: AgentWallet,
    worker_base_url: Optional[str] = None,
    chunks: int = 10,  # Prize doc: "Repeat 10 times"
    worker_endpoint: Optional[str] = None,
    **kwargs: object,
) -> str:
    """
    Micro-payments (chunked) THEN on-chain settlement.
    Prize doc: Worker sends 10% → Client signs "$0.10" → Repeat 10 times → Settlement on-chain.
    
    1. Chunked session: create_session → for each chunk (10): submit_state(cumulative) → worker sign_state
    2. Channel settlement: create_channel → transfer → close (on-chain tx).
    
    Returns: yellow_chunked_full|session_id|version|tx_hash
    """
    # Step 1: Chunked micropayments (off-chain)
    print("[CLIENT] Step 1: Chunked micropayments (off-chain)...", flush=True)
    chunked_proof = pay_yellow_chunked(bill, wallet, worker_base_url, chunks, worker_endpoint, **kwargs)
    # Parse: yellow_chunked|session_id|version
    parts = chunked_proof.split("|")
    if len(parts) < 3:
        raise RuntimeError(f"Invalid chunked proof: {chunked_proof}")
    session_id = parts[1]
    version = parts[2]
    print(f"[CLIENT] ✅ Step 1 complete: Session {session_id[:18]}... ({chunks} chunks, version {version})", flush=True)
    
    # Step 2: On-chain settlement (channel close)
    print("[CLIENT] Step 2: On-chain settlement (channel close)...", flush=True)
    tx_hash = pay_yellow_channel(bill, wallet, worker_endpoint, **kwargs)
    print(f"[CLIENT] ✅ Step 2 complete: Settlement tx {tx_hash[:18]}...", flush=True)
    
    return f"yellow_chunked_full|{session_id}|{version}|{tx_hash}"


def pay_yellow_channel(bill: Bill, wallet: AgentWallet, worker_endpoint: Optional[str] = None, **kwargs: object) -> str:
    """
    Pay via Yellow channel path as three separate steps (4a → 4c → 4d):
    open channel (if needed), transfer to worker, close channel.
    Returns close_tx_hash (on-chain, visible on Sepolia Etherscan).
    Each step has its own timeout so slow RPCs don't fail the whole flow.
    Client needs ytest.usd in unified balance (faucet) and a little Sepolia ETH for gas.
    """
    if not hasattr(wallet, "account"):
        raise ValueError("Wallet must have an account for Yellow channel payments")
    try:
        print("[CLIENT] Opening channel (step 4a)...", flush=True)
        create_channel(wallet, timeout=90)
        print("[CLIENT] Transferring to worker (step 4c)...", flush=True)
        channel_transfer(wallet, bill.recipient, amount=bill.amount, timeout=60)
        print("[CLIENT] Closing channel (step 4d)...", flush=True)
        tx_hash = close_channel(wallet, timeout=90)
    except RuntimeError as e:
        raise RuntimeError(
            f"{e}. "
            "Check you have enough ytest.usd (Yellow faucet) and a little Sepolia ETH for gas."
        )
    if not tx_hash:
        raise RuntimeError("Close channel returned no tx hash (no open channel?)")
    return tx_hash


def close_channel(wallet: AgentWallet, timeout: int = 70) -> Optional[str]:
    """
    Step 4d: Close the Yellow channel (on-chain settlement).

    Prereq: At least one open channel (e.g. after create_channel or channel_transfer).
    Wallet needs a little Sepolia ETH for gas. Returns the close tx hash (Etherscan).

    Returns:
        Tx hash string, or None if no open channel / already closed.
    """
    if not hasattr(wallet, "account"):
        raise ValueError("Wallet must have an account for Yellow")
    private_key = wallet.account.key.hex()
    if not private_key.startswith("0x"):
        private_key = "0x" + private_key
    cmd = {"command": "close_channel", "client_private_key": private_key}
    response = _call_bridge(cmd, timeout=timeout)
    if not response.get("success"):
        raise RuntimeError(f"close_channel failed: {response.get('error')}")
    data = response.get("data") or {}
    return data.get("tx_hash")


def channel_transfer(
    wallet: AgentWallet,
    worker_address: str,
    amount: float = 1.0,
    timeout: int = 35,
) -> bool:
    """
    Step 4c: One off-chain transfer to worker (from unified balance).

    Prereq: Channel exists (run create_channel first). Do not run 4b (resize) —
    in 0.5.x transfer is blocked if any channel has non-zero balance.
    Client needs ytest.usd in unified balance (use Yellow faucet if needed).

    Args:
        wallet: Client wallet (CLIENT_PRIVATE_KEY).
        worker_address: Destination address (0x...).
        amount: Amount in USDC/ytest.usd (float, e.g. 1.0).
        timeout: Bridge timeout in seconds.

    Returns:
        True if transfer succeeded.
    """
    if not hasattr(wallet, "account"):
        raise ValueError("Wallet must have an account for Yellow")
    private_key = wallet.account.key.hex()
    if not private_key.startswith("0x"):
        private_key = "0x" + private_key
    amount_units = _to_units(amount)
    cmd = {
        "command": "channel_transfer",
        "client_private_key": private_key,
        "worker_address": worker_address,
        "amount": amount_units,
    }
    response = _call_bridge(cmd, timeout=timeout)
    if not response.get("success"):
        raise RuntimeError(f"channel_transfer failed: {response.get('error')}")
    return True


def create_channel(wallet: AgentWallet, timeout: int = 70) -> dict:
    """
    Step 4a: Create a Yellow channel (on-chain). No resize, no transfer.
    This is the "Lock" step: funds are locked in the custody/adjudicator layer.

    Wallet must have a little Sepolia ETH for gas. If a channel already exists,
    returns that channel_id with tx_hash=None.

    Returns:
        {"channel_id": "0x...", "tx_hash": "0x..." or None}
    """
    if not hasattr(wallet, "account"):
        raise ValueError("Wallet must have an account for Yellow")
    private_key = wallet.account.key.hex()
    if not private_key.startswith("0x"):
        private_key = "0x" + private_key
    cmd = {"command": "create_channel", "client_private_key": private_key}
    response = _call_bridge(cmd, timeout=timeout)
    if not response.get("success"):
        raise RuntimeError(f"create_channel failed: {response.get('error')}")
    data = response.get("data") or {}
    return {"channel_id": data.get("channel_id"), "tx_hash": data.get("tx_hash")}


def ensure_worker_channel(worker_private_key: str, timeout: int = 70) -> dict:
    """
    Lock (on-chain): Ensure the worker has a channel so both bots have locked.
    Call from worker process at startup when using session payment.
    """
    pk = worker_private_key.strip()
    if not pk.startswith("0x"):
        pk = "0x" + pk
    worker_wallet = AgentWallet.from_key(pk)
    return create_channel(worker_wallet, timeout=timeout)


def steps_1_to_3(wallet: AgentWallet, timeout: int = 25) -> list[dict]:
    """
    Run Yellow steps 1–3 over the bridge: connect → auth → get ledger balances.

    Args:
        wallet: Agent wallet (must have private key; use CLIENT_PRIVATE_KEY).
        timeout: Subprocess timeout in seconds.

    Returns:
        List of balance dicts, e.g. [{"asset": "ytest.usd", "amount": "1000000"}, ...].

    Raises:
        FileNotFoundError: If yellow_test/bridge.ts not found.
        RuntimeError: On bridge failure or timeout.
    """
    if not hasattr(wallet, "account"):
        raise ValueError("Wallet must have an account for Yellow")
    private_key = wallet.account.key.hex()
    if not private_key.startswith("0x"):
        private_key = "0x" + private_key
    cmd = {
        "command": "steps_1_to_3",
        "client_private_key": private_key,
    }
    response = _call_bridge(cmd, timeout=timeout)
    if not response.get("success"):
        raise RuntimeError(f"steps_1_to_3 failed: {response.get('error')}")
    data = response.get("data") or {}
    return data.get("ledger_balances", [])


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
