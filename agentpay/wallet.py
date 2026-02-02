"""
Agent wallet: local keypair, no API keys.

Key is loaded only from AGENTPAY_PRIVATE_KEY (env). Never read/write a key file.
"""

import os
from pathlib import Path
from typing import Optional

from eth_account import Account
from eth_account.signers.local import LocalAccount
from web3 import Web3

Account.enable_unaudited_hdwallet_features()

ENV_PRIVATE_KEY = "AGENTPAY_PRIVATE_KEY"


def generate_keypair() -> LocalAccount:
    """Generate a new random keypair. Caller must persist via env (never to file)."""
    return Account.create()


def load_or_create_key(key_path: Optional[Path] = None, save: bool = True) -> LocalAccount:
    """
    Load key from AGENTPAY_PRIVATE_KEY env only. Never reads or writes a file.
    Raises RuntimeError if env is not set.
    """
    pk_env = os.getenv(ENV_PRIVATE_KEY)
    if not pk_env or not pk_env.strip():
        raise RuntimeError(
            "Set AGENTPAY_PRIVATE_KEY in the environment (never commit it). "
            "Generate one: python -c \"from eth_account import Account; a = Account.create(); print(a.key.hex())\""
        )
    pk = pk_env.strip()
    if pk.startswith("0x"):
        pk = pk[2:]
    return Account.from_key(pk)


class AgentWallet:
    """
    Wallet for an AI agent. Key is loaded only from AGENTPAY_PRIVATE_KEY (env).
    Never reads or writes a key file.
    """

    def __init__(self, account: Optional[LocalAccount] = None, key_path: Optional[Path] = None):
        if account is None:
            account = load_or_create_key(key_path=key_path)
        self._account = account

    @property
    def address(self) -> str:
        """Agent's payment address (0x...). Others send here to fund the agent."""
        return self._account.address

    @property
    def account(self) -> LocalAccount:
        return self._account

    def sign_transaction(self, tx: dict, w3: Optional[Web3] = None) -> bytes:
        """Sign a transaction. Returns signed raw_Transaction (hex)."""
        if w3 is None:
            w3 = Web3()
        signed = self._account.sign_transaction(tx)
        return signed.rawTransaction

    def sign_message(self, message: bytes) -> dict:
        """Sign a message (EIP-191). Returns dict with messageHash, r, s, v."""
        from eth_account.messages import encode_defunct
        signable = encode_defunct(primitive=message)
        sig = self._account.sign_message(signable)
        return {"messageHash": sig.messageHash.hex(), "r": sig.r, "s": sig.s, "v": sig.v}

    @classmethod
    def from_key(cls, private_key: str) -> "AgentWallet":
        """Create wallet from raw private key (hex string)."""
        if private_key.startswith("0x"):
            private_key = private_key[2:]
        acc = Account.from_key(private_key)
        return cls(account=acc)

    @classmethod
    def from_key_file(cls, path: Path) -> "AgentWallet":
        """Deprecated: key must be in env. Set AGENTPAY_PRIVATE_KEY and use AgentWallet()."""
        raise RuntimeError("Private key must be in AGENTPAY_PRIVATE_KEY env only; do not use key files.")
