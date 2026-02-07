"""
Faucet helper: Check balances and prompt human for funding.

On testnet: Can auto-request from faucets (if enabled).
On mainnet: Always prompts human (never auto-funds).
"""
import os
from typing import Optional, Tuple
from web3 import Web3

from agentpay.wallet import AgentWallet

# Minimum balances (in wei/units)
MIN_ETH_WEI = 500_000 * 30 * 10**9  # ~0.015 ETH at 30 gwei (for gas)
MIN_YTEST_USD_UNITS = 50_000  # 0.05 USDC (minimum for a small payment)

# Sepolia faucet API (if available)
SEPOLIA_FAUCET_URL = os.getenv("AGENTPAY_SEPOLIA_FAUCET_URL", "https://sepoliafaucet.com")
YELLOW_FAUCET_URL = os.getenv("AGENTPAY_YELLOW_FAUCET_URL", "https://clearnet-sandbox.yellow.com/faucet/requestTokens")

# Auto-funding behavior (testnet only)
AUTO_FUND_TESTNET = os.getenv("AGENTPAY_AUTO_FUND_TESTNET", "false").lower() == "true"


def check_eth_balance(wallet: AgentWallet, w3: Optional[Web3] = None) -> Tuple[float, bool]:
    """
    Check ETH balance. Returns (balance_eth, has_sufficient).
    Gracefully handles network errors (returns 0.0, False if can't check).
    """
    try:
        if w3 is None:
            # Use same RPC as rest of SDK (publicnode.com is reliable)
            rpc_url = os.getenv("AGENTPAY_SEPOLIA_RPC") or os.getenv("SEPOLIA_RPC", "https://ethereum-sepolia-rpc.publicnode.com")
            w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 10}))
        
        # Test RPC connection
        try:
            w3.eth.block_number  # Quick connectivity test
        except Exception as rpc_err:
            # RPC not available - return 0 but log for debugging
            if os.getenv("AGENTPAY_DEBUG"):
                print(f"⚠️  RPC unavailable ({rpc_url}): {rpc_err}")
            return 0.0, False
        
        balance_wei = w3.eth.get_balance(wallet.address)
        balance_eth = balance_wei / 10**18
        has_sufficient = balance_wei >= MIN_ETH_WEI
        
        return balance_eth, has_sufficient
    except Exception as e:
        # Network error or RPC unavailable - can't check balance
        # Return False so user is prompted, but don't crash
        if os.getenv("AGENTPAY_DEBUG"):
            print(f"⚠️  Balance check error: {e}")
        return 0.0, False


def check_yellow_balance(wallet: AgentWallet) -> Tuple[Optional[float], bool]:
    """
    Check Yellow ytest.usd balance. Returns (balance_usd, has_sufficient) or (None, False) if can't check.
    Gracefully handles errors (network, bridge unavailable, etc.).
    """
    try:
        from agentpay.payments.yellow import steps_1_to_3
        balances = steps_1_to_3(wallet)
        for bal in balances:
            if bal.get("asset") == "ytest.usd":
                amount_units = int(bal.get("amount", "0"))
                amount_usd = amount_units / 1_000_000  # ytest.usd uses 6 decimals
                has_sufficient = amount_units >= MIN_YTEST_USD_UNITS
                return amount_usd, has_sufficient
        return 0.0, False
    except Exception:
        # Bridge unavailable, network error, etc. - can't check; don't block worker startup
        return None, True


def request_sepolia_eth(address: str) -> Tuple[bool, str]:
    """
    Request Sepolia ETH from faucet (if API available).
    Returns (success, message).
    """
    # Most Sepolia faucets require manual interaction (captcha, etc.)
    # This is a placeholder - implement if you have API access
    return False, f"Manual funding required. Visit {SEPOLIA_FAUCET_URL} and send ETH to {address}"


def request_yellow_tokens(address: str) -> Tuple[bool, str]:
    """
    Request Yellow test tokens from faucet.
    Returns (success, message).
    """
    import requests
    try:
        response = requests.post(
            YELLOW_FAUCET_URL,
            json={"userAddress": address},
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        if response.status_code == 200:
            return True, "Yellow tokens requested successfully"
        return False, f"Faucet returned {response.status_code}: {response.text}"
    except Exception as e:
        return False, f"Faucet request failed: {e}"


def ensure_funded(
    wallet: AgentWallet,
    auto_fund: Optional[bool] = None,
    network: str = "sepolia",
) -> Tuple[bool, str]:
    """
    Check balances and prompt/request funding if needed.
    
    Args:
        wallet: Agent wallet to check
        auto_fund: If True, auto-request from faucets (testnet only). If None, uses AGENTPAY_AUTO_FUND_TESTNET env.
        network: "sepolia" (testnet) or "mainnet"
    
    Returns:
        (is_funded, message) - True if funded, False if needs funding
    
    Behavior:
        - Mainnet: Always prompts human (never auto-funds)
        - Testnet: If auto_fund=True, requests from faucets. Otherwise prompts human.
    """
    if auto_fund is None:
        auto_fund = AUTO_FUND_TESTNET and network == "sepolia"
    
    # Check ETH balance (gracefully handles network errors)
    eth_balance, eth_ok = check_eth_balance(wallet)
    
    # Check Yellow balance (testnet only, gracefully handles errors)
    yellow_balance, yellow_ok = check_yellow_balance(wallet) if network == "sepolia" else (None, True)
    
    # If we can't check balances (network error), assume needs funding to be safe
    if eth_balance == 0.0 and not eth_ok:
        # Network error - can't verify, so prompt user
        eth_ok = False
    
    if eth_ok and yellow_ok:
        return True, f"✅ Wallet funded: {eth_balance:.6f} ETH" + (f", {yellow_balance:.2f} ytest.usd" if yellow_balance is not None else "")
    
    # Needs funding
    messages = []
    needs_eth = not eth_ok
    needs_yellow = network == "sepolia" and not yellow_ok
    
    if needs_eth:
        eth_needed = MIN_ETH_WEI / 10**18
        messages.append(f"ETH: {eth_balance:.6f} ETH (need ~{eth_needed:.4f} ETH)")
    
    if needs_yellow:
        yellow_needed = MIN_YTEST_USD_UNITS / 1_000_000
        yellow_display = f"{yellow_balance:.2f}" if yellow_balance is not None else "0.00"
        messages.append(f"ytest.usd: {yellow_display} (need ~{yellow_needed:.2f})")
    
    message = f"⚠️  Wallet needs funding:\n  " + "\n  ".join(messages)
    message += f"\n  Address: {wallet.address}"
    
    if network == "mainnet":
        # Mainnet: Always prompt human
        message += "\n\n🔒 MAINNET: Manual funding required."
        message += f"\n  Send ETH to: {wallet.address}"
        message += "\n  (Never auto-fund on mainnet)"
        return False, message
    
    # Testnet: Can auto-fund or prompt
    if auto_fund:
        # Try to auto-fund
        message += "\n\n🤖 AUTO-FUNDING (testnet)..."
        
        if needs_eth:
            success, msg = request_sepolia_eth(wallet.address)
            if success:
                message += f"\n  ✅ ETH requested: {msg}"
            else:
                message += f"\n  ⚠️  ETH: {msg}"
        
        if needs_yellow:
            success, msg = request_yellow_tokens(wallet.address)
            if success:
                message += f"\n  ✅ Yellow tokens requested: {msg}"
            else:
                message += f"\n  ⚠️  Yellow: {msg}"
        
        # Check again after auto-fund attempt
        eth_balance_after, eth_ok_after = check_eth_balance(wallet)
        yellow_balance_after, yellow_ok_after = check_yellow_balance(wallet) if network == "sepolia" else (None, True)
        
        if eth_ok_after and yellow_ok_after:
            return True, message + "\n✅ Wallet funded after auto-request"
        else:
            return False, message + "\n⚠️  Still needs funding (faucet may require manual approval)"
    else:
        # Prompt human
        message += "\n\n💡 FUNDING OPTIONS:"
        message += f"\n  1. Manual: Visit {SEPOLIA_FAUCET_URL} → send ETH to {wallet.address}"
        if needs_yellow:
            message += f"\n  2. Yellow faucet: curl -X POST {YELLOW_FAUCET_URL} -H 'Content-Type: application/json' -d '{{\"userAddress\":\"{wallet.address}\"}}'"
        message += "\n  3. Auto-fund (testnet only): Set AGENTPAY_AUTO_FUND_TESTNET=true and retry"
        return False, message


def prompt_funding_choice(wallet: AgentWallet, network: str = "sepolia") -> str:
    """
    Interactive prompt: Ask human whether to auto-fund or manually fund.
    Returns user choice: "auto", "manual", or "skip"
    """
    eth_balance, eth_ok = check_eth_balance(wallet)
    yellow_balance, yellow_ok = check_yellow_balance(wallet) if network == "sepolia" else (None, True)
    
    if eth_ok and yellow_ok:
        return "skip"
    
    print(f"\n⚠️  Wallet {wallet.address} needs funding:")
    if not eth_ok:
        print(f"  ETH: {eth_balance:.6f} ETH (need ~{MIN_ETH_WEI / 10**18:.4f} ETH)")
    if network == "sepolia" and not yellow_ok:
        yellow_display = f"{yellow_balance:.2f}" if yellow_balance is not None else "0.00"
        print(f"  ytest.usd: {yellow_display} (need ~{MIN_YTEST_USD_UNITS / 1_000_000:.2f})")
    
    if network == "mainnet":
        print("\n🔒 MAINNET: Manual funding only.")
        print(f"  Send funds to: {wallet.address}")
        return "manual"
    
    print("\nChoose funding method:")
    print("  1. Auto-fund (I'll request from testnet faucets)")
    print("  2. Manual (I'll fund it myself)")
    print("  3. Skip (continue anyway, may fail)")
    
    choice = input("\nEnter choice (1/2/3): ").strip()
    if choice == "1":
        return "auto"
    elif choice == "2":
        return "manual"
    else:
        return "skip"
