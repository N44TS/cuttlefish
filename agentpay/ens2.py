"""
ENS registration + provisioning built on the working ens_register_only.py.

Layer 1: Registration (exact copy of ens_register_only.py flow).
Layer 2: Provisioning (set resolver then setText for agentpay.*).

No module-level env load; all functions take a wallet (AgentWallet).
"""

import os
import secrets
import time
from typing import Optional, Tuple

from web3 import Web3

from agentpay.wallet import AgentWallet

# --- Config (same as ens_register_only.py) ---
RPC_URL = os.environ.get("RPC_URL", "https://ethereum-sepolia-rpc.publicnode.com")
ETH_REGISTRAR_CONTROLLER = "0xFED6a969AaA60E4961FCD3EBF1A2e8913ac65B72"
# Resolver at registration: zero (working example). set real resolver in provision step.
REGISTRATION_RESOLVER = "0x0000000000000000000000000000000000000000"

# For provisioning (set resolver + text records)
SEPOLIA_ENS_REGISTRY = "0x00000000000C2E074eC69A0dFb2997BA6C7d2e1e"
SEPOLIA_BASE_REGISTRAR = "0x57f1887a8bf19b14fc0df6fd9b2acc9af147ea85"  # .eth NFT owner; reclaim() sets registry owner
SEPOLIA_NAME_WRAPPER = "0x0635513f179D50A207757E05759CbD106d7dFcE8"  # wrapped names: owner is Name Wrapper; call nameWrapper.setResolver
SEPOLIA_PUBLIC_RESOLVER = "0xE99638b40E4Fff0129D56f03b55b6bbC4BBE49b5"

KEY_CAPABILITIES = "agentpay.capabilities"
KEY_ENDPOINT = "agentpay.endpoint"
KEY_PRICES = "agentpay.prices"

# --- ABIs (from ens_register_only.py) ---
CONTROLLER_ABI = [
    {
        "inputs": [
            {"name": "name", "type": "string"},
            {"name": "owner", "type": "address"},
            {"name": "duration", "type": "uint256"},
            {"name": "secret", "type": "bytes32"},
            {"name": "resolver", "type": "address"},
            {"name": "data", "type": "bytes[]"},
            {"name": "reverseRecord", "type": "bool"},
            {"name": "ownerControlledFuses", "type": "uint16"}
        ],
        "name": "makeCommitment",
        "outputs": [{"name": "", "type": "bytes32"}],
        "stateMutability": "pure",
        "type": "function"
    },
    {
        "inputs": [{"name": "commitment", "type": "bytes32"}],
        "name": "commit",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [
            {"name": "name", "type": "string"},
            {"name": "owner", "type": "address"},
            {"name": "duration", "type": "uint256"},
            {"name": "secret", "type": "bytes32"},
            {"name": "resolver", "type": "address"},
            {"name": "data", "type": "bytes[]"},
            {"name": "reverseRecord", "type": "bool"},
            {"name": "ownerControlledFuses", "type": "uint16"}
        ],
        "name": "register",
        "outputs": [],
        "stateMutability": "payable",
        "type": "function"
    },
    {"inputs": [{"name": "name", "type": "string"}], "name": "available", "outputs": [{"name": "", "type": "bool"}], "stateMutability": "view", "type": "function"},
    {
        "inputs": [{"name": "name", "type": "string"}, {"name": "duration", "type": "uint256"}],
        "name": "rentPrice",
        "outputs": [{"components": [{"name": "base", "type": "uint256"}, {"name": "premium", "type": "uint256"}], "name": "price", "type": "tuple"}],
        "stateMutability": "view",
        "type": "function"
    },
    {"inputs": [], "name": "minCommitmentAge", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "maxCommitmentAge", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"}
]

REGISTRY_ABI = [
    {"constant": True, "inputs": [{"name": "node", "type": "bytes32"}], "name": "resolver", "outputs": [{"name": "", "type": "address"}], "type": "function"},
    {"constant": True, "inputs": [{"name": "node", "type": "bytes32"}], "name": "owner", "outputs": [{"name": "", "type": "address"}], "type": "function"},
    {"constant": False, "inputs": [{"name": "node", "type": "bytes32"}, {"name": "resolver", "type": "address"}], "name": "setResolver", "outputs": [], "type": "function"},
]

RESOLVER_ABI = [
    {"constant": True, "inputs": [{"name": "node", "type": "bytes32"}, {"name": "key", "type": "string"}], "name": "text", "outputs": [{"name": "", "type": "string"}], "type": "function"},
    {"constant": False, "inputs": [{"name": "node", "type": "bytes32"}, {"name": "key", "type": "string"}, {"name": "value", "type": "string"}], "name": "setText", "outputs": [], "type": "function"},
]

# Base Registrar: for .eth names, registry.owner(node) may be Base Registrar; NFT owner calls reclaim(id, addr) to become registry owner
BASE_REGISTRAR_ABI = [
    {"inputs": [{"name": "id", "type": "uint256"}, {"name": "owner", "type": "address"}], "name": "reclaim", "outputs": [], "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [{"name": "tokenId", "type": "uint256"}], "name": "ownerOf", "outputs": [{"name": "", "type": "address"}], "stateMutability": "view", "type": "function"},
]

# Name Wrapper: when registry.owner(node) is Name Wrapper, name is wrapped; call nameWrapper.setResolver (wallet must own wrapped name)
NAME_WRAPPER_ABI = [
    {"inputs": [{"name": "node", "type": "bytes32"}, {"name": "resolver", "type": "address"}], "name": "setResolver", "outputs": [], "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [{"name": "account", "type": "address"}, {"name": "id", "type": "uint256"}], "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
]


def namehash(name: str) -> bytes:
    """ENS namehash for e.g. 'label.eth'."""
    if not name:
        return b"\x00" * 32
    from eth_utils import keccak, to_bytes
    labels = [l for l in name.split(".") if l]
    if not labels:
        return b"\x00" * 32
    node = b"\x00" * 32
    for label in reversed(labels):
        label_hash = keccak(to_bytes(text=label))
        node = keccak(node + label_hash)
    return node


def _connect(rpc: Optional[str] = None) -> Web3:
    url = rpc or RPC_URL
    w3 = Web3(Web3.HTTPProvider(url))
    if not w3.is_connected():
        raise ConnectionError(f"Failed to connect to RPC: {url}")
    return w3


def _wait_receipt(w3: Web3, tx_hash, timeout: int = 300):
    """Wait for tx receipt; longer timeout for Sepolia; clear error on timeout."""
    try:
        return w3.eth.wait_for_transaction_receipt(tx_hash, timeout=timeout)
    except Exception as e:
        tx_hex = tx_hash.hex() if hasattr(tx_hash, "hex") else str(tx_hash)
        if "TimeExhausted" in type(e).__name__ or "Timeout" in type(e).__name__:
            raise RuntimeError(
                f"Transaction not confirmed within {timeout}s. "
                f"Check status: https://sepolia.etherscan.io/tx/{tx_hex}"
            ) from e
        raise


# --- Layer 1: Registration (ens_register_only.py flow) ---

def register_ens_name(
    wallet: AgentWallet,
    label: str,
    duration_seconds: int = 31536000,
    set_reverse_record: bool = False,
    rpc_url: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    Register a .eth name on Sepolia. Exact same flow as ens_register_only.py.
    Returns (True, "label.eth") or (False, error_message).
    """
    label = label.strip().lower().removesuffix(".eth")
    if not label or len(label) < 3:
        return False, "Label must be at least 3 characters."

    w3 = _connect(rpc_url)
    controller = w3.eth.contract(
        address=Web3.to_checksum_address(ETH_REGISTRAR_CONTROLLER),
        abi=CONTROLLER_ABI,
    )
    owner_address = wallet.address

    if not controller.functions.available(label).call():
        return False, f"'{label}.eth' is not available."

    price = controller.functions.rentPrice(label, duration_seconds).call()
    total_price = price[0] + price[1]
    total_price_with_buffer = int(total_price * 1.05)

    balance = w3.eth.get_balance(owner_address)
    if balance < total_price_with_buffer + 500_000 * 30 * 10**9:
        return False, f"Insufficient balance. Need ~{(total_price_with_buffer + 500_000 * 30 * 10**9) / 10**18:.4f} ETH (Sepolia faucet: https://sepoliafaucet.com)."

    secret = secrets.token_bytes(32)
    commitment = controller.functions.makeCommitment(
        label,
        Web3.to_checksum_address(owner_address),
        duration_seconds,
        secret,
        Web3.to_checksum_address(REGISTRATION_RESOLVER),
        [],
        set_reverse_record,
        0,
    ).call()

    pk = wallet.account.key.hex()
    if not pk.startswith("0x"):
        pk = "0x" + pk

    # Commit
    commit_tx = controller.functions.commit(commitment).build_transaction({
        "from": owner_address,
        "nonce": w3.eth.get_transaction_count(owner_address),
        "gas": 100000,
        "gasPrice": w3.eth.gas_price,
    })
    signed_commit = w3.eth.account.sign_transaction(commit_tx, pk)
    commit_tx_hash = w3.eth.send_raw_transaction(signed_commit.raw_transaction)
    commit_receipt = w3.eth.wait_for_transaction_receipt(commit_tx_hash)
    if commit_receipt.get("status") != 1:
        return False, "Commit transaction failed."

    min_age = controller.functions.minCommitmentAge().call()
    wait_time = min_age + 5
    time.sleep(wait_time)

    # Register
    register_tx = controller.functions.register(
        label,
        Web3.to_checksum_address(owner_address),
        duration_seconds,
        secret,
        Web3.to_checksum_address(REGISTRATION_RESOLVER),
        [],
        set_reverse_record,
        0,
    ).build_transaction({
        "from": owner_address,
        "value": total_price_with_buffer,
        "nonce": w3.eth.get_transaction_count(owner_address),
        "gas": 300000,
        "gasPrice": w3.eth.gas_price,
    })
    signed_register = w3.eth.account.sign_transaction(register_tx, pk)
    register_tx_hash = w3.eth.send_raw_transaction(signed_register.raw_transaction)
    register_receipt = w3.eth.wait_for_transaction_receipt(register_tx_hash)
    if register_receipt.get("status") != 1:
        return False, "Register transaction failed."

    return True, f"{label}.eth"


# --- Layer 2: Provisioning (set resolver + setText) ---

def _label_to_token_id(label: str) -> int:
    """Token ID for .eth name in Base Registrar = uint256(keccak256(label))."""
    from eth_utils import keccak, to_bytes
    return int.from_bytes(keccak(to_bytes(text=label)), "big")


def provision_ens_identity(
    wallet: AgentWallet,
    ens_name: str,
    capabilities: str,
    endpoint: str = "",
    prices: str = "N/A",
    rpc_url: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    Set resolver (if currently zero) then set agentpay.* text records.
    Wallet must own the ENS name (or own the .eth NFT and we reclaim first).
    Returns (True, ens_name) or (False, error_message).
    """
    w3 = _connect(rpc_url)
    ens_name = ens_name.strip().lower().removesuffix(".eth") + ".eth"  # normalize
    node = namehash(ens_name)
    registry = w3.eth.contract(
        address=Web3.to_checksum_address(SEPOLIA_ENS_REGISTRY),
        abi=REGISTRY_ABI,
    )
    owner = registry.functions.owner(node).call()
    if not owner:
        return False, f"Name '{ens_name}' has no owner in registry."

    # Who can call setResolver: registry owner (wallet) or Name Wrapper (wallet must own wrapped name)
    use_registry_for_set_resolver = True
    if owner.lower() != wallet.address.lower():
        name_wrapper_addr = Web3.to_checksum_address(SEPOLIA_NAME_WRAPPER)
        if owner.lower() == name_wrapper_addr.lower():
            # Wrapped name: wallet must own the wrapped NFT (ERC-1155); we call nameWrapper.setResolver
            name_wrapper = w3.eth.contract(address=name_wrapper_addr, abi=NAME_WRAPPER_ABI)
            token_id = int.from_bytes(node, "big")  # Name Wrapper uses namehash as tokenId
            try:
                balance = name_wrapper.functions.balanceOf(wallet.address, token_id).call()
            except Exception:
                return False, f"Name '{ens_name}' not found on Name Wrapper (wrong chain?)."
            if balance < 1:
                return False, f"Wallet does not own the wrapped name '{ens_name}'."
            use_registry_for_set_resolver = False
        else:
            # Registry owner can be Base Registrar; NFT owner must reclaim to become registry owner
            base_registrar_addr = Web3.to_checksum_address(SEPOLIA_BASE_REGISTRAR)
            if owner.lower() == base_registrar_addr.lower():
                label = ens_name.removesuffix(".eth")
                token_id = _label_to_token_id(label)
                base_registrar = w3.eth.contract(address=base_registrar_addr, abi=BASE_REGISTRAR_ABI)
                try:
                    nft_owner = base_registrar.functions.ownerOf(token_id).call()
                except Exception:
                    return False, f"Name '{ens_name}' not found on Base Registrar (wrong chain or not .eth?)."
                if nft_owner.lower() != wallet.address.lower():
                    return False, f"Wallet does not own the .eth NFT for '{ens_name}' (owner: {nft_owner})."
                pk = wallet.account.key.hex()
                if not pk.startswith("0x"):
                    pk = "0x" + pk
                reclaim_tx = base_registrar.functions.reclaim(token_id, Web3.to_checksum_address(wallet.address)).build_transaction({
                    "from": wallet.address,
                    "nonce": w3.eth.get_transaction_count(wallet.address),
                    "gas": 100000,
                    "gasPrice": w3.eth.gas_price,
                })
                signed = w3.eth.account.sign_transaction(reclaim_tx, pk)
                tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
                _wait_receipt(w3, tx_hash)
            else:
                return False, f"Wallet does not own '{ens_name}' (registry owner: {owner})."

    try:
        resolver_addr = registry.functions.resolver(node).call()
        if not resolver_addr or resolver_addr == "0x0000000000000000000000000000000000000000":
            if use_registry_for_set_resolver:
                set_resolver_contract = registry
            else:
                set_resolver_contract = w3.eth.contract(address=Web3.to_checksum_address(SEPOLIA_NAME_WRAPPER), abi=NAME_WRAPPER_ABI)
            tx = set_resolver_contract.functions.setResolver(node, Web3.to_checksum_address(SEPOLIA_PUBLIC_RESOLVER)).build_transaction({
                "from": wallet.address,
                "nonce": w3.eth.get_transaction_count(wallet.address),
                "gas": 100000,
                "gasPrice": w3.eth.gas_price,
            })
            pk = wallet.account.key.hex()
            if not pk.startswith("0x"):
                pk = "0x" + pk
            signed = w3.eth.account.sign_transaction(tx, pk)
            set_resolver_tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
            _wait_receipt(w3, set_resolver_tx_hash)
            resolver_addr = SEPOLIA_PUBLIC_RESOLVER

        resolver = w3.eth.contract(
            address=Web3.to_checksum_address(resolver_addr),
            abi=RESOLVER_ABI,
        )
        pk = wallet.account.key.hex()
        if not pk.startswith("0x"):
            pk = "0x" + pk

        for key, value in [
            (KEY_CAPABILITIES, capabilities),
            (KEY_ENDPOINT, endpoint),
            (KEY_PRICES, prices),
        ]:
            tx = resolver.functions.setText(node, key, value).build_transaction({
                "from": wallet.address,
                "nonce": w3.eth.get_transaction_count(wallet.address),
                "gas": 80000,
                "gasPrice": w3.eth.gas_price,
            })
            signed = w3.eth.account.sign_transaction(tx, pk)
            tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
            _wait_receipt(w3, tx_hash)
    except RuntimeError as e:
        return False, str(e)

    return True, ens_name
