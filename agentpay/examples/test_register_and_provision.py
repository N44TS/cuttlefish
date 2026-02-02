#!/usr/bin/env python3
"""
Test flow: register ENS then provision, then verify.

Uses ens2.py (built on ens_register_only.py) for register + provision;
uses ens.py for get_agent_info (verify) and env helpers.

Prerequisites (must use export so the script sees them):
  - export AGENTPAY_PRIVATE_KEY=0x... (wallet with Sepolia ETH)
  - export AGENTPAY_ENS_NAME=myagent123 (must be available on Sepolia)
  - Optional for provisioning:
      AGENTPAY_CAPABILITIES  (e.g. "analyze,summarize")
      AGENTPAY_ENDPOINT       (e.g. "https://myagent.com/submit-job")
      AGENTPAY_PRICES         (e.g. "0.05 USDC")

Usage (from repo root):
  export AGENTPAY_PRIVATE_KEY=0x...
  export AGENTPAY_ENS_NAME=myagent123
  python -m agentpay.examples.test_register_and_provision
  # Or with label:
  python -m agentpay.examples.test_register_and_provision myagent456
"""

import os
import sys
import time

_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _root not in sys.path:
    sys.path.insert(0, _root)

from agentpay import (
    AgentWallet,
    get_agent_info,
    get_ens_name_for_registration,
    get_agent_provisioning_from_env,
)
from agentpay.ens2 import register_ens_name, provision_ens_identity


def main():
    print("=== AgentPay: Test Register + Provision (ens2) ===\n")

    try:
        wallet = AgentWallet()
    except RuntimeError as e:
        print(f"❌ Wallet: {e}")
        print("   Export the key so this script sees it: export AGENTPAY_PRIVATE_KEY=0x...")
        return 1
    print(f"✓ Wallet: {wallet.address}")

    label = (sys.argv[1] if len(sys.argv) > 1 else None) or get_ens_name_for_registration()
    if not label:
        print("❌ No ENS name. Set AGENTPAY_ENS_NAME or pass label as first arg (e.g. myagent123).")
        return 1
    label = label.strip().lower().removesuffix(".eth")
    print(f"✓ ENS label: {label}")

    # Register (ens2)
    print("\n--- Register (ens2.register_ens_name) ---")
    ok, result = register_ens_name(wallet, label)
    if not ok:
        print(f"❌ Registration failed: {result}")
        return 1
    ens_name = result
    print(f"✓ Registered: {ens_name}")

    # Provision (ens2)
    caps, endpoint, prices = get_agent_provisioning_from_env()
    capabilities = caps or "analyze,summarize"
    endpoint = endpoint or ""
    prices = prices if (prices and prices != "N/A") else "N/A"
    print("\n--- Provision (ens2.provision_ens_identity) ---")
    time.sleep(2)
    ok, msg = provision_ens_identity(
        wallet,
        ens_name,
        capabilities=capabilities,
        endpoint=endpoint,
        prices=prices,
    )
    if not ok:
        print(f"❌ Provisioning failed: {msg}")
        return 1
    print(f"✓ Provisioned: {msg}")

    # Verify
    print("\n--- Verify (ens.get_agent_info) ---")
    time.sleep(3)
    info = get_agent_info(ens_name, mainnet=False)
    if not info:
        print(f"❌ Verification failed: no agent info for {ens_name}")
        return 1
    print("✓ Agent info found:")
    print(f"  name:         {info.get('name')}")
    print(f"  capabilities: {info.get('capabilities')}")
    print(f"  endpoint:     {info.get('endpoint')}")
    print(f"  prices:       {info.get('prices')}")

    print("\n=== Flow test passed ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
