"""
AgentPay CLI — Interactive commands for setting up and running agents.

Commands:
  agentpay setup    — Interactive setup: generate wallet, register ENS, provision endpoint
  agentpay worker   — Start worker server with interactive setup checks
"""
import os
import sys
from pathlib import Path
from typing import Optional

def setup_command():
    """Interactive setup: generate wallet, register ENS, provision endpoint."""
    print("╔═══════════════════════════════════════════════════════════════╗")
    print("║  AgentPay Setup — Let's get your agent ready!                ║")
    print("╚═══════════════════════════════════════════════════════════════╝\n")
    
    from agentpay import setup_new_agent, AgentWallet, register_and_provision_ens
    from agentpay.ens2 import get_ens_registration_quote
    
    # Step 1: Get ENS name
    ens_name = input("What ENS name should I use? (e.g., 'myagent' → registers 'myagent.eth'): ").strip()
    if not ens_name:
        ens_name = "myagent"
    ens_name = ens_name.lower().removesuffix(".eth")
    
    # Step 2: Generate wallet
    print(f"\n📦 Generating wallet for {ens_name}.eth...")
    wallet, instructions = setup_new_agent(ens_name)
    
    # Step 3: Ask user to fund — show exact amount and address
    try:
        total_wei, _ = get_ens_registration_quote(ens_name, duration_years=1.0)
        eth_amount = f"{total_wei / 10**18:.4f}"
    except Exception:
        eth_amount = "0.002"
    addr = wallet.address
    print("\n" + "="*70)
    print("💰 FUNDING REQUIRED")
    print("="*70)
    print(f"Send exactly this to your agent wallet:")
    print(f"  • {eth_amount} ETH (Sepolia) — for gas and ENS registration")
    print(f"  • Get ETH: https://sepoliafaucet.com")
    print(f"  • Send to this address: {addr}")
    print(f"\n  • Yellow test tokens (ytest.usd) — for receiving payments")
    print(f"  • Request: curl -X POST https://clearnet-sandbox.yellow.com/faucet/requestTokens -H 'Content-Type: application/json' -d '{{\"userAddress\":\"{addr}\"}}'")
    print("="*70)
    input("After you have sent ETH (and optionally requested ytest.usd), press Enter to continue...")
    
    # Step 4: Get endpoint
    print("\n" + "="*70)
    print("🌐 ENDPOINT CONFIGURATION")
    print("="*70)
    print("Where should other agents send jobs to you?")
    print("  Examples:")
    print("    - Codespace: https://your-codespace-8000.preview.app.github.dev")
    print("    - Local dev: http://localhost:8000")
    print("    - Your server: https://your-domain.com")
    endpoint = input("\nYour public endpoint URL: ").strip()
    
    if not endpoint:
        print("⚠️  No endpoint provided. You can set it later with:")
        print(f"   python -c \"from agentpay import AgentWallet, provision_ens_identity; w=AgentWallet(); provision_ens_identity(w, '{ens_name}', endpoint='YOUR_URL')\"")
        return
    
    # Step 5: Register and provision ENS
    print(f"\n📝 Registering {ens_name}.eth and setting up your agent profile...")
    capabilities = input("What can you do? (e.g., 'analyze-data,summarize'): ").strip() or "analyze-data"
    prices = input("Your prices? (e.g., '0.05 USDC per job'): ").strip() or "0.05 USDC per job"
    print("   (This may take 2-3 minutes for ENS registration to complete)")
    
    ok, result = register_and_provision_ens(
        wallet,
        ens_name,
        capabilities=capabilities,
        endpoint=endpoint,
        prices=prices,
    )
    
    if ok:
        ens_domain = result.replace(".eth", "")
        pk_hex = wallet._account.key.hex()
        # Save to .env so they don't have to copy-paste; same wallet works for both roles
        env_path = Path.cwd() / ".env"
        env_lines = [
            "# AgentPay — written by agentpay setup (do not commit; contains private key)",
            f"CLIENT_PRIVATE_KEY={pk_hex}",
            f"AGENTPAY_WORKER_PRIVATE_KEY={pk_hex}",
            f"AGENTPAY_ENS_NAME={result}",
            "",
        ]
        try:
            with open(env_path, "w") as f:
                f.write("\n".join(env_lines))
            saved_env = True
        except Exception:
            saved_env = False
        print(f"\n✅ Successfully provisioned '{result}'")
        print(f"🎉 Complete! '{result}' is registered and provisioned.")
        print(f"\n   You can check it out here: https://sepolia.app.ens.domains/{ens_domain}.eth")
        print(f"   ENS Name: {result}")
        print(f"   Wallet: {wallet.address}")
        print(f"   Endpoint: {endpoint}")
        if saved_env:
            print(f"\n   💾 Saved credentials to .env in this directory (key + ENS name). Do not commit .env.")
        # Yellow bridge: required for payments to work; do it as part of setup
        _pkg_dir = Path(__file__).resolve().parent
        _repo_root = _pkg_dir.parent
        _yellow_dir = _repo_root / "yellow_test"
        _bridge_ts = _yellow_dir / "bridge.ts"
        _node_modules = _yellow_dir / "node_modules"
        if _bridge_ts.exists() and not _node_modules.exists():
            print("\n" + "="*70)
            print("📦 YELLOW PAYMENT BRIDGE (required for pay/receive)")
            print("="*70)
            print("Installing Node dependencies for the payment bridge...")
            import subprocess
            try:
                subprocess.run(
                    ["npm", "install"],
                    cwd=_yellow_dir,
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                print("✅ Yellow bridge deps installed.")
            except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as e:
                print(f"⚠️  Could not run npm install: {e}")
                print(f"\nYou must run this before payments will work:")
                print(f"  cd {_yellow_dir}")
                print(f"  npm install")
                input("Press Enter after you have run the above, or Enter to continue anyway...")
        elif _bridge_ts.exists():
            print("\n✅ Yellow bridge ready (node_modules present).")
        print(f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"YOU CAN DO BOTH — receive work and give work (same wallet)")
        print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        if saved_env:
            print(f"\n► To start receiving work (get hired): run this from the same directory:")
            print(f"  agentpay worker")
            print(f"\n► To give work (hire another agent): run this, replacing otherbot.eth with their ENS name:")
            print(f"  WORKER_ENS_NAME=otherbot.eth python agentpay/examples/moltbot_demo.py")
        else:
            print(f"\n► To receive work:")
            print(f"  export CLIENT_PRIVATE_KEY={pk_hex}")
            print(f"  export AGENTPAY_ENS_NAME={result}")
            print(f"  agentpay worker")
            print(f"\n► To give work (hire another agent):")
            print(f"  export CLIENT_PRIVATE_KEY={pk_hex}")
            print(f"  WORKER_ENS_NAME=otherbot.eth python agentpay/examples/moltbot_demo.py")
        if saved_env:
            print(f"\n  Run from this directory so .env is loaded; no need to copy the key.")
    else:
        print(f"\n❌ Failed: {result}")
        print(f"\n💡 You can retry with:")
        print(f"   export CLIENT_PRIVATE_KEY={wallet._account.key.hex()}")
        print(f"   python -c \"from agentpay import AgentWallet, register_and_provision_ens; w=AgentWallet(); register_and_provision_ens(w, '{ens_name}', endpoint='{endpoint}')\"")


def worker_command():
    """Start worker server with interactive setup checks."""
    print("╔═══════════════════════════════════════════════════════════════╗")
    print("║  AgentPay Worker — Starting with setup checks...             ║")
    print("╚═══════════════════════════════════════════════════════════════╝\n")
    
    # Import here to avoid circular deps
    from agentpay import AgentWallet
    from agentpay.ens2 import get_agent_info, provision_ens_identity, register_and_provision_ens_from_env
    from agentpay.faucet import check_eth_balance, check_yellow_balance
    
    # Step 1: Check for wallet/key — use worker key if set, else same wallet as setup (CLIENT_PRIVATE_KEY)
    worker_key = os.getenv("AGENTPAY_WORKER_PRIVATE_KEY")
    worker_wallet_addr = os.getenv("AGENTPAY_WORKER_WALLET")
    client_key = os.getenv("CLIENT_PRIVATE_KEY") or os.getenv("AGENTPAY_PRIVATE_KEY")
    
    if not worker_key and not worker_wallet_addr:
        if client_key:
            # Same agent: use the wallet from setup so "agentpay worker" works right after setup
            os.environ["AGENTPAY_WORKER_PRIVATE_KEY"] = client_key.strip()
            worker_key = client_key
        else:
            print("❌ No worker wallet found!")
            print("   If you just ran 'agentpay setup', set your key first:")
            print("   export CLIENT_PRIVATE_KEY=0x...   # (from setup output)")
            print("   Then run: agentpay worker")
            choice = input("\nGenerate a new wallet? (y/n): ").strip().lower()
            if choice == 'y':
                from agentpay.wallet import generate_keypair
                account = generate_keypair()
                private_key_hex = account.key.hex()
                print(f"\n✅ Generated wallet:")
                print(f"   Address: {account.address}")
                print(f"   Private Key: {private_key_hex}")
                print(f"\n💡 Set this in your environment:")
                print(f"   export AGENTPAY_WORKER_PRIVATE_KEY={private_key_hex}")
                print(f"\n⚠️  Restart the worker after setting the key.")
                sys.exit(1)
            else:
                print("❌ Set CLIENT_PRIVATE_KEY (from setup) or AGENTPAY_WORKER_PRIVATE_KEY")
                sys.exit(1)
    
    # Create wallet to check it: prefer AgentWallet (CLIENT_PRIVATE_KEY), else worker key
    try:
        if client_key or os.getenv("AGENTPAY_PRIVATE_KEY"):
            wallet = AgentWallet()
            worker_address = wallet.address
        else:
            from eth_account import Account
            pk = (os.getenv("AGENTPAY_WORKER_PRIVATE_KEY") or "").strip()
            if not pk.startswith("0x"):
                pk = "0x" + pk
            account = Account.from_key(pk)
            worker_address = account.address
            # Minimal wallet-like object for balance checks
            class _WorkerWallet:
                address = account.address
            wallet = _WorkerWallet()
    except Exception as e:
        print(f"❌ Failed to load wallet: {e}")
        sys.exit(1)
    
    print(f"✅ Wallet loaded: {worker_address}")
    
    # Step 2: Check funding
    print("\n💰 Checking wallet balance...")
    eth_balance, eth_ok = check_eth_balance(wallet)
    yellow_balance, yellow_ok = check_yellow_balance(wallet)
    
    if not eth_ok or not yellow_ok:
        print("⚠️  Wallet needs funding:")
        if not eth_ok:
            print(f"   ETH: send Sepolia ETH to {worker_address} (get from https://sepoliafaucet.com)")
        if not yellow_ok:
            print(f"   ytest.usd: request from Yellow faucet for {worker_address}")
        input("\nPress Enter after funding, or Ctrl+C to exit...")
    
    # Step 3: Check ENS registration
    ens_name = os.getenv("AGENTPAY_ENS_NAME", "").strip().removesuffix(".eth")
    if not ens_name:
        ens_name = input("\nWhat's your ENS name? (e.g., 'myagent'): ").strip().removesuffix(".eth")
        if ens_name:
            os.environ["AGENTPAY_ENS_NAME"] = ens_name
    
    if ens_name:
        print(f"\n📝 Checking ENS setup for {ens_name}.eth...")
        try:
            info = get_agent_info(f"{ens_name}.eth", mainnet=False)
            endpoint = info.get("endpoint") if info else None
            
            if not endpoint:
                print(f"⚠️  {ens_name}.eth exists but has no endpoint set!")
                endpoint = input("What's your public endpoint URL? (e.g., https://your-codespace-8000.preview.app.github.dev): ").strip()
                if endpoint:
                    print(f"📝 Setting endpoint in ENS...")
                    ok, msg = provision_ens_identity(
                        wallet,
                        f"{ens_name}.eth",
                        endpoint=endpoint,
                    )
                    if ok:
                        print(f"✅ Endpoint set: {endpoint}")
                    else:
                        print(f"❌ Failed to set endpoint: {msg}")
            else:
                print(f"✅ ENS configured: endpoint = {endpoint}")
        except Exception as e:
            print(f"⚠️  ENS check failed: {e}")
            print("   Continuing anyway...")
    else:
        print("⚠️  No ENS name configured. Other agents won't be able to find you via ENS.")
        print("   Set AGENTPAY_ENS_NAME or run 'agentpay setup' first.")
    
    # Step 4: Start worker server
    print("\n" + "="*70)
    print("🚀 Starting worker server...")
    print("="*70)
    print(f"   Wallet: {worker_address}")
    if ens_name:
        print(f"   ENS: {ens_name}.eth")
    pay_method = os.getenv("AGENTPAY_PAYMENT_METHOD", "yellow_chunked_full")
    print(f"   Payment method: {pay_method}")
    print(f"   Port: {os.getenv('PORT', os.getenv('AGENTPAY_PORT', '8000'))}")
    # Yellow payments need the bridge; ensure node_modules exists so clients can pay
    if "yellow" in (pay_method or "").lower():
        _pkg_dir_pre = Path(__file__).resolve().parent
        _root_pre = _pkg_dir_pre.parent
        _yellow_dir = _root_pre / "yellow_test"
        _bridge_ts = _yellow_dir / "bridge.ts"
        _node_modules = _yellow_dir / "node_modules"
        if _bridge_ts.exists() and not _node_modules.exists():
            print("\n⚠️  Yellow bridge needs Node deps. Before a client can pay you, run:")
            print(f"     cd {_yellow_dir} && npm install")
            print()
    print("\n✅ Worker is ready! Waiting for jobs...\n")
    
    # Import and run worker server
    # agentpay/cli.py -> parent = agentpay pkg dir, so examples live at agentpay/examples/
    _pkg_dir = Path(__file__).resolve().parent
    _root = _pkg_dir.parent  # repo root (for sys.path)
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))
    
    # Worker script lives inside the agentpay package: agentpay/examples/worker_server.py
    worker_server_file = _pkg_dir / "examples" / "worker_server.py"
    
    # Read and exec the worker_server.py to get the app
    # This ensures the path setup in worker_server.py runs
    import importlib.util
    spec = importlib.util.spec_from_file_location("worker_server", worker_server_file)
    worker_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker_module)
    app = worker_module.app
    
    import uvicorn
    
    port = int(os.getenv("PORT", os.getenv("AGENTPAY_PORT", "8000")))
    uvicorn.run(app, host="0.0.0.0", port=port)


def main():
    """CLI entry point."""
    if len(sys.argv) < 2:
        print("AgentPay CLI")
        print("\nCommands:")
        print("  agentpay setup    — Interactive setup: generate wallet, register ENS")
        print("  agentpay worker   — Start worker server with setup checks")
        print("\nExamples:")
        print("  agentpay setup")
        print("  agentpay worker")
        sys.exit(1)
    
    command = sys.argv[1]
    
    if command == "setup":
        setup_command()
    elif command == "worker":
        worker_command()
    else:
        print(f"Unknown command: {command}")
        print("Use 'agentpay setup' or 'agentpay worker'")
        sys.exit(1)


if __name__ == "__main__":
    main()
