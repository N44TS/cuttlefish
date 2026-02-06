"""
On-chain payment: USDC transfer. No API key; uses public RPC.

Agent wallet signs and broadcasts; worker verifies tx on chain.
"""

import os
from typing import Optional

from web3 import Web3

from agentpay.schema import Bill
from agentpay.wallet import AgentWallet

# Sepolia
SEPOLIA_RPC = os.getenv("SEPOLIA_RPC", "https://ethereum-sepolia-rpc.publicnode.com")
SEPOLIA_CHAIN_ID = 11155111
# USDC on Sepolia (6 decimals)
USDC_SEPOLIA = "0x25762231808F040410586504fDF08Df259A2163c"

ERC20_TRANSFER_ABI = [
    {
        "constant": False,
        "inputs": [
            {"name": "to", "type": "address"},
            {"name": "value", "type": "uint256"},
        ],
        "name": "transfer",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [{"name": "account", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function",
    },
]

USDC_DECIMALS = 6


def _to_units(amount_usdc: float) -> int:
    return int(amount_usdc * (10**USDC_DECIMALS))


def pay_onchain(
    bill: Bill,
    wallet: AgentWallet,
    rpc_url: Optional[str] = None,
    usdc_address: Optional[str] = None,
    worker_endpoint: Optional[str] = None,
    **kwargs: object,
) -> str:
    """
    Pay a bill with on-chain USDC. Returns tx_hash for the worker to verify.

    No API key. Uses public RPC. Agent must have USDC and some native token for gas.
    """
    rpc_url = rpc_url or SEPOLIA_RPC
    usdc_address = usdc_address or USDC_SEPOLIA
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    if not w3.is_connected():
        raise ConnectionError(f"Cannot connect to RPC: {rpc_url}")

    contract = w3.eth.contract(
        address=Web3.to_checksum_address(usdc_address),
        abi=ERC20_TRANSFER_ABI,
    )
    amount_units = _to_units(bill.amount)
    recipient = Web3.to_checksum_address(bill.recipient)

    nonce = w3.eth.get_transaction_count(wallet.address)
    tx = contract.functions.transfer(recipient, amount_units).build_transaction(
        {
            "from": wallet.address,
            "chainId": bill.chain_id or SEPOLIA_CHAIN_ID,
            "gas": 100_000,
            "nonce": nonce,
        }
    )
    signed = wallet.account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    return tx_hash.hex()
