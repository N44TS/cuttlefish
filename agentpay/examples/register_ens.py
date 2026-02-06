#!/usr/bin/env python3
"""
Quick script to register and provision an ENS name.

Usage:
  export CLIENT_PRIVATE_KEY=0x...
  python3 agentpay/examples/register_ens.py <label> [--endpoint <url>] [--capabilities <caps>] [--prices <prices>]

Example:
  python3 agentpay/examples/register_ens.py testcuttlefish8000 --endpoint http://localhost:8000 --capabilities analyze-data,summarize --prices "0.05 USDC per job"
"""

import sys
import argparse
from agentpay import AgentWallet, register_and_provision_ens


def main():
    parser = argparse.ArgumentParser(description="Register and provision ENS name")
    parser.add_argument("label", help="ENS label (without .eth suffix)")
    parser.add_argument("--endpoint", default="http://localhost:8000", help="Worker endpoint URL")
    parser.add_argument("--capabilities", default="analyze-data,summarize", help="Comma-separated capabilities")
    parser.add_argument("--prices", default="0.05 USDC per job", help="Price string")
    
    args = parser.parse_args()
    
    wallet = AgentWallet()
    print(f"Using wallet: {wallet.address}")
    print(f"Registering '{args.label}.eth'...")
    
    ok, result = register_and_provision_ens(
        wallet,
        args.label,
        capabilities=args.capabilities,
        endpoint=args.endpoint,
        prices=args.prices,
    )
    
    if ok:
        print(f"✅ Successfully registered: {result}")
    else:
        print(f"❌ Failed: {result}")
        sys.exit(1)


if __name__ == "__main__":
    main()
