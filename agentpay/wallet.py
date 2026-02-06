"""
Agent wallet: local keypair, no API keys.

Key is loaded from CLIENT_PRIVATE_KEY (env) or .env file; AGENTPAY_PRIVATE_KEY is accepted as fallback.
Never read/write a key file.
"""

import os
from pathlib import Path
from typing import Optional

from eth_account import Account
from eth_account.signers.local import LocalAccount
from web3 import Web3

# Try to load .env file if python-dotenv is available
try:
    from dotenv import load_dotenv
    # Load .env from current directory or parent directories (up to repo root)
    _env_loaded = False
    for _dir in [Path.cwd(), Path(__file__).parent, Path(__file__).parent.parent]:
        _env_file = _dir / ".env"
        if _env_file.exists():
            load_dotenv(_env_file, override=False)  # Don't override existing env vars
            _env_loaded = True
            break
    if not _env_loaded:
        # Try loading from current directory as fallback
        load_dotenv(override=False)
except ImportError:
    # python-dotenv not installed, skip .env loading
    pass

Account.enable_unaudited_hdwallet_features()

# Prefer CLIENT_PRIVATE_KEY so it's clear this is the client's key (not worker's).
ENV_PRIVATE_KEY = "CLIENT_PRIVATE_KEY"
ENV_PRIVATE_KEY_LEGACY = "AGENTPAY_PRIVATE_KEY"


def generate_keypair() -> LocalAccount:
    """Generate a new random keypair. Caller must persist via env (never to file)."""
    return Account.create()


def load_or_create_key(key_path: Optional[Path] = None, save: bool = True) -> LocalAccount:
    """
    Load key from CLIENT_PRIVATE_KEY (or AGENTPAY_PRIVATE_KEY) env or .env file.
    Never reads or writes a key file (only reads from env/.env).
    Raises RuntimeError if neither env is set.
    
    Note: Balance checking (if enabled) happens AFTER wallet creation, so you must set CLIENT_PRIVATE_KEY first.
    """
    # Try loading .env if not already loaded (in case called before wallet.py import)
    try:
        from dotenv import load_dotenv
        load_dotenv(override=False)
    except ImportError:
        pass
    
    pk_env = os.getenv(ENV_PRIVATE_KEY) or os.getenv(ENV_PRIVATE_KEY_LEGACY)
    if not pk_env or not pk_env.strip():
        check_balance_hint = ""
        if os.getenv("AGENTPAY_CHECK_BALANCE", "false").lower() == "true":
            check_balance_hint = "\n\n(Note: Balance checking requires CLIENT_PRIVATE_KEY to be set first.)"
        raise RuntimeError(
            "Set CLIENT_PRIVATE_KEY in the environment (never commit it). "
            "Generate one: python -c \"from eth_account import Account; a = Account.create(); print(a.key.hex())\""
            + check_balance_hint
        )
    pk = pk_env.strip()
    if pk.startswith("0x"):
        pk = pk[2:]
    return Account.from_key(pk)


class AgentWallet:
    """
    Wallet for an AI agent. Key is loaded from CLIENT_PRIVATE_KEY (env); AGENTPAY_PRIVATE_KEY accepted as fallback.
    Never reads or writes a key file.
    
    Optionally checks balance and prompts for funding:
    - Set AGENTPAY_CHECK_BALANCE=true to enable balance checking
    - Set AGENTPAY_AUTO_FUND_TESTNET=true to auto-fund on testnet (default: false, prompts human)
    - On mainnet: Always prompts human (never auto-funds)
    """

    def __init__(
        self,
        account: Optional[LocalAccount] = None,
        key_path: Optional[Path] = None,
        check_balance: Optional[bool] = None,
        network: str = "sepolia",
    ):
        if account is None:
            account = load_or_create_key(key_path=key_path)
        self._account = account
        
        # Optional: Check balance and prompt for funding
        if check_balance is None:
            check_balance = os.getenv("AGENTPAY_CHECK_BALANCE", "false").lower() == "true"
        
        if check_balance:
            # Lazy import to avoid circular dependency
            try:
                from agentpay.faucet import ensure_funded, prompt_funding_choice
                
                is_funded, message = ensure_funded(self, network=network)
                if is_funded:
                    # Wallet is funded - print success message
                    print(message)
                else:
                    # Needs funding - print message and prompt
                    print(message)
                    # If not auto-funding, prompt human
                    if network == "sepolia" and not os.getenv("AGENTPAY_AUTO_FUND_TESTNET", "false").lower() == "true":
                        try:
                            choice = prompt_funding_choice(self, network=network)
                            if choice == "auto":
                                # Retry with auto-fund
                                is_funded, message = ensure_funded(self, auto_fund=True, network=network)
                                if not is_funded:
                                    print(f"\n⚠️  {message}")
                            elif choice == "manual":
                                print(f"\n💡 Please fund {self.address} and retry.")
                            # else: skip (continue anyway)
                        except (EOFError, KeyboardInterrupt):
                            # Non-interactive environment (e.g., bot), skip prompt
                            print(f"\n💡 Non-interactive: Please fund {self.address} manually or set AGENTPAY_AUTO_FUND_TESTNET=true")
            except ImportError:
                # Faucet module not available, skip check
                pass
            except Exception as e:
                # Don't crash wallet creation if balance check fails
                print(f"⚠️  Balance check failed: {e}")

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
        """Deprecated: key must be in env. Set CLIENT_PRIVATE_KEY and use AgentWallet()."""
        raise RuntimeError("Private key must be in CLIENT_PRIVATE_KEY env only; do not use key files.")
