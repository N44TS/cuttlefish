"""
EAS (Ethereum Attestation Service) job reviews.

After a job is completed, the requester (client) creates an on-chain
attestation = "review" of the worker. Recipient = worker address;
attester = requester; requester pays gas. Anyone can query attestations
by recipient (worker wallet) to see reviews. No ETH needed for the worker.
"""

import os
from typing import Optional

from web3 import Web3
from eth_abi import encode

from agentpay.wallet import AgentWallet

# EAS on Sepolia
EAS_SEPOLIA = "0xC2679fBD37d54388Ce493F1DB75320D236e1815e"
SCHEMA_REGISTRY_SEPOLIA = "0x0a7E2Ff54e76B8E6659aedc9103FB21c038050D0"
SEPOLIA_RPCS = [
    os.getenv("SEPOLIA_RPC", "https://ethereum-sepolia-rpc.publicnode.com"),
    "https://rpc.sepolia.org",
    "https://sepolia.infura.io/v3/9aa3d95b3bc440fa88ea12eaa4456161",
]

# Minimal ABI for attest()
EAS_ABI = [
    {
        "inputs": [
            {
                "components": [
                    {"internalType": "bytes32", "name": "schema", "type": "bytes32"},
                    {
                        "components": [
                            {"internalType": "address", "name": "recipient", "type": "address"},
                            {"internalType": "uint64", "name": "expirationTime", "type": "uint64"},
                            {"internalType": "bool", "name": "revocable", "type": "bool"},
                            {"internalType": "bytes32", "name": "refUID", "type": "bytes32"},
                            {"internalType": "bytes", "name": "data", "type": "bytes"},
                            {"internalType": "uint256", "name": "value", "type": "uint256"},
                        ],
                        "internalType": "struct AttestationRequestData",
                        "name": "data",
                        "type": "tuple",
                    },
                ],
                "internalType": "struct AttestationRequest",
                "name": "request",
                "type": "tuple",
            },
        ],
        "name": "attest",
        "outputs": [{"internalType": "bytes32", "name": "", "type": "bytes32"}],
        "stateMutability": "payable",
        "type": "function",
    },
]

# Register a schema on EAS Sepolia (https://sepolia.easscan.org) once. Then either:
# - Set AGENTPAY_EAS_SCHEMA_UID in .env (your own use), or
# - Paste the schema UID below so end users get it by default (no .env needed).
# Example schema: "bytes32 jobId, address requester, address worker, uint256 amountWei, string taskType, bool success"
DEFAULT_JOB_REVIEW_SCHEMA_UID = "0x64cd6993a4837265e24cd43ec55a9095789459d09a57be95240921c5279c8e6e"  # Paste your Sepolia schema UID here (0x...) so end users don't need .env
JOB_RECEIPT_SCHEMA_UID = os.getenv("AGENTPAY_EAS_SCHEMA_UID", "").strip() or DEFAULT_JOB_REVIEW_SCHEMA_UID


def _encode_receipt_data(job_id: str, requester: str, worker: str, amount_usdc: float, task_type: str, success: bool) -> bytes:
    """Encode receipt payload. Schema must match registered schema on EAS."""
    # Simple encoding: job_id (bytes32), requester (address), worker (address), amount (uint256), task_type (string), success (bool)
    job_id_bytes = job_id.encode("utf-8")[:32].ljust(32, b"\x00")  # 32 bytes
    amount_units = int(amount_usdc * 1_000_000)  # 6 decimals
    # EAS attestation data is arbitrary bytes; we use ABI encode for a simple schema
    return encode(
        ["bytes32", "address", "address", "uint256", "string", "bool"],
        [job_id_bytes, Web3.to_checksum_address(requester), Web3.to_checksum_address(worker), amount_units, task_type, success],
    )


def create_job_review(
    job_id: str,
    worker_address: str,
    requester_wallet: AgentWallet,
    amount_usdc: float,
    task_type: str,
    success: bool = True,
    schema_uid_hex: Optional[str] = None,
    rpc_url: Optional[str] = None,
) -> Optional[str]:
    """
    Create an EAS attestation (job review). Requester attests after a successful job.
    Recipient = worker address; attester = requester; requester pays gas.

    Returns attestation tx_hash or None if schema not set or tx failed.
    Prerequisite: Register a schema on EAS Sepolia (sepolia.easscan.org) and set
    AGENTPAY_EAS_SCHEMA_UID or pass schema_uid_hex.
    """
    schema_uid_hex = schema_uid_hex or JOB_RECEIPT_SCHEMA_UID
    if not schema_uid_hex or schema_uid_hex == "0x" + "0" * 64:
        return None
    w3 = None
    if rpc_url:
        w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 30}))
        if not w3.is_connected():
            raise RuntimeError(f"Sepolia RPC not connected: {rpc_url}")
    else:
        w3 = None
        for url in SEPOLIA_RPCS:
            if not url or not url.strip():
                continue
            try:
                w3 = Web3(Web3.HTTPProvider(url.strip(), request_kwargs={"timeout": 15}))
                if w3.is_connected():
                    break
            except Exception:
                continue
        if not w3 or not w3.is_connected():
            raise RuntimeError("Could not connect to any Sepolia RPC. Set SEPOLIA_RPC in .env or check network.")
    schema_uid = bytes.fromhex(schema_uid_hex.replace("0x", "").zfill(64)[-64:])
    data = _encode_receipt_data(
        job_id, requester_wallet.address, worker_address, amount_usdc, task_type, success
    )
    eas = w3.eth.contract(address=Web3.to_checksum_address(EAS_SEPOLIA), abi=EAS_ABI)
    request = (
        schema_uid,
        (
            Web3.to_checksum_address(worker_address),  # recipient = worker (reviews about this worker)
            0,  # expirationTime (0 = no expiration per EAS Common.sol)
            True,  # revocable
            b"\x00" * 32,  # refUID
            data,
            0,  # value
        ),
    )
    # Gas: EAS attest typically needs ~150k–300k; use 400k so RPC eth_call and real tx both succeed
    gas_limit = 400_000
    # Dry-run when possible to surface revert reason; skip if RPC limits call gas
    try:
        eas.functions.attest(request).call(
            {"from": requester_wallet.address, "gas": gas_limit}
        )
    except Exception as dry_err:
        msg = str(dry_err)
        if "out of gas" in msg.lower():
            # RPC often caps eth_call; proceed with real tx (it has its own gas)
            pass
        elif "InvalidSchema" in msg or "schema" in msg.lower():
            raise RuntimeError(
                "EAS attest reverted (InvalidSchema): schema UID not found on this chain. "
                "Register the schema at https://sepolia.easscan.org and use that schema UID."
            ) from dry_err
        elif "InvalidExpirationTime" in msg:
            raise RuntimeError("EAS attest reverted: InvalidExpirationTime.") from dry_err
        elif "InvalidAttestation" in msg:
            raise RuntimeError(
                "EAS attest reverted (InvalidAttestation): resolver or data validation failed."
            ) from dry_err
        else:
            raise RuntimeError(f"EAS attest would revert: {msg}") from dry_err
    try:
        tx = eas.functions.attest(request).build_transaction(
            {
                "from": requester_wallet.address,
                "chainId": 11155111,
                "gas": gas_limit,
                "nonce": w3.eth.get_transaction_count(requester_wallet.address),
            }
        )
    except Exception as e:
        raise RuntimeError(f"EAS build_transaction failed (check schema UID matches EAS Sepolia): {e}") from e
    signed = requester_wallet.account.sign_transaction(tx)
    raw_tx = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction", None)
    if not raw_tx:
        raise RuntimeError("Signed transaction missing raw_transaction (check web3/eth-account version)")
    tx_hash = w3.eth.send_raw_transaction(raw_tx)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    if receipt["status"] != 1:
        raise RuntimeError(
            f"EAS attestation reverted. See tx on Etherscan: https://sepolia.etherscan.io/tx/{tx_hash.hex()}"
        )
    return tx_hash.hex()
