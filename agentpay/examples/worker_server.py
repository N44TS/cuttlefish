"""
Worker: 402 + Yellow. No X-Payment → 402 + Bill. With X-Payment (tx hash) → verify, work, result.

Default: yellow_channel (on-chain). Env: AGENTPAY_WORKER_WALLET or AGENTPAY_WORKER_PRIVATE_KEY.
Run from repo root: python3 agentpay/examples/worker_server.py
"""

import os
import sys
import json
import time
import subprocess
import threading
from pathlib import Path
from typing import Optional, Tuple

# Allow running as script without pip install: add repo root so import agentpay works
if __name__ == "__main__" or "agentpay" not in sys.modules:
    _root = Path(__file__).resolve().parent.parent.parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

from fastapi import FastAPI, Request, Response
from web3 import Web3

from agentpay.schema import Job, Bill, JobResult


def _agentpay_status_path() -> Path:
    p = os.getenv("AGENTPAY_STATUS_FILE", "").strip()
    if p:
        return Path(p)
    return Path(os.path.expanduser("~/.openclaw/workspace/agentpay_status.json"))


def _write_agentpay_status(status: str, task_type: str = "", balance_after: Optional[str] = None, error: Optional[str] = None) -> None:
    """Write status so TUI/skill can report 'am I working / did I just finish?'"""
    path = _agentpay_status_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "status": status,
            "task_type": task_type,
            "balance_after": balance_after,
            "error": error,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass


app = FastAPI()


@app.on_event("startup")
def _print_balance_and_llm_at_startup():
    """So judges can see worker balance and whether the worker has a real brain (LLM)."""
    global _worker_channel_ensured
    _write_agentpay_status("idle")
    bal = _worker_yellow_balance()
    if bal is not None:
        print(f"[WORKER] Balance before any job: {bal}")
    else:
        print("[WORKER] Balance check skipped (Yellow bridge or key unavailable).")
    token = (os.getenv("OPENCLAW_GATEWAY_TOKEN") or os.getenv("OPENCLAW_GATEWAY_PASSWORD") or "").strip()
    if not token:
        print("[WORKER] OpenClaw is required. Run 'agentpay setup-openclaw' and start 'openclaw gateway'.")
        sys.exit(1)
    print("[WORKER] OpenClaw Gateway configured — worker will ask the bot to do real work.")
    # Ensure worker Yellow channel in background so server can accept connections immediately.
    # (Blocking here for up to 120s was preventing the server from listening, causing client "connection refused".)
    if PAYMENT_METHOD in ("yellow", "yellow_full", "yellow_chunked", "yellow_chunked_full") and WORKER_PRIVATE_KEY:
        def _ensure_channel_background():
            global _worker_channel_ensured
            try:
                from agentpay.payments.yellow import ensure_worker_channel
                ensure_worker_channel(WORKER_PRIVATE_KEY)
                _worker_channel_ensured = True
                print("[WORKER] Yellow worker channel ready (lock step done).")
            except Exception as e:
                print("[WORKER] ensure_worker_channel in background failed:", e)
                print("[WORKER] First job may fail at payment. Fix bridge/RPC and retry.")
        t = threading.Thread(target=_ensure_channel_background, daemon=True)
        t.start()

SEPOLIA_RPC = os.getenv("SEPOLIA_RPC", "https://ethereum-sepolia-rpc.publicnode.com")
# USDC Sepolia
USDC = "0x25762231808F040410586504fDF08Df259A2163c"
# Worker's private key (for Yellow sign_state_worker)
WORKER_PRIVATE_KEY = os.getenv("AGENTPAY_WORKER_PRIVATE_KEY")
# Worker's payment address: from AGENTPAY_WORKER_WALLET, or derived from WORKER_PRIVATE_KEY
def _worker_wallet():
    addr = os.getenv("AGENTPAY_WORKER_WALLET")
    if addr and addr != "0xYourWorkerAddress":
        return addr
    if WORKER_PRIVATE_KEY:
        from eth_account import Account
        pk = WORKER_PRIVATE_KEY.strip()
        if not pk.startswith("0x"):
            pk = "0x" + pk
        return Account.from_key(pk).address
    return "0xYourWorkerAddress"

WORKER_WALLET = _worker_wallet()


def _worker_yellow_balance() -> Optional[str]:
    """Get worker's ytest.usd balance for display. Returns formatted string or None if unavailable."""
    if not WORKER_PRIVATE_KEY:
        return None
    try:
        from eth_account import Account
        from agentpay.wallet import AgentWallet
        from agentpay.faucet import check_yellow_balance
        pk = WORKER_PRIVATE_KEY.strip()
        if not pk.startswith("0x"):
            pk = "0x" + pk
        acc = Account.from_key(pk)
        wallet = AgentWallet(account=acc)
        bal, _ = check_yellow_balance(wallet)
        if bal is not None:
            return f"{bal:.2f} ytest.usd"
    except Exception:
        pass
    return None

def _client_address_for_job(requester: str) -> str:
    """Client address for Yellow: env or job requester."""
    addr = os.getenv("AGENTPAY_CLIENT_ADDRESS")
    if addr and addr != "0xYourClientAddress":
        return addr
    return requester or ""

# Client address (for Yellow allocations); fallback is job.requester in submit_job
CLIENT_ADDRESS = os.getenv("AGENTPAY_CLIENT_ADDRESS")
JOB_PRICE_USDC = 0.05
CHAIN_ID = 11155111
# Yellow prize: BOTH session (off-chain) AND channel (on-chain settlement).
# Default: yellow_chunked_full = chunked micropayments (10 chunks) + channel (money moves on-chain).
PAYMENT_METHOD = os.getenv("AGENTPAY_PAYMENT_METHOD", "yellow_chunked_full")

# Lock (on-chain): ensure worker has a channel once when using session payment.
_worker_channel_ensured = False

def _bridge_path() -> Path:
    """Path to bridge.ts. Prefer AGENTPAY_YELLOW_BRIDGE_DIR; else repo layout."""
    env_dir = os.getenv("AGENTPAY_YELLOW_BRIDGE_DIR")
    if env_dir:
        return Path(env_dir).resolve() / "bridge.ts"
    return Path(__file__).resolve().parent.parent.parent / "yellow_test" / "bridge.ts"

ERC20_ABI = [
    {"constant": True, "inputs": [{"name": "account", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
]


def verify_payment_onchain(tx_hash: str, recipient: str, amount_usdc: float) -> tuple[bool, str]:
    """Verify on-chain payment. Returns (ok, reason)."""
    tx_hash = (tx_hash or "").strip()
    if not tx_hash or not tx_hash.startswith("0x") or len(tx_hash) != 66:
        return False, "PAYMENT_INVALID_TX_HASH"
    w3 = Web3(Web3.HTTPProvider(SEPOLIA_RPC, request_kwargs={"timeout": 20}))
    if not w3.is_connected():
        return False, "PAYMENT_RPC_ERROR"
    try:
        for attempt in range(3):
            receipt = w3.eth.get_transaction_receipt(tx_hash)
            if receipt is not None:
                break
            if attempt < 2:
                time.sleep(2)
        if receipt is None:
            return False, "PAYMENT_PENDING"
        if receipt.get("status") != 1:
            return False, "PAYMENT_REVERTED"
        return True, ""
    except Exception as e:
        return False, f"PAYMENT_ERROR:{type(e).__name__}"


def _parse_yellow_proof(proof: str) -> Optional[Tuple[str, int]]:
    """Parse proof into (session_id, version). Accepts yellow|id|ver, yellow_chunked|id|ver, yellow_chunked_full|id|ver|tx."""
    proof = (proof or "").strip()
    if not proof:
        return None
    # yellow| or yellow_chunked| or yellow_chunked_full|session_id|version
    if proof.startswith("yellow|") or proof.startswith("yellow_chunked|") or proof.startswith("yellow_chunked_full|"):
        parts = proof.split("|")
        if len(parts) >= 3:
            try:
                return parts[1].strip(), int(str(parts[2]).split(":")[0])
            except ValueError:
                pass
        return None
    # session:session_id:version:N or session_id:version:N (some proxies strip "session:" or "yellow|")
    if "version" in proof and ":" in proof:
        parts = proof.split(":")
        for i, p in enumerate(parts):
            if p == "version" and i + 1 < len(parts):
                try:
                    ver = int(parts[i + 1])
                    sid = (parts[1] if parts[0] == "session" and i >= 2 else (":".join(parts[:i]) or parts[0])).strip()
                    if not sid:
                        return None
                    if not sid.startswith("0x") and len(sid) >= 40:
                        sid = "0x" + sid
                    return sid, ver
                except (ValueError, IndexError):
                    pass
        return None
    return None


def verify_payment_yellow(
    proof: str, amount_usdc: float, client_address_override: Optional[str] = None
) -> tuple[bool, str]:
    """Verify Yellow session payment and add worker signature. Accepts yellow|id|ver or session:id:version:N."""
    parsed = _parse_yellow_proof(proof)
    if not parsed:
        return False, "PAYMENT_INVALID_YELLOW_PROOF"
    session_id, version = parsed
    if not session_id:
        return False, "PAYMENT_YELLOW_MISSING_SESSION_ID"
    if not WORKER_PRIVATE_KEY:
        return False, "PAYMENT_YELLOW_WORKER_KEY_MISSING"
    client_addr = client_address_override or CLIENT_ADDRESS
    if not client_addr or client_addr == "0xYourClientAddress":
        return False, "PAYMENT_YELLOW_CLIENT_ADDRESS_MISSING"
    amount_units = str(int(amount_usdc * (10**6)))
    sid = session_id if session_id.startswith("0x") else "0x" + session_id
    try:
        bridge_cmd = {
            "command": "sign_state_worker",
            "app_session_id": sid,
            "worker_private_key": WORKER_PRIVATE_KEY,
            "client_address": client_addr,
            "worker_address": WORKER_WALLET,
            "amount": amount_units,
            "version": version,
        }
        result = subprocess.run(
            ["npx", "tsx", str(_bridge_path())],
            input=json.dumps(bridge_cmd),
            capture_output=True,
            text=True,
            cwd=_bridge_path().parent,
            check=True,
            timeout=30,
        )
        response = json.loads(result.stdout)
        if not response.get("success"):
            return False, f"PAYMENT_YELLOW_SIGN_FAILED:{response.get('error', 'Unknown')}"
        return True, ""
    except subprocess.CalledProcessError as e:
        return False, f"PAYMENT_YELLOW_BRIDGE_ERROR:{e.stderr or e.stdout or 'Unknown'}"
    except Exception as e:
        return False, f"PAYMENT_YELLOW_ERROR:{type(e).__name__}:{str(e)}"


def verify_payment_yellow_full(
    proof: str, recipient: str, amount_usdc: float, client_address_for_job: Optional[str] = None
) -> tuple[bool, str]:
    """Verify yellow_full: session (worker signs) + on-chain tx. Proof format: yellow_full|yellow|session_id|version|tx_hash."""
    proof = (proof or "").strip()
    if not proof.startswith("yellow_full|"):
        return False, "PAYMENT_INVALID_YELLOW_FULL"
    parts = proof.split("|")
    if len(parts) < 5:
        return False, "PAYMENT_YELLOW_FULL_BAD_FORMAT"
    session_proof = f"{parts[1]}|{parts[2]}|{parts[3]}"
    tx_hash = parts[4].strip()
    ok, reason = verify_payment_yellow(session_proof, amount_usdc, client_address_for_job)
    if not ok:
        return False, reason
    ok2, reason2 = verify_payment_onchain(tx_hash, recipient, amount_usdc)
    if not ok2:
        return False, reason2
    return True, ""


def verify_payment_yellow_chunked(proof: str, amount_usdc: float) -> tuple[bool, str]:
    """Chunked session: worker already signed each chunk via /sign-state; just validate proof format."""
    parsed = _parse_yellow_proof(proof)
    if not parsed:
        return False, "PAYMENT_INVALID_YELLOW_PROOF"
    session_id, version = parsed
    if not session_id or version < 1:
        return False, "PAYMENT_YELLOW_CHUNKED_BAD_PROOF"
    return True, ""


def verify_payment_yellow_chunked_full(
    proof: str, recipient: str, amount_usdc: float
) -> tuple[bool, str]:
    """Verify yellow_chunked_full: chunked session (already signed per chunk) + on-chain tx."""
    proof = (proof or "").strip()
    if not proof.startswith("yellow_chunked_full|"):
        return False, "PAYMENT_INVALID_YELLOW_CHUNKED_FULL"
    parts = proof.split("|")
    if len(parts) < 4:
        return False, "PAYMENT_YELLOW_CHUNKED_FULL_BAD_FORMAT"
    # Session part: yellow_chunked|session_id|version (worker already signed each chunk)
    session_proof = f"yellow_chunked|{parts[1]}|{parts[2]}"
    tx_hash = parts[3].strip()
    ok, reason = verify_payment_yellow_chunked(session_proof, amount_usdc)
    if not ok:
        return False, reason
    ok2, reason2 = verify_payment_onchain(tx_hash, recipient, amount_usdc)
    if not ok2:
        return False, reason2
    return True, ""


def verify_payment(
    proof: str,
    recipient: str,
    amount_usdc: float,
    payment_method: str,
    client_address_for_job: Optional[str] = None,
) -> tuple[bool, str]:
    """Verify payment. yellow_channel = tx hash. yellow = session. yellow_chunked = session (already signed). yellow_full = session + tx. yellow_chunked_full = chunked session + tx."""
    if payment_method == "yellow_chunked_full" or (proof and proof.strip().startswith("yellow_chunked_full|")):
        return verify_payment_yellow_chunked_full(proof, recipient, amount_usdc)
    if payment_method == "yellow_full" or (proof and proof.strip().startswith("yellow_full|")):
        return verify_payment_yellow_full(proof, recipient, amount_usdc, client_address_for_job)
    if payment_method == "yellow_chunked" or (proof and proof.strip().startswith("yellow_chunked|")):
        return verify_payment_yellow_chunked(proof, amount_usdc)
    if payment_method == "yellow_channel" or (proof and proof.strip().startswith("0x") and len(proof.strip()) == 66):
        return verify_payment_onchain(proof, recipient, amount_usdc)
    if payment_method == "yellow":
        return verify_payment_yellow(proof, amount_usdc, client_address_for_job)
    return verify_payment_onchain(proof, recipient, amount_usdc)


@app.get("/")
def root():
    """Health check: 402 test and load balancers expect 200 here."""
    return {"ok": True, "service": "agentpay-worker", "submit_job": "/submit-job", "sign_state": "/sign-state"}


@app.post("/sign-state")
async def sign_state(request: Request):
    """
    Micro-payments: worker signs a session state update (chunk).
    Body: { "app_session_id": "0x...", "version": 2, "amount": "1000000", "client_address": "0x..." }.
    amount = ytest.usd units (6 decimals). client_address = payer (for allocations).
    """
    if not WORKER_PRIVATE_KEY:
        return Response(status_code=503, content="AGENTPAY_WORKER_PRIVATE_KEY required for sign-state.")
    try:
        body = await request.json()
        app_session_id = body["app_session_id"]
        version = int(body["version"])
        amount = str(body["amount"])
        client_address = body.get("client_address") or CLIENT_ADDRESS or ""
        if not client_address or client_address == "0xYourClientAddress":
            return Response(status_code=400, content="client_address required in body or AGENTPAY_CLIENT_ADDRESS.")
    except (KeyError, TypeError, ValueError) as e:
        return Response(status_code=400, content=f"Invalid body: {e}")
    sid = app_session_id if app_session_id.startswith("0x") else "0x" + app_session_id
    bridge_cmd = {
        "command": "sign_state_worker",
        "app_session_id": sid,
        "worker_private_key": WORKER_PRIVATE_KEY if WORKER_PRIVATE_KEY.startswith("0x") else "0x" + WORKER_PRIVATE_KEY,
        "client_address": client_address,
        "worker_address": WORKER_WALLET,
        "amount": amount,
        "version": version,
    }
    try:
        result = subprocess.run(
            ["npx", "tsx", str(_bridge_path())],
            input=json.dumps(bridge_cmd),
            capture_output=True,
            text=True,
            cwd=_bridge_path().parent,
            check=True,
            timeout=30,
        )
        resp = json.loads(result.stdout)
    except Exception as e:
        return Response(status_code=502, content=f"Bridge error: {e}")
    if not resp.get("success"):
        return Response(status_code=402, content=resp.get("error", "sign_state_worker failed"))
    return {"success": True, "version": version}


@app.post("/submit-job")
async def submit_job(request: Request):
    body = await request.json()
    job = Job(
        job_id=body["job_id"],
        requester=body["requester"],
        task_type=body["task_type"],
        input_data=body.get("input_data", {}),
    )
    payment_proof = request.headers.get("X-Payment")
    if not payment_proof:
        print("[WORKER] Job received. Sending invoice (402).")
        if PAYMENT_METHOD in ("yellow", "yellow_full", "yellow_chunked", "yellow_chunked_full") and (WORKER_WALLET == "0xYourWorkerAddress" or not WORKER_PRIVATE_KEY):
            return Response(status_code=503, content="Yellow session/chunked needs AGENTPAY_WORKER_PRIVATE_KEY.")
        # Worker channel is ensured at startup so we return 402 immediately (no blocking here).
        return Response(
            status_code=402,
            content=Bill(
                amount=JOB_PRICE_USDC,
                recipient=WORKER_WALLET,
                chain_id=CHAIN_ID,
                message=f"Pay {JOB_PRICE_USDC} for {job.task_type}",
                payment_method=PAYMENT_METHOD,
            ).model_dump_json(),
            media_type="application/json",
        )
    
    # Yellow only. Tx hash = channel (on-chain). yellow|... = session.
    payment_method = PAYMENT_METHOD
    if payment_proof:
        p = payment_proof.strip()
        if p.startswith("yellow_chunked_full|"):
            payment_method = "yellow_chunked_full"
        elif p.startswith("yellow_full|"):
            payment_method = "yellow_full"
        elif p.startswith("yellow_chunked|"):
            payment_method = "yellow_chunked"
        elif p.startswith("yellow|") or p.startswith("session:"):
            payment_method = "yellow"
        elif p.startswith("0x") and len(p) == 66:
            payment_method = "yellow_channel"
    client_addr = _client_address_for_job(job.requester)
    print("[WORKER] Payment proof received. Verifying...")
    ok, reason = verify_payment(
        payment_proof, WORKER_WALLET, JOB_PRICE_USDC, payment_method, client_addr
    )
    if not ok:
        debug = (str(payment_proof)[:60] + "..." if len(str(payment_proof)) > 60 else str(payment_proof)) if payment_proof else "(empty)"
        return Response(status_code=402, content=f"{reason} (received: {debug})")
    print("[WORKER] Payment verified. Doing work...")
    _write_agentpay_status("working", task_type=job.task_type)
    bal_before = _worker_yellow_balance()
    if bal_before is not None:
        print(f"[WORKER] Balance (after payment, before job): {bal_before}")
    inp = job.input_data or {}
    query = (inp.get("query") or inp.get("text") or "")
    n = len(query)
    print(f"[WORKER] Sending to OpenClaw: {job.task_type} ({n} chars)")
    try:
        from agentpay.llm_task import do_task
        result = do_task(job.task_type, inp)
        print("[WORKER] OpenClaw completed the task.")
    except RuntimeError as e:
        print(f"[WORKER] OpenClaw required but failed: {e}")
        _write_agentpay_status("idle", error=str(e))
        return Response(status_code=503, content=str(e))
    except Exception as e:
        print(f"[WORKER] Task error: {e}")
        _write_agentpay_status("idle", error=str(e))
        return Response(status_code=503, content=str(e))
    bal_after = _worker_yellow_balance()
    bal_str = str(bal_after) if bal_after is not None else None
    if bal_after is not None:
        print(f"[WORKER] Balance after job: {bal_after}")
    _write_agentpay_status("completed", task_type=job.task_type, balance_after=bal_str)
    print("[WORKER] Done. Returning result.")
    # Show outcome so judges/operators see the bot's answer in the worker terminal
    if result and isinstance(result, str) and result.strip():
        preview = result.strip()[:300] + ("..." if len(result.strip()) > 300 else "")
        print(f"[WORKER] Result (preview): {preview}")
    return {
        "status": "completed",
        "result": result,
        "worker": WORKER_WALLET,
        "attestation_uid": None,
        "error": None,
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", os.getenv("AGENTPAY_PORT", "8000")))
    uvicorn.run(app, host="0.0.0.0", port=port)
