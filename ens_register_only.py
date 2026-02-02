import os
import sys
import time
import secrets
from web3 import Web3
from eth_abi import encode

# Replace these with your values
PRIVATE_KEY = os.environ.get("PRIVATE_KEY", "privatekeyhere")
RPC_URL = os.environ.get("RPC_URL", "https://ethereum-sepolia-rpc.publicnode.com")
DURATION_SECONDS = 31536000  # 1 year in seconds

# Sepolia Contract Addresses
ETH_REGISTRAR_CONTROLLER = "0xFED6a969AaA60E4961FCD3EBF1A2e8913ac65B72"
PUBLIC_RESOLVER = "0x0000000000000000000000000000000000000000"

# ============== ABIs ==============
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


def register_ens_domain(
    domain_name: str,
    duration_seconds: int = 31536000,
    set_reverse_record: bool = False
) -> dict:
    """
    Register an ENS domain on Sepolia testnet.
    
    Args:
        domain_name: The domain name without .eth suffix
        duration_seconds: Registration duration in seconds (default 1 year)
        set_reverse_record: Whether to set the reverse record (default True)
    
    Returns:
        dict with transaction hashes and registration details
    """
    
    # Initialize Web3
    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    
    if not w3.is_connected():
        raise ConnectionError("Failed to connect to Sepolia RPC")
    
    print(f"✓ Connected to Sepolia (Chain ID: {w3.eth.chain_id})")
    
    # Setup account
    account = w3.eth.account.from_key(PRIVATE_KEY)
    owner_address = account.address
    print(f"✓ Using account: {owner_address}")
    
    # Check balance
    balance = w3.eth.get_balance(owner_address)
    print(f"✓ Account balance: {w3.from_wei(balance, 'ether')} ETH")
    
    # Initialize controller contract
    controller = w3.eth.contract(
        address=Web3.to_checksum_address(ETH_REGISTRAR_CONTROLLER),
        abi=CONTROLLER_ABI
    )
    
    # Step 1: Check availability
    print(f"\n[1/5] Checking availability of '{domain_name}.eth'...")
    is_available = controller.functions.available(domain_name).call()
    
    if not is_available:
        raise ValueError(f"Domain '{domain_name}.eth' is not available")
    print(f"✓ Domain '{domain_name}.eth' is available!")
    
    # Step 2: Get rent price
    print(f"\n[2/5] Getting rent price...")
    price = controller.functions.rentPrice(domain_name, duration_seconds).call()
    total_price = price[0] + price[1]  # base + premium
    total_price_with_buffer = int(total_price * 1.05)  # 5% buffer for price fluctuations
    print(f"✓ Price: {w3.from_wei(total_price, 'ether')} ETH (+ 5% buffer)")
    
    # Step 3: Generate secret and make commitment
    print(f"\n[3/5] Creating commitment...")
    secret = secrets.token_bytes(32)
    
    commitment = controller.functions.makeCommitment(
        domain_name,
        owner_address,
        duration_seconds,
        secret,
        Web3.to_checksum_address(PUBLIC_RESOLVER),
        [],  # Empty data array
        set_reverse_record,
        0  # ownerControlledFuses
    ).call()
    
    print(f"✓ Commitment hash: {commitment.hex()}")
    
    # Step 4: Submit commitment transaction
    print(f"\n[4/5] Submitting commitment transaction...")
    
    # Get min commitment age
    min_commitment_age = controller.functions.minCommitmentAge().call()
    print(f"  Min commitment age: {min_commitment_age} seconds")
    
    commit_tx = controller.functions.commit(commitment).build_transaction({
        'from': owner_address,
        'nonce': w3.eth.get_transaction_count(owner_address),
        'gas': 100000,
        'gasPrice': w3.eth.gas_price,
    })
    
    signed_commit_tx = w3.eth.account.sign_transaction(commit_tx, PRIVATE_KEY)
    commit_tx_hash = w3.eth.send_raw_transaction(signed_commit_tx.raw_transaction)
    print(f"✓ Commit TX sent: {commit_tx_hash.hex()}")
    
    # Wait for commit transaction confirmation
    print("  Waiting for confirmation...")
    commit_receipt = w3.eth.wait_for_transaction_receipt(commit_tx_hash)
    
    if commit_receipt['status'] != 1:
        raise Exception("Commit transaction failed")
    print(f"✓ Commit confirmed in block {commit_receipt['blockNumber']}")
    
    # Wait for minimum commitment age + buffer
    wait_time = min_commitment_age + 5
    print(f"\n  ⏳ Waiting {wait_time} seconds for commitment to mature...")
    
    for remaining in range(wait_time, 0, -1):
        print(f"    {remaining} seconds remaining...", end='\r')
        time.sleep(1)
    print(f"    ✓ Commitment matured!              ")
    
    # Step 5: Register the domain
    print(f"\n[5/5] Registering domain...")
    
    register_tx = controller.functions.register(
        domain_name,
        owner_address,
        duration_seconds,
        secret,
        Web3.to_checksum_address(PUBLIC_RESOLVER),
        [],  # Empty data array
        set_reverse_record,
        0  # ownerControlledFuses
    ).build_transaction({
        'from': owner_address,
        'value': total_price_with_buffer,
        'nonce': w3.eth.get_transaction_count(owner_address),
        'gas': 300000,
        'gasPrice': w3.eth.gas_price,
    })
    
    signed_register_tx = w3.eth.account.sign_transaction(register_tx, PRIVATE_KEY)
    register_tx_hash = w3.eth.send_raw_transaction(signed_register_tx.raw_transaction)
    print(f"✓ Register TX sent: {register_tx_hash.hex()}")
    
    # Wait for register transaction confirmation
    print("  Waiting for confirmation...")
    register_receipt = w3.eth.wait_for_transaction_receipt(register_tx_hash)
    
    if register_receipt['status'] != 1:
        raise Exception("Register transaction failed")
    
    print(f"✓ Registration confirmed in block {register_receipt['blockNumber']}")
    print(f"\n🎉 Successfully registered '{domain_name}.eth'!")
    
    return {
        "domain": f"{domain_name}.eth",
        "owner": owner_address,
        "duration_seconds": duration_seconds,
        "commit_tx_hash": commit_tx_hash.hex(),
        "register_tx_hash": register_tx_hash.hex(),
        "total_cost_wei": total_price,
        "total_cost_eth": float(w3.from_wei(total_price, 'ether'))
    }


def check_domain_availability(domain_name: str) -> bool:
    """Quick check if a domain is available."""
    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    controller = w3.eth.contract(
        address=Web3.to_checksum_address(ETH_REGISTRAR_CONTROLLER),
        abi=CONTROLLER_ABI
    )
    return controller.functions.available(domain_name).call()


def get_registration_price(domain_name: str, duration_seconds: int = 31536000) -> dict:
    """Get the price to register a domain."""
    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    controller = w3.eth.contract(
        address=Web3.to_checksum_address(ETH_REGISTRAR_CONTROLLER),
        abi=CONTROLLER_ABI
    )
    price = controller.functions.rentPrice(domain_name, duration_seconds).call()
    return {
        "base_wei": price[0],
        "premium_wei": price[1],
        "total_wei": price[0] + price[1],
        "total_eth": float(w3.from_wei(price[0] + price[1], 'ether'))
    }


if __name__ == "__main__":
    # example usage
    try:
        result = register_ens_domain(
            domain_name=DOMAIN_NAME,
            duration_seconds=DURATION_SECONDS,
            set_reverse_record=False
        )
        print("\n" + "=" * 50)
        print("Registration Result:")
        for key, value in result.items():
            print(f"  {key}: {value}")
    except Exception as e:
        print(f"\n❌ Error: {e}")