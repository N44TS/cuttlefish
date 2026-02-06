"""
ENS discovery and provisioning: find agents by capability via ENS text records;
provision an agent's ENS "resume" (set text records) using the agent's wallet.
Optional: register a new .eth name on Sepolia (commit-reveal via ETH Registrar Controller).

Agents publish agentpay.capabilities, agentpay.prices, agentpay.endpoint.
No API key; uses public RPC. Fund the agent's wallet once (e.g. Coinbase or faucet)
so it can pay gas for setting records or registering a name.

ENS docs: https://docs.ens.domains/ (registry/eth for commit-reveal).
"""

import os
import secrets
import time
from typing import Dict, List, Optional, Tuple

from web3 import Web3
from web3.types import HexBytes

from agentpay.wallet import AgentWallet

# ENS contract addresses (https://docs.ens.domains/learn/deployments)
# Registry is same address on mainnet and Sepolia; chain is determined by RPC.
ENS_REGISTRY = "0x00000000000C2E074eC69A0dFb2997BA6C7d2e1e"
SEPOLIA_ENS_REGISTRY = "0x00000000000C2E074eC69A0dFb2997BA6C7d2e1e"  # same as mainnet, used on Sepolia RPC

# Mainnet (only when mainnet=True)
PUBLIC_RESOLVER = "0x4976fb03C32e5B8cfe2b6cCB31c09Ba78EBaBa41"

# Sepolia testnet (default for this SDK)
SEPOLIA_ETH_REGISTRAR_CONTROLLER = "0xFED6a969AaA60E4961FCD3EBF1A2e8913ac65B72"
SEPOLIA_PUBLIC_RESOLVER = "0xE99638b40E4Fff0129D56f03b55b6bbC4BBE49b5"
# Resolver to pass at registration time: match ens_register_only.py (zero = no resolver set at reg)
REGISTRATION_RESOLVER_ZERO = "0x0000000000000000000000000000000000000000"
RESOLVER_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "node", "type": "bytes32"}, {"name": "key", "type": "string"}],
        "name": "text",
        "outputs": [{"name": "", "type": "string"}],
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [
            {"name": "node", "type": "bytes32"},
            {"name": "key", "type": "string"},
            {"name": "value", "type": "string"},
        ],
        "name": "setText",
        "outputs": [],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [{"name": "node", "type": "bytes32"}],
        "name": "resolver",
        "outputs": [{"name": "", "type": "address"}],
        "type": "function",
    },
]
REGISTRY_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "node", "type": "bytes32"}],
        "name": "resolver",
        "outputs": [{"name": "", "type": "address"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [{"name": "node", "type": "bytes32"}],
        "name": "owner",
        "outputs": [{"name": "", "type": "address"}],
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [
            {"name": "node", "type": "bytes32"},
            {"name": "resolver", "type": "address"},
        ],
        "name": "setResolver",
        "outputs": [],
        "type": "function",
    },
]

# ETH Registrar Controller (Sepolia .eth registration: commit-reveal)
# Updated to match working version from ens_register_only.py
ETH_REGISTRAR_CONTROLLER_ABI = [
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
    {
        "inputs": [{"name": "name", "type": "string"}],
        "name": "available",
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [
            {"name": "name", "type": "string"},
            {"name": "duration", "type": "uint256"}
        ],
        "name": "rentPrice",
        "outputs": [
            {
                "components": [
                    {"name": "base", "type": "uint256"},
                    {"name": "premium", "type": "uint256"}
                ],
                "name": "price",
                "type": "tuple"
            }
        ],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "minCommitmentAge",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "maxCommitmentAge",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    }
]

# Text record keys for agent discovery
KEY_CAPABILITIES = "agentpay.capabilities"
KEY_PRICES = "agentpay.prices"
KEY_ENDPOINT = "agentpay.endpoint"

# Same default RPC as working examples (testens.py, ens_register_only.py)
_SEPOLIA_RPC_DEFAULT = "https://ethereum-sepolia-rpc.publicnode.com"
SEPOLIA_RPCS = [
    os.getenv("RPC_URL") or os.getenv("SEPOLIA_RPC") or _SEPOLIA_RPC_DEFAULT,
    "https://ethereum-sepolia-rpc.publicnode.com",
    "https://rpc.sepolia.org",
    "https://rpc2.sepolia.org",
]
MAINNET_RPCS = [
    os.getenv("ETH_RPC", "https://eth.llamarpc.com"),
    "https://rpc.ankr.com/eth",
]


def namehash(name: str) -> bytes:
    """ENS namehash: for 'label.eth' we need both labels ('eth' and 'label'), not just the label."""
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


def _connect(rpc_urls: List[str]) -> Web3:
    for url in rpc_urls:
        try:
            w3 = Web3(Web3.HTTPProvider(url))
            if w3.is_connected():
                return w3
        except Exception:
            continue
    raise ConnectionError(f"Could not connect to any RPC: {rpc_urls}")


def get_agent_info(ens_name: str, rpc_url: Optional[str] = None, mainnet: bool = False) -> Optional[Dict[str, str]]:
    """
    Get agent info from ENS text records.

    Returns dict with name, capabilities, prices, endpoint or None if not found.
    Default mainnet=False: uses Sepolia testnet. Set mainnet=True for mainnet.
    
    Note: endpoint is required for hiring; capabilities and prices are optional.
    """
    rpc_urls = [rpc_url] if rpc_url else (MAINNET_RPCS if mainnet else SEPOLIA_RPCS)
    registry_addr = ENS_REGISTRY if mainnet else SEPOLIA_ENS_REGISTRY
    w3 = _connect(rpc_urls)
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
    except Exception as e:
        return None


def discover_agents(
    capability: str,
    known_agents: List[str],
    rpc_url: Optional[str] = None,
    mainnet: bool = False,
) -> List[Dict[str, str]]:
    """
    Find agents that offer a capability. Checks a list of ENS names.

    In production you'd use a subgraph or indexer; here we check known_agents.
    """
    out = []
    for ens_name in known_agents:
        info = get_agent_info(ens_name, rpc_url=rpc_url, mainnet=mainnet)
        if not info:
            continue
        caps = [c.strip().lower() for c in info["capabilities"].split(",")]
        if capability.lower() in caps:
            out.append(info)
    return out


# Minimum ETH (wei) we consider enough for setting a few text records
MIN_GAS_WEI = 500_000 * 20 * 10**9  # ~0.01 ETH at 20 gwei
FUNDING_MESSAGE = (
    "Fund this address with a little ETH (e.g. ~0.01 ETH on mainnet, or use Sepolia faucet for testnet) "
    "so it can pay gas to set your ENS records. You only need to do this once. "
    "Options: Coinbase, or faucet (e.g. https://sepoliafaucet.com for Sepolia)."
)


def provision_ens_identity(
    wallet: AgentWallet,
    ens_name: str,
    capabilities: str,
    endpoint: str = "",
    prices: str = "N/A",
    rpc_url: Optional[str] = None,
    mainnet: bool = False,
) -> Tuple[bool, str]:
    """
    Set AgentPay text records (agent resume) on an ENS name using the agent's wallet.
    The wallet must already own the ENS name (register at sepolia.app.ens.domains for testnet).

    Default mainnet=False: uses Sepolia testnet. Set mainnet=True for mainnet.
    Returns (True, ens_name) on success, or (False, error_message) on failure.
    """
    rpc_urls = [rpc_url] if rpc_url else (MAINNET_RPCS if mainnet else SEPOLIA_RPCS)
    registry_addr = ENS_REGISTRY if mainnet else SEPOLIA_ENS_REGISTRY
    try:
        w3 = _connect(rpc_urls)
    except Exception as e:
        return False, str(e)

    balance = w3.eth.get_balance(wallet.address)
    if balance < MIN_GAS_WEI:
        return (
            False,
            f"Insufficient gas. Address {wallet.address} has low balance. {FUNDING_MESSAGE}",
        )

    node = namehash(ens_name)
    registry = w3.eth.contract(
        address=Web3.to_checksum_address(registry_addr),
        abi=REGISTRY_ABI,
    )
    owner = registry.functions.owner(node).call()
    if not owner or owner.lower() != wallet.address.lower():
        return (
            False,
            f"Wallet {wallet.address} does not own ENS name '{ens_name}'. "
            "Register it at sepolia.app.ens.domains (testnet) or app.ens.domains (mainnet) and link this wallet.",
        )

    resolver_to_use = PUBLIC_RESOLVER if mainnet else SEPOLIA_PUBLIC_RESOLVER
    resolver_addr = registry.functions.resolver(node).call()
    if not resolver_addr or resolver_addr == "0x0000000000000000000000000000000000000000":
        # Set resolver first
        resolver_contract = w3.eth.contract(
            address=Web3.to_checksum_address(resolver_to_use),
            abi=RESOLVER_ABI,
        )
        tx = registry.functions.setResolver(node, Web3.to_checksum_address(resolver_to_use)).build_transaction(
            {
                "from": wallet.address,
                "chainId": w3.eth.chain_id,
                "gas": 100_000,
                "nonce": w3.eth.get_transaction_count(wallet.address),
            }
        )
        signed = wallet.account.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed.rawTransaction)
        w3.eth.wait_for_transaction_receipt(tx_hash)
        resolver_addr = resolver_to_use

    resolver = w3.eth.contract(
        address=Web3.to_checksum_address(resolver_addr),
        abi=RESOLVER_ABI,
    )
    records = [
        (KEY_CAPABILITIES, capabilities),
        (KEY_ENDPOINT, endpoint),
        (KEY_PRICES, prices),
    ]
    for key, value in records:
        tx = resolver.functions.setText(node, key, value).build_transaction(
            {
                "from": wallet.address,
                "chainId": w3.eth.chain_id,
                "gas": 80_000,
                "nonce": w3.eth.get_transaction_count(wallet.address),
            }
        )
        signed = wallet.account.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed.rawTransaction)
        w3.eth.wait_for_transaction_receipt(tx_hash)

    return True, ens_name


# --- Sepolia .eth registration (commit-reveal) ---

# Env vars for agent config (agent or deployer sets these; SDK uses them when not passed explicitly)
AGENTPAY_ENS_NAME_ENV = "AGENTPAY_ENS_NAME"
AGENTPAY_CAPABILITIES_ENV = "AGENTPAY_CAPABILITIES"
AGENTPAY_ENDPOINT_ENV = "AGENTPAY_ENDPOINT"
AGENTPAY_PRICES_ENV = "AGENTPAY_PRICES"

# 1 year in seconds; controller may enforce MIN_REGISTRATION_DURATION (e.g. 28 days)
DEFAULT_REGISTRATION_DURATION_SEC = 31536000
# Slippage for rent (ENS docs: "5-10% will likely be sufficient")
RENT_SLIPPAGE_BPS = 1000  # 10%
# Minimum wei to send with register() when oracle returns 0 (e.g. testnet)
MIN_REGISTER_VALUE_WEI = 10**15  # 0.001 ETH
# Extra wei for commit + register gas
REGISTRATION_GAS_BUFFER_WEI = 500_000 * 30 * 10**9  # ~0.015 ETH at 30 gwei


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
    w3 = _connect(rpc_urls)
    controller = w3.eth.contract(
        address=Web3.to_checksum_address(SEPOLIA_ETH_REGISTRAR_CONTROLLER),
        abi=ETH_REGISTRAR_CONTROLLER_ABI,
    )
    duration = int(duration_years * 365 * 24 * 3600)
    if duration < 28 * 24 * 3600:
        duration = 28 * 24 * 3600  # at least 28 days
    price = controller.functions.rentPrice(label, duration).call()
    base, premium = price[0], price[1]
    rent_wei = base + premium
    total = rent_wei + (rent_wei * RENT_SLIPPAGE_BPS // 10_000) + REGISTRATION_GAS_BUFFER_WEI
    eth_str = f"{total / 10**18:.4f}"
    return total, f"Send at least {eth_str} ETH (Sepolia) to your agent address to register '{label}.eth'. Faucet: https://sepoliafaucet.com"


def register_ens_name(
    wallet: AgentWallet,
    label: str,
    duration_years: float = 1.0,
    rpc_url: Optional[str] = None,
    set_reverse_record: bool = False,
) -> Tuple[bool, str]:
    """
    Register a .eth name on Sepolia using the agent's wallet (commit-reveal).
    Uses the working implementation from ens_register_only.py.

    Returns (True, "label.eth") on success, or (False, error_message) on failure.
    """
    label = label.strip().lower().removesuffix(".eth")
    if not label or len(label) < 3:
        return False, "Label must be at least 3 characters."
    
    rpc_urls = [rpc_url] if rpc_url else SEPOLIA_RPCS
    try:
        w3 = _connect(rpc_urls)
    except Exception as e:
        return False, f"Failed to connect to RPC: {e}"

    controller = w3.eth.contract(
        address=Web3.to_checksum_address(SEPOLIA_ETH_REGISTRAR_CONTROLLER),
        abi=ETH_REGISTRAR_CONTROLLER_ABI,
    )
    
    # Check availability
    if not controller.functions.available(label).call():
        return False, f"Name '{label}.eth' is not available on Sepolia."

    # Get rent price
    duration_seconds = int(duration_years * 365 * 24 * 3600)
    price = controller.functions.rentPrice(label, duration_seconds).call()
    total_price = price[0] + price[1]  # base + premium
    total_price_with_buffer = int(total_price * 1.05)  # 5% buffer
    
    # Check balance
    balance = w3.eth.get_balance(wallet.address)
    if balance < total_price_with_buffer + 500_000 * 30 * 10**9:  # value + gas buffer
        eth_needed = (total_price_with_buffer + 500_000 * 30 * 10**9) / 10**18
        return False, (
            f"Insufficient balance. Need ~{eth_needed:.4f} ETH (registration + gas). "
            f"Send to: {wallet.address} (Sepolia faucet: https://sepoliafaucet.com)"
        )

    # Generate secret
    secret = secrets.token_bytes(32)
    
    # Resolver at registration: use zero to match ens_register_only.py (working). Provisioning sets real resolver later.
    resolver_at_registration = REGISTRATION_RESOLVER_ZERO
    commitment = controller.functions.makeCommitment(
        label,
        Web3.to_checksum_address(wallet.address),
        duration_seconds,
        secret,
        Web3.to_checksum_address(resolver_at_registration),
        [],  # Empty data array
        set_reverse_record,
        0  # ownerControlledFuses
    ).call()

    # Step 1: Commit
    commit_tx = controller.functions.commit(commitment).build_transaction({
        'from': wallet.address,
        'nonce': w3.eth.get_transaction_count(wallet.address),
        'gas': 100000,
        'gasPrice': w3.eth.gas_price,
    })
    # Use w3.eth.account.sign_transaction like working version
    private_key = wallet.account.key.hex()
    signed_commit_tx = w3.eth.account.sign_transaction(commit_tx, private_key)
    commit_tx_hash = w3.eth.send_raw_transaction(signed_commit_tx.raw_transaction)
    commit_receipt = w3.eth.wait_for_transaction_receipt(commit_tx_hash)
    
    if commit_receipt.get('status') != 1:
        return False, (
            f"Commit transaction failed. "
            f"Check Etherscan: https://sepolia.etherscan.io/tx/{commit_tx_hash.hex()}"
        )

    # Wait for commitment age
    min_commitment_age = controller.functions.minCommitmentAge().call()
    wait_time = min_commitment_age + 5
    time.sleep(wait_time)

    # Step 2: Register (payable)
    register_tx = controller.functions.register(
        label,
        Web3.to_checksum_address(wallet.address),
        duration_seconds,
        secret,
        Web3.to_checksum_address(resolver_at_registration),
        [],  # Empty data array
        set_reverse_record,
        0  # ownerControlledFuses
    ).build_transaction({
        'from': wallet.address,
        'value': total_price_with_buffer,
        'nonce': w3.eth.get_transaction_count(wallet.address),
        'gas': 300000,
        'gasPrice': w3.eth.gas_price,
    })
    
    # Use w3.eth.account.sign_transaction like working version
    signed_register_tx = w3.eth.account.sign_transaction(register_tx, private_key)
    register_tx_hash = w3.eth.send_raw_transaction(signed_register_tx.raw_transaction)
    register_receipt = w3.eth.wait_for_transaction_receipt(register_tx_hash)
    
    if register_receipt.get('status') != 1:
        return False, (
            f"Register transaction failed (name taken, timing, or insufficient value). "
            f"Check Etherscan: https://sepolia.etherscan.io/tx/{register_tx_hash.hex()}"
        )

    return True, f"{label}.eth"


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

    # Step 1: Register ENS name
    ok, result = register_ens_name(
        wallet,
        label,
        duration_years=duration_years,
        rpc_url=rpc_url,
        set_reverse_record=False,
    )
    if not ok:
        return False, f"Registration failed: {result}"
    
    ens_name = result  # Should be "label.eth"
    
    # Step 2: Provision identity (set text records)
    # Wait a moment for registration to propagate
    time.sleep(2)
    
    ok, msg = provision_ens_identity(
        wallet,
        ens_name,
        capabilities=capabilities,
        endpoint=endpoint,
        prices=prices,
        rpc_url=rpc_url,
        mainnet=mainnet,
    )
    if not ok:
        return False, f"Registration succeeded but provisioning failed: {msg}"
    
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
    2. User saves the private key to AGENTPAY_PRIVATE_KEY env var
    3. User sends ETH to the address (from get_ens_registration_quote)
    4. User calls register_ens_name(wallet, "myagent")
    
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

3. REGISTER YOUR AGENT NAME AND ENDPOINT
   After your wallet has ETH, register your agent's name and where to send jobs:
   
   python3 -c "
   from agentpay import AgentWallet, register_and_provision_ens
   wallet = AgentWallet()
   ok, name = register_and_provision_ens(
       wallet,
       '{label}',
       capabilities='analyze-data,summarize',
       endpoint='http://localhost:8000',
       prices='0.05 USDC per job'
   )
   print('Registered:', name if ok else 'Failed: ' + name)
   "
   
   What this does:
   - Registers "{label}.eth" as your agent's name
   - Sets up your "resume" (what you can do, your prices, where to send jobs)
   - Other agents can now find and hire you by name

4. START YOUR WORKER
   Once registered, start your worker server (in a separate terminal):
   
   export AGENTPAY_WORKER_WALLET={address}
   export AGENTPAY_WORKER_PRIVATE_KEY={private_key_hex}
   export AGENTPAY_PAYMENT_METHOD=yellow_full
   python3 agentpay/examples/worker_server.py
   
   Your worker is now running and ready to receive jobs!

5. TEST IT WORKS
   In another terminal, hire your own agent to test:
   
   export CLIENT_PRIVATE_KEY={private_key_hex}
   export WORKER_ENS_NAME={label}.eth
   python3 agentpay/examples/yellow_e2e.py
   
   This will:
   - Find your agent by ENS name
   - Send a job
   - Pay via Yellow
   - Get the result back

╚═══════════════════════════════════════════════════════════════╝
"""
    
    print(instructions)
    return wallet, instructions