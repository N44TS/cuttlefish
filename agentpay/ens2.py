"""
ENS registration + provisioning built on the working ens_register_only.py.

Layer 1: Registration (exact copy of ens_register_only.py flow).
Layer 2: Provisioning (set resolver then setText for agentpay.*).

No module-level env load; all functions take a wallet (AgentWallet).
"""

import os
import secrets
import time
from typing import Dict, List, Optional, Tuple

from web3 import Web3
from web3.exceptions import TransactionNotFound

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
KEY_REVIEW = "agentpay.review"  # EAS attestation UID or tx hash — link review to ENS for prize

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


def _wait_receipt(w3: Web3, tx_hash, timeout: int = 300, description: str = "Transaction"):
    """Wait for tx receipt; longer timeout for Sepolia; clear error on timeout."""
    tx_hex = tx_hash.hex() if hasattr(tx_hash, "hex") else str(tx_hash)
    print(f"⏳ {description} sent: https://sepolia.etherscan.io/tx/{tx_hex}")
    
    # First check if transaction exists (may take a moment to propagate)
    print(f"   Verifying transaction was broadcast...", end="", flush=True)
    tx_found = False
    for i in range(10):  # Check for up to 10 seconds
        try:
            tx_info = w3.eth.get_transaction(tx_hash)
            if tx_info:
                tx_found = True
                print(f"\n   ✅ Transaction found on network")
                break
        except TransactionNotFound:
            time.sleep(1)
            print(".", end="", flush=True)
    
    if not tx_found:
        print(f"\n   ⚠️  Transaction not found on network yet (may still be propagating)")
        print(f"   Check manually: https://sepolia.etherscan.io/tx/{tx_hex}")
    
    print(f"   Waiting for confirmation (this can take 30-120 seconds)...", end="", flush=True)
    
    start_time = time.time()
    last_update = start_time
    step = 3  # Check every 3 seconds
    
    # Use polling approach similar to flow.py but with progress feedback
    max_iterations = timeout // step
    for i in range(max_iterations):
        try:
            receipt = w3.eth.get_transaction_receipt(tx_hash)
            if receipt is not None:
                elapsed = int(time.time() - start_time)
                status = receipt.get("status")
                if status == 1:
                    print(f"\n✅ {description} confirmed after {elapsed}s")
                    return receipt
                else:
                    # Transaction failed
                    elapsed = int(time.time() - start_time)
                    print(f"\n❌ {description} failed after {elapsed}s (status: {status})")
                    raise RuntimeError(
                        f"Transaction failed with status {status}. "
                        f"Check status: https://sepolia.etherscan.io/tx/{tx_hex}"
                    )
        except TransactionNotFound:
            # Transaction not indexed yet, keep waiting
            elapsed = int(time.time() - start_time)
            if elapsed > timeout:
                print(f"\n❌ {description} timeout after {elapsed}s")
                raise RuntimeError(
                    f"Transaction not confirmed within {timeout}s. "
                    f"Check status: https://sepolia.etherscan.io/tx/{tx_hex}"
                )
            # Update progress every 10 seconds
            if elapsed - int(last_update) >= 10:
                print(f".", end="", flush=True)
                last_update = elapsed
            time.sleep(step)
        except Exception as e:
            # Other exceptions (connection errors, etc.) - re-raise immediately
            elapsed = int(time.time() - start_time)
            print(f"\n❌ {description} error after {elapsed}s: {e}")
            raise
    
    # Timeout reached
    elapsed = int(time.time() - start_time)
    print(f"\n❌ {description} timeout after {elapsed}s")
    raise RuntimeError(
        f"Transaction not confirmed within {timeout}s. "
        f"Check status: https://sepolia.etherscan.io/tx/{tx_hex}"
    )


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
    print(f"\n📝 Starting ENS registration for '{label}.eth'...")
    print("   (Full registration typically takes about 2.5 minutes.)")
    
    label = label.strip().lower().removesuffix(".eth")
    if not label or len(label) < 3:
        return False, "Label must be at least 3 characters."

    print("🔌 Connecting to Sepolia RPC...")
    w3 = _connect(rpc_url)
    print("✅ Connected")
    
    controller = w3.eth.contract(
        address=Web3.to_checksum_address(ETH_REGISTRAR_CONTROLLER),
        abi=CONTROLLER_ABI,
    )
    owner_address = wallet.address

    print(f"🔍 Checking if '{label}.eth' is available...")
    if not controller.functions.available(label).call():
        return False, f"'{label}.eth' is not available."
    print("✅ Name is available")

    print("💰 Calculating registration cost...")
    price = controller.functions.rentPrice(label, duration_seconds).call()
    total_price = price[0] + price[1]
    total_price_with_buffer = int(total_price * 1.05)
    eth_cost = total_price_with_buffer / 10**18
    print(f"   Cost: ~{eth_cost:.6f} ETH")

    balance = w3.eth.get_balance(owner_address)
    balance_eth = balance / 10**18
    needed = (total_price_with_buffer + 500_000 * 30 * 10**9) / 10**18
    print(f"   Wallet balance: {balance_eth:.6f} ETH")
    if balance < total_price_with_buffer + 500_000 * 30 * 10**9:
        return False, f"Insufficient balance. Need ~{needed:.4f} ETH (Sepolia faucet: https://sepoliafaucet.com)."
    print("✅ Sufficient balance")

    print("🔐 Generating commitment secret...")
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
    print("✅ Commitment prepared")

    # Commit - RESTORED TO WORKING PATTERN
    print("\n📤 Step 1/2: Committing registration...")
    commit_tx = controller.functions.commit(commitment).build_transaction({
        "from": owner_address,
        "nonce": w3.eth.get_transaction_count(owner_address, "pending"),
        "gas": 100000,
        "gasPrice": w3.eth.gas_price,
    })
    # Use w3.eth.account.sign_transaction like working version
    pk = wallet.account.key.hex()
    signed_commit = w3.eth.account.sign_transaction(commit_tx, pk)
    # Handle both web3.py versions: rawTransaction (old) or raw_transaction (new)
    if hasattr(signed_commit, 'raw_transaction'):
        raw_tx = signed_commit.raw_transaction
    elif hasattr(signed_commit, 'rawTransaction'):
        raw_tx = signed_commit.rawTransaction
    else:
        raise RuntimeError("Signed transaction missing raw transaction data (neither raw_transaction nor rawTransaction found)")
    
    # Ensure it's bytes (HexBytes is fine, send_raw_transaction accepts it)
    # But convert to bytes if needed for compatibility
    if hasattr(raw_tx, '__bytes__'):
        raw_tx_bytes = bytes(raw_tx)
    elif isinstance(raw_tx, bytes):
        raw_tx_bytes = raw_tx
    else:
        raw_tx_bytes = bytes(raw_tx)
    
    commit_tx_hash = w3.eth.send_raw_transaction(raw_tx_bytes)
    commit_receipt = w3.eth.wait_for_transaction_receipt(commit_tx_hash, timeout=300)
    if commit_receipt.get("status") != 1:
        return False, "Commit transaction failed."

    min_age = controller.functions.minCommitmentAge().call()
    wait_time = min_age + 5
    print(f"\n⏳ Waiting {wait_time}s for commitment to mature (ENS requirement)...")
    for i in range(wait_time):
        if i % 10 == 0 and i > 0:
            print(f"   {i}/{wait_time}s...", end="\r", flush=True)
        time.sleep(1)
    print(f"   {wait_time}/{wait_time}s ✅")

    # Register - RESTORED TO WORKING PATTERN
    print("\n📤 Step 2/2: Registering ENS name...")
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
        "nonce": w3.eth.get_transaction_count(owner_address, "pending"),
        "gas": 300000,
        "gasPrice": w3.eth.gas_price,
    })
    # Use w3.eth.account.sign_transaction like working version
    signed_register = w3.eth.account.sign_transaction(register_tx, pk)
    # Handle both web3.py versions: rawTransaction (old) or raw_transaction (new)
    # Try raw_transaction first (newer web3.py), then rawTransaction (older)
    if hasattr(signed_register, 'raw_transaction'):
        raw_tx = signed_register.raw_transaction
    elif hasattr(signed_register, 'rawTransaction'):
        raw_tx = signed_register.rawTransaction
    else:
        raise RuntimeError("Signed transaction missing raw transaction data (neither raw_transaction nor rawTransaction found)")
    
    # Ensure it's bytes (HexBytes is fine, send_raw_transaction accepts it)
    # But convert to bytes if needed for compatibility
    if hasattr(raw_tx, '__bytes__'):
        raw_tx_bytes = bytes(raw_tx)
    elif isinstance(raw_tx, bytes):
        raw_tx_bytes = raw_tx
    else:
        raw_tx_bytes = bytes(raw_tx)
    
    print(f"   Sending registration transaction...", flush=True)
    try:
        register_tx_hash = w3.eth.send_raw_transaction(raw_tx_bytes)
        print(f"   ✅ Tx hash: {register_tx_hash.hex()}", flush=True)
        print(f"   ⏳ Waiting for confirmation (timeout: 300s)...", flush=True)
        register_receipt = w3.eth.wait_for_transaction_receipt(register_tx_hash, timeout=300)
        print(f"   ✅ Transaction confirmed (block: {register_receipt.get('blockNumber')})", flush=True)
    except Exception as e:
        print(f"   ❌ Error sending/waiting for transaction: {e}", flush=True)
        raise
    if register_receipt.get("status") != 1:
        return False, "Register transaction failed."

    print(f"\n🎉 Successfully registered '{label}.eth'!")
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
    print(f"\n⚙️  Provisioning ENS identity for '{ens_name}'...")
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
                reclaim_tx = base_registrar.functions.reclaim(token_id, Web3.to_checksum_address(wallet.address)).build_transaction({
                    "from": wallet.address,
                    "chainId": w3.eth.chain_id,  # CRITICAL: Include chainId (EIP-155)
                    "gas": 100000,
                    "nonce": w3.eth.get_transaction_count(wallet.address, "pending"),
                })
                print("🔓 Reclaiming ownership from Base Registrar...")
                signed = wallet.account.sign_transaction(reclaim_tx)
                raw_tx = getattr(signed, 'raw_transaction', None) or getattr(signed, 'rawTransaction', None)
                if raw_tx is None:
                    raise RuntimeError("Signed transaction missing raw transaction data")
                tx_hash = w3.eth.send_raw_transaction(raw_tx)
                _wait_receipt(w3, tx_hash, description="Reclaim ownership")
            else:
                return False, f"Wallet does not own '{ens_name}' (registry owner: {owner})."

    try:
        resolver_addr = registry.functions.resolver(node).call()
        if not resolver_addr or resolver_addr == "0x0000000000000000000000000000000000000000":
            print("🔧 Setting resolver...")
            if use_registry_for_set_resolver:
                # Use registry.setResolver (wallet owns the name directly)
                tx = registry.functions.setResolver(node, Web3.to_checksum_address(SEPOLIA_PUBLIC_RESOLVER)).build_transaction({
                    "from": wallet.address,
                    "chainId": w3.eth.chain_id,  # CRITICAL: Include chainId (EIP-155)
                    "gas": 100000,
                    "nonce": w3.eth.get_transaction_count(wallet.address, "pending"),
                })
            else:
                # Use Name Wrapper (name is wrapped)
                name_wrapper = w3.eth.contract(address=Web3.to_checksum_address(SEPOLIA_NAME_WRAPPER), abi=NAME_WRAPPER_ABI)
                tx = name_wrapper.functions.setResolver(node, Web3.to_checksum_address(SEPOLIA_PUBLIC_RESOLVER)).build_transaction({
                    "from": wallet.address,
                    "chainId": w3.eth.chain_id,  # CRITICAL: Include chainId (EIP-155)
                    "gas": 100000,
                    "nonce": w3.eth.get_transaction_count(wallet.address, "pending"),
                })
            
            # Use wallet.account.sign_transaction (matches working ens.py)
            signed = wallet.account.sign_transaction(tx)
            raw_tx = getattr(signed, 'raw_transaction', None) or getattr(signed, 'rawTransaction', None)
            if raw_tx is None:
                raise RuntimeError("Signed transaction missing raw transaction data")
            set_resolver_tx_hash = w3.eth.send_raw_transaction(raw_tx)
            _wait_receipt(w3, set_resolver_tx_hash, timeout=300, description="Set resolver")
            
            # Verify resolver was set
            time.sleep(2)  # Brief wait for state to update
            resolver_addr = registry.functions.resolver(node).call()
            if not resolver_addr or resolver_addr == "0x0000000000000000000000000000000000000000":
                return False, "Resolver was not set after transaction confirmed. Check transaction status."
            print("✅ Resolver set successfully")
        else:
            print("✅ Resolver already set")

        resolver = w3.eth.contract(
            address=Web3.to_checksum_address(resolver_addr),
            abi=RESOLVER_ABI,
        )

        print("📝 Setting text records...")
        # Always set endpoint (required), set capabilities and prices if provided
        records_to_set = []
        if endpoint:
            records_to_set.append((KEY_ENDPOINT, endpoint))
        if capabilities:
            records_to_set.append((KEY_CAPABILITIES, capabilities))
        if prices:  # Set prices if provided (even if "N/A" - that's a valid value)
            records_to_set.append((KEY_PRICES, prices))
        
        if not records_to_set:
            return False, "No records to set (endpoint is required)"
        
        for i, (key, value) in enumerate(records_to_set, 1):
            print(f"   [{i}/{len(records_to_set)}] Setting {key}...")
            # Use same pattern as working ens.py: chainId, wallet.account.sign_transaction
            tx = resolver.functions.setText(node, key, value).build_transaction({
                "from": wallet.address,
                "chainId": w3.eth.chain_id,  # CRITICAL: Include chainId (EIP-155)
                "gas": 80000,
                "nonce": w3.eth.get_transaction_count(wallet.address, "pending"),
            })
            # Use wallet.account.sign_transaction (matches working ens.py)
            signed = wallet.account.sign_transaction(tx)
            raw_tx = getattr(signed, 'raw_transaction', None) or getattr(signed, 'rawTransaction', None)
            if raw_tx is None:
                raise RuntimeError("Signed transaction missing raw transaction data")
            tx_hash = w3.eth.send_raw_transaction(raw_tx)
            _wait_receipt(w3, tx_hash, timeout=300, description=f"Set {key}")
    except RuntimeError as e:
        return False, str(e)

    print(f"\n✅ Successfully provisioned '{ens_name}'")
    return True, ens_name


def set_review_record(ens_name: str, attestation_tx_or_uid: str, wallet: "AgentWallet", rpc_url: Optional[str] = None, mainnet: bool = False) -> bool:
    """
    Set agentpay.review on an ENS name to the EAS attestation tx (or UID).
    Links EAS review to ENS for prize. Caller (wallet) must own the ENS name.
    Returns True if set, False if resolver missing or tx failed.
    """
    rpc_urls = [rpc_url] if rpc_url else (MAINNET_RPCS if mainnet else SEPOLIA_RPCS)
    w3 = _connect_multiple(rpc_urls)
    registry = w3.eth.contract(address=Web3.to_checksum_address(SEPOLIA_ENS_REGISTRY if not mainnet else "0x00000000000C2E074eC69A0dFb2997BA6C7d2e1e"), abi=REGISTRY_ABI)
    n = ens_name.strip()
    n = n if n.endswith(".eth") else (n.removesuffix(".eth").strip() + ".eth")
    node = namehash(n)
    try:
        resolver_addr = registry.functions.resolver(node).call()
        if not resolver_addr or resolver_addr == "0x0000000000000000000000000000000000000000":
            return False
        resolver = w3.eth.contract(address=Web3.to_checksum_address(resolver_addr), abi=RESOLVER_ABI)
        tx = resolver.functions.setText(node, KEY_REVIEW, attestation_tx_or_uid.strip()).build_transaction({
            "from": wallet.address,
            "chainId": w3.eth.chain_id,
            "gas": 80000,
            "nonce": w3.eth.get_transaction_count(wallet.address, "pending"),
        })
        signed = wallet.account.sign_transaction(tx)
        raw_tx = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction", None)
        if raw_tx is None:
            return False
        tx_hash = w3.eth.send_raw_transaction(raw_tx)
        _wait_receipt(w3, tx_hash, timeout=120, description="Set agentpay.review")
        return True
    except Exception:
        return False


# --- Convenience functions (discovery, combined register+provision, setup) ---

# Env vars for agent config
AGENTPAY_ENS_NAME_ENV = "AGENTPAY_ENS_NAME"
AGENTPAY_CAPABILITIES_ENV = "AGENTPAY_CAPABILITIES"
AGENTPAY_ENDPOINT_ENV = "AGENTPAY_ENDPOINT"
AGENTPAY_PRICES_ENV = "AGENTPAY_PRICES"

# RPC fallbacks (same as ens.py)
SEPOLIA_RPCS = [
    "https://ethereum-sepolia-rpc.publicnode.com",
    "https://sepolia.infura.io/v3/9aa3d95b3bc440fa88ea12eaa4456161",
]
MAINNET_RPCS = [
    "https://eth.llamarpc.com",
    "https://ethereum.publicnode.com",
]


def _connect_multiple(rpc_urls: List[str], timeout: int = 30) -> Web3:
    """Connect to first available RPC from list. 30s timeout allows slow RPCs for ENS lookup."""
    for url in rpc_urls:
        try:
            w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": timeout}))
            if w3.is_connected():
                return w3
        except Exception:
            continue
    raise ConnectionError(f"Could not connect to any RPC within {timeout}s: {rpc_urls}")


def get_agent_info(ens_name: str, rpc_url: Optional[str] = None, mainnet: bool = False) -> Optional[Dict[str, str]]:
    """
    Get agent info from ENS text records.

    Returns dict with name, capabilities, prices, endpoint or None if not found.
    Default mainnet=False: uses Sepolia testnet. Set mainnet=True for mainnet.
    
    Note: endpoint is required for hiring; capabilities and prices are optional.
    """
    rpc_urls = [rpc_url] if rpc_url else (MAINNET_RPCS if mainnet else SEPOLIA_RPCS)
    registry_addr = SEPOLIA_ENS_REGISTRY if not mainnet else "0x00000000000C2E074eC69A0dFb2997BA6C7d2e1e"
    try:
        w3 = _connect_multiple(rpc_urls)
    except Exception:
        return None
    
    registry = w3.eth.contract(address=Web3.to_checksum_address(registry_addr), abi=REGISTRY_ABI)
    node = namehash(ens_name)
    try:
        resolver_addr = registry.functions.resolver(node).call()
        if not resolver_addr or resolver_addr == "0x0000000000000000000000000000000000000000":
            return None
        resolver = w3.eth.contract(address=Web3.to_checksum_address(resolver_addr), abi=RESOLVER_ABI)
        # Read all records (endpoint required for hiring, but return partial info if missing)
        endpoint = resolver.functions.text(node, KEY_ENDPOINT).call() or ""
        capabilities = resolver.functions.text(node, KEY_CAPABILITIES).call() or ""
        prices = resolver.functions.text(node, KEY_PRICES).call() or ""
        # Return info even if endpoint is missing (caller can check)
        return {
            "name": ens_name,
            "capabilities": capabilities,
            "prices": prices,
            "endpoint": endpoint,
        }
    except Exception:
        return None


def _normalize_capability_spelling(s: str) -> str:
    """British/American and common typo: summarise/summerise -> summarize."""
    s = s.strip().lower()
    for variant, canonical in (
        ("summarise", "summarize"),
        ("summarises", "summarizes"),
        ("summerise", "summarize"),
        ("summerises", "summarizes"),
        ("analyse", "analyze"),
        ("analyses", "analyzes"),
    ):
        s = s.replace(variant, canonical)
    return s


def discover_agents(
    capability: str,
    known_agents: List[str],
    rpc_url: Optional[str] = None,
    mainnet: bool = False,
) -> List[Dict[str, str]]:
    """
    Find agents that offer a capability. Checks a list of ENS names.

    In production you'd use a subgraph or indexer; here we check known_agents.
    British/American spelling (e.g. summarise/summarize) is normalized so both match.
    """
    out = []
    want = _normalize_capability_spelling(capability)
    for ens_name in known_agents:
        info = get_agent_info(ens_name, rpc_url=rpc_url, mainnet=mainnet)
        if not info:
            continue
        caps_str = (info.get("capabilities") or "").strip()
        caps = [c.strip().lower() for c in caps_str.split(",") if c.strip()]
        caps_normalized = [_normalize_capability_spelling(c) for c in caps]
        if want in caps or want in caps_normalized:
            out.append(info)
            continue
        # Flexible: e.g. "summarize" matches ENS "summarise medical articles"
        if caps and any(want in _normalize_capability_spelling(cap) or _normalize_capability_spelling(cap).startswith(want) for cap in caps):
            out.append(info)
    return out


def get_ens_name_for_registration() -> str:
    """
    Return the ENS name the bot/human chose for sign-up (from AGENTPAY_ENS_NAME env).
    Use this so the agent is not assigned a random name: set AGENTPAY_ENS_NAME=myagent
    before registering, then pass the result to register_ens_name(wallet, name).
    Returns empty string if not set.
    """
    return (os.getenv(AGENTPAY_ENS_NAME_ENV) or "").strip().lower().removesuffix(".eth")


def get_agent_provisioning_from_env() -> Tuple[str, str, str]:
    """
    Return (capabilities, endpoint, prices) from env for automatic provisioning.
    Agent or deployer sets AGENTPAY_CAPABILITIES, AGENTPAY_ENDPOINT, AGENTPAY_PRICES.
    Returns ("", "", "N/A") if not set (caller can still pass explicit values).
    """
    caps = (os.getenv(AGENTPAY_CAPABILITIES_ENV) or "").strip()
    endpoint = (os.getenv(AGENTPAY_ENDPOINT_ENV) or "").strip()
    prices = (os.getenv(AGENTPAY_PRICES_ENV) or "N/A").strip()
    return caps, endpoint, prices


def get_ens_registration_quote(
    label: str,
    duration_years: float = 1.0,
    rpc_url: Optional[str] = None,
) -> Tuple[int, str]:
    """
    Get the ETH (wei) needed to register a .eth name on Sepolia and a short message for the user.

    Returns (total_wei_to_send, message). Use the message to prompt the human: "Send X ETH to <address> to register."
    The label is the name the user/bot chose (e.g. from AGENTPAY_ENS_NAME or user input).
    """
    label = label.strip().lower().removesuffix(".eth")
    if not label or len(label) < 3:
        return 0, "Label must be at least 3 characters."
    
    rpc_urls = [rpc_url] if rpc_url else SEPOLIA_RPCS
    try:
        w3 = _connect_multiple(rpc_urls)
    except Exception as e:
        return 0, f"Failed to connect to RPC: {e}"
    
    controller = w3.eth.contract(
        address=Web3.to_checksum_address(ETH_REGISTRAR_CONTROLLER),
        abi=CONTROLLER_ABI,
    )
    duration_seconds = int(duration_years * 365 * 24 * 3600)
    if duration_seconds < 28 * 24 * 3600:
        duration_seconds = 28 * 24 * 3600  # at least 28 days
    
    try:
        price = controller.functions.rentPrice(label, duration_seconds).call()
        base, premium = price[0], price[1]
        rent_wei = base + premium
        total_price_with_buffer = int(rent_wei * 1.05)  # 5% buffer
        gas_buffer = 500_000 * 30 * 10**9  # ~0.015 ETH at 30 gwei
        total = total_price_with_buffer + gas_buffer
        eth_str = f"{total / 10**18:.4f}"
        return total, f"Send at least {eth_str} ETH (Sepolia) to your agent address to register '{label}.eth'. Faucet: https://sepoliafaucet.com"
    except Exception as e:
        return 0, f"Failed to get registration quote: {e}"


def register_and_provision_ens(
    wallet: AgentWallet,
    label: str,
    capabilities: Optional[str] = None,
    endpoint: Optional[str] = None,
    prices: Optional[str] = None,
    duration_years: float = 1.0,
    rpc_url: Optional[str] = None,
    mainnet: bool = False,
) -> Tuple[bool, str]:
    """
    Register ENS name and automatically provision it with agent identity.
    
    This is the recommended flow for agents: register + provision in one call.
    ENS domain is prefilled from label; capabilities/endpoint/prices can come from
    env (AGENTPAY_CAPABILITIES, AGENTPAY_ENDPOINT, AGENTPAY_PRICES) if not passed.
    
    Args:
        wallet: Agent wallet (must be funded with ETH)
        label: ENS name without .eth suffix (e.g. "myagent")
        capabilities: Comma-separated capabilities; if None, uses AGENTPAY_CAPABILITIES env
        endpoint: Worker endpoint URL; if None, uses AGENTPAY_ENDPOINT env
        prices: Price string; if None, uses AGENTPAY_PRICES env or "N/A"
        duration_years: Registration duration in years (default 1.0)
        rpc_url: Optional RPC URL
        mainnet: If True, use mainnet (default False for Sepolia)
    
    Returns:
        (True, "label.eth") on success, or (False, error_message) on failure
    """
    # Resolve capabilities/endpoint/prices from env when not passed
    caps, ep, pr = get_agent_provisioning_from_env()
    capabilities = capabilities if capabilities is not None else caps
    endpoint = endpoint if endpoint is not None else ep
    prices = prices if prices is not None else pr

    # Step 1: Register ENS name (convert years to seconds)
    duration_seconds = int(duration_years * 365 * 24 * 3600)
    ok, result = register_ens_name(
        wallet,
        label,
        duration_seconds=duration_seconds,
        rpc_url=rpc_url,
        set_reverse_record=False,
    )
    if not ok:
        return False, f"Registration failed: {result}"
    
    ens_name = result  # Should be "label.eth"
    
    # Step 2: Provision identity (set text records)
    # Wait a moment for registration to propagate
    print("\n⏳ Waiting 2s for registration to propagate...")
    time.sleep(2)
    
    ok, msg = provision_ens_identity(
        wallet,
        ens_name,
        capabilities=capabilities,
        endpoint=endpoint,
        prices=prices,
        rpc_url=rpc_url,
    )
    if not ok:
        return False, f"Registration succeeded but provisioning failed: {msg}"
    
    print(f"\n🎉 Complete! '{ens_name}' is registered and provisioned.")
    return True, ens_name


def register_and_provision_ens_from_env(
    wallet: AgentWallet,
    label: Optional[str] = None,
    duration_years: float = 1.0,
    rpc_url: Optional[str] = None,
    mainnet: bool = False,
) -> Tuple[bool, str]:
    """
    Register ENS name and provision from env config. One-shot for agents.
    
    Uses AGENTPAY_ENS_NAME (or label), AGENTPAY_CAPABILITIES, AGENTPAY_ENDPOINT,
    AGENTPAY_PRICES. Agent/deployer sets these once; then call with just wallet.
    ENS domain is prefilled; capabilities/endpoint/prices come from env.
    
    Returns (True, "label.eth") on success, or (False, error_message) on failure.
    """
    label = (label or get_ens_name_for_registration() or "").strip().lower().removesuffix(".eth")
    if not label or len(label) < 3:
        return False, "Set AGENTPAY_ENS_NAME or pass label (min 3 chars)."
    return register_and_provision_ens(
        wallet,
        label,
        capabilities=None,
        endpoint=None,
        prices=None,
        duration_years=duration_years,
        rpc_url=rpc_url,
        mainnet=mainnet,
    )


def setup_new_agent(ens_name: Optional[str] = None) -> Tuple[AgentWallet, str]:
    """
    Helper function for new users: generates a wallet, shows setup instructions.
    
    This is the recommended flow for new users:
    1. Call setup_new_agent("myagent") → generates keypair, shows address
    2. User saves the private key to CLIENT_PRIVATE_KEY env var
    3. User sends ETH to the address (from get_ens_registration_quote)
    4. User calls register_and_provision_ens(wallet, "myagent", ...)
    
    Args:
        ens_name: Optional ENS name to register (from AGENTPAY_ENS_NAME if not provided)
    
    Returns:
        (wallet, instructions_message) - wallet is ready to use after user sets env var
    """
    from agentpay.wallet import generate_keypair
    
    # Generate new keypair
    account = generate_keypair()
    private_key_hex = account.key.hex()
    address = account.address
    
    # Get ENS name
    label = ens_name or get_ens_name_for_registration() or "myagent"
    label = label.strip().lower().removesuffix(".eth")
    
    # Get registration quote
    try:
        total_wei, quote_msg = get_ens_registration_quote(label, duration_years=1.0)
        eth_amount = f"{total_wei / 10**18:.4f}"
    except Exception:
        eth_amount = "~0.002"  # fallback estimate
        quote_msg = f"Send at least {eth_amount} ETH (Sepolia) to register '{label}.eth'"
    
    # Create wallet (user will need to set env var to use it)
    wallet = AgentWallet(account=account)
    
    instructions = f"""
╔═══════════════════════════════════════════════════════════════╗
║  AgentPay Setup - Save Your Private Key Securely!            ║
╚═══════════════════════════════════════════════════════════════╝

Your agent wallet has been generated:

  Address: {address}
  Private Key: {private_key_hex}

⚠️  IMPORTANT: Save your private key immediately!

  export CLIENT_PRIVATE_KEY={private_key_hex}
  export AGENTPAY_ENS_NAME={label}

Next steps:

1. SAVE YOUR PRIVATE KEY
   Copy this command and run it in your terminal:
   export CLIENT_PRIVATE_KEY={private_key_hex}

2. FUND YOUR WALLET
   Your wallet needs money to pay for things:
   
   a) Send ETH (for gas fees and ENS registration):
      - Amount: {eth_amount} ETH
      - Send to: {address}
      - Get free ETH: https://sepoliafaucet.com
      - (Paste your address {address}, click "Send Me ETH")
   
   b) Get Yellow test tokens (for paying workers):
      - Run this command in your terminal:
        curl -X POST https://clearnet-sandbox.yellow.com/faucet/requestTokens \\
             -H "Content-Type: application/json" \\
             -d '{{"userAddress":"{address}"}}'
      - Or if you have yellow_test set up: cd yellow_test && PRIVATE_KEY={private_key_hex} npm run faucet
      - This gives you test money (ytest.usd) to pay workers
   
   c) Check your ytest.usd balance (after faucet). Set CLIENT_PRIVATE_KEY first, then run:
      export CLIENT_PRIVATE_KEY={private_key_hex}
      python3 -c "from agentpay import AgentWallet; from agentpay.payments.yellow import steps_1_to_3; w=AgentWallet(); b=[x for x in steps_1_to_3(w) if x.get('asset')=='ytest.usd']; print('ytest.usd:', b[0]['amount']+' units (1e6=1 USD)' if b else 'none - request from faucet above')"

3. REGISTER YOUR AGENT NAME AND ENDPOINT
   After your wallet has ETH, register your agent's name and where to send jobs.
   Note: Full ENS registration (commit + register + provisioning) takes about 2.5 minutes; wait for it to complete.
   
   python3 -c "from agentpay import AgentWallet, register_and_provision_ens; wallet = AgentWallet(); ok, name = register_and_provision_ens(wallet, '{label}', capabilities='analyze-data,summarize', endpoint='http://localhost:8000', prices='0.05 USDC per job'); print('Registered:', name if ok else 'Failed: ' + name)"
   
   What this does:
   - Registers "{label}.eth" as your agent's name
   - Sets up your "resume" (what you can do, your prices, where to send jobs)
   - Other agents can now find and hire you by name

4. START YOUR WORKER
   Once registered, start your worker server (in a separate terminal).
   Important: The worker address must be DIFFERENT from the client address. Use this same wallet as worker when testing alone; when another agent pays you, they use their own CLIENT_PRIVATE_KEY and your worker address.
   
   export AGENTPAY_WORKER_WALLET={address}
   export AGENTPAY_WORKER_PRIVATE_KEY={private_key_hex}
   export AGENTPAY_PAYMENT_METHOD=yellow_chunked_full
   python3 agentpay/examples/worker_server.py
   
   Your worker is now running and ready to receive jobs!

5. TEST IT WORKS
   In another terminal, use a DIFFERENT wallet as client (different from the worker above). Payment fails if client and worker are the same address. Set CLIENT_PRIVATE_KEY to a different key, then:
   
   export CLIENT_PRIVATE_KEY=<different_key_hex>
   export WORKER_ENS_NAME={label}.eth
   python3 agentpay/examples/test_all_features.py
   
   This will test all prize features:
   - Find your agent by ENS name
   - Lock (both bots create channels)
   - Handshake (create Nitrolite session)
   - Chunked micropayments (10 chunks)
   - Settlement (on-chain transaction)
   - Adjudicator (dispute resolution demo)
   - Get the result back
   
   Note: ENS registration takes about 2.5 minutes to complete; wait before using a newly registered name.

╚═══════════════════════════════════════════════════════════════╝
"""
    
    print(instructions)
    return wallet, instructions