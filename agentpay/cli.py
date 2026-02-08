"""
AgentPay CLI — Interactive commands for setting up and running agents.

Commands:
  agentpay setup    — Interactive setup: generate wallet, register ENS, provision endpoint
  agentpay worker   — Start worker server with setup checks
  agentpay client   — Send a job and pay a worker (no exports if .env present)
"""
import os
import sys
from pathlib import Path
from typing import Optional

def _load_dotenv():
    """Load .env from cwd so setup/worker/client use it without manual exports."""
    try:
        from dotenv import load_dotenv
        load_dotenv(Path.cwd() / ".env", override=False)
    except ImportError:
        pass


def _ens_name_from_env_file(env_path: Optional[Path] = None) -> str:
    """Read AGENTPAY_ENS_NAME from .env file directly to avoid truncation (e.g. 13-char limit)."""
    path = env_path or Path.cwd() / ".env"
    if not path.exists():
        return ""
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line.startswith("AGENTPAY_ENS_NAME="):
                val = line.split("=", 1)[1].strip().strip('"\'')
                val = val.replace("\r", "").replace("\n", "").strip().removesuffix(".eth")
                return val
    except Exception:
        pass
    return ""


def _try_add_openclaw_to_env(env_path: Path) -> None:
    """If user says yes, read OpenClaw config and add OPENCLAW_GATEWAY_* to .env so no manual export."""
    try:
        use = input("\nUse OpenClaw so your bot does real work when jobs come in? (y/n): ").strip().lower()
        if use != "y":
            return
    except Exception:
        return
    config_paths = [
        Path.home() / ".openclaw" / "openclaw.json",
        Path.home() / ".clawdbot" / "clawdbot.json",
    ]
    config = None
    for p in config_paths:
        if p.exists():
            try:
                import json
                config = json.loads(p.read_text())
                break
            except Exception:
                continue
    if not config:
        print("   OpenClaw config not found. Add OPENCLAW_GATEWAY_URL and OPENCLAW_GATEWAY_TOKEN to .env later if you use OpenClaw.")
        print("   See agentpay/docs/OPENCLAW_SETUP.md Part 5.")
        return
    gateway = config.get("gateway") or {}
    auth = gateway.get("auth") or {}
    token = (auth.get("token") or auth.get("password") or "").strip()
    port = gateway.get("port", 18789)
    if not token:
        print("   No gateway token in OpenClaw config. Add OPENCLAW_GATEWAY_TOKEN to .env later.")
        return
    url = f"http://127.0.0.1:{port}"
    try:
        with open(env_path, "a") as f:
            f.write(f"\n# OpenClaw — worker asks your bot to do jobs\n")
            f.write(f"OPENCLAW_GATEWAY_URL={url}\n")
            f.write(f"OPENCLAW_GATEWAY_TOKEN={token}\n")
        print("   ✅ Added OpenClaw gateway URL and token to .env (no manual export needed).")
        print("   If the gateway HTTP API is off, run once: openclaw config set gateway.http.endpoints.chatCompletions.enabled true")
        print("   Then restart the gateway (openclaw gateway).")
    except Exception as e:
        print(f"   Could not append to .env: {e}. Add OPENCLAW_GATEWAY_URL and OPENCLAW_GATEWAY_TOKEN yourself.")

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
        # OpenClaw: so the worker asks the real bot to do jobs (plug-and-play)
        if saved_env:
            _try_add_openclaw_to_env(env_path)
        print(f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"YOU CAN DO BOTH — receive work and give work (same wallet)")
        print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        if saved_env:
            print(f"\n► To start receiving work (get hired): run from this directory:")
            print(f"  agentpay worker")
            print(f"\n► To give work (hire another agent): in a new terminal, set the payer's key then:")
            print(f"  export CLIENT_PRIVATE_KEY=0x...   # payer's key (must be different from worker's key!)")
            print(f"  agentpay client otherbot.eth")
        else:
            print(f"\n► To receive work:")
            print(f"  export CLIENT_PRIVATE_KEY={pk_hex}")
            print(f"  export AGENTPAY_ENS_NAME={result}")
            print(f"  agentpay worker")
            print(f"\n► To give work (hire another agent):")
            print(f"  export CLIENT_PRIVATE_KEY=0x...   # payer's key")
            print(f"  agentpay client otherbot.eth")
        if saved_env:
            print(f"\n  Run worker from this directory so .env is loaded.")
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
        # Re-check so we show current balance (Yellow may have been temporarily unavailable)
        eth_balance, eth_ok = check_eth_balance(wallet)
        yellow_balance, yellow_ok = check_yellow_balance(wallet)
        if yellow_balance is not None or eth_ok:
            print(f"   Balance now: {eth_balance:.4f} ETH" + (f", {yellow_balance:.2f} ytest.usd" if yellow_balance is not None else ""))

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
    balance_line = f"   Balance: {eth_balance:.4f} ETH" + (f", {yellow_balance:.2f} ytest.usd" if yellow_balance is not None else "")
    print("\n✅ Worker is ready! Waiting for jobs...")
    print(balance_line)
    print()
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("NEXT STEP — Send a job from another terminal (client)")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("1. Open a NEW terminal (keep this worker running).")
    print("2. Export the PAYER's key (the client who pays — must be a different address to workers):")
    print("   export CLIENT_PRIVATE_KEY=0x...")
    print(f"3. Run:")
    _ens = f"{ens_name}.eth" if ens_name else "worker.eth"
    print(f"   agentpay client {_ens}")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")
    
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


def client_command():
    """Send a job and pay a worker (hire an agent). Loads .env from cwd; worker ENS from arg or env, or hire by capability."""
    _load_dotenv()
    # Hire by capability: agentpay client --by-capability analyze-data (uses AGENTPAY_KNOWN_AGENTS)
    by_capability = "--by-capability" in sys.argv
    capability = "analyze-data"
    known_agents_raw = (os.getenv("AGENTPAY_KNOWN_AGENTS") or "").strip()
    if by_capability:
        idx = sys.argv.index("--by-capability")
        if idx + 1 < len(sys.argv) and not sys.argv[idx + 1].startswith("-"):
            capability = sys.argv[idx + 1].strip()
        known_agents = [(a.strip() if a.strip().endswith(".eth") else a.strip() + ".eth") for a in known_agents_raw.split(",") if a.strip()]
        if not known_agents:
            print("Usage: agentpay client --by-capability <capability>")
            print("  Set AGENTPAY_KNOWN_AGENTS=worker1.eth,worker2.eth (comma-separated ENS names to try).")
            print("  Worker ENS must have agentpay.capabilities set (e.g. 'analyze-data') via provision.")
            sys.exit(1)
    else:
        worker_ens = (sys.argv[2] if len(sys.argv) > 2 else os.getenv("WORKER_ENS_NAME", "")).strip().removesuffix(".eth")
        if worker_ens:
            worker_ens = f"{worker_ens}.eth" if not worker_ens.endswith(".eth") else worker_ens
        if not worker_ens:
            print("Usage: agentpay client <worker.eth>")
            print("  Or: agentpay client --by-capability analyze-data (with AGENTPAY_KNOWN_AGENTS=ens.eth)")
            print("  Or set WORKER_ENS_NAME in .env and run: agentpay client")
            sys.exit(1)
    if not os.getenv("CLIENT_PRIVATE_KEY") and not os.getenv("AGENTPAY_PRIVATE_KEY"):
        print("❌ No CLIENT_PRIVATE_KEY. Run from the directory where you ran 'agentpay setup' (so .env is loaded), or export CLIENT_PRIVATE_KEY=0x...")
        sys.exit(1)
    from agentpay import AgentWallet, hire_agent
    from agentpay.payments import get_pay_fn
    print("=" * 70)
    print("AgentPay Client — Hiring agent via ENS")
    print("=" * 70)
    if by_capability:
        print(f"  Mode: hire by capability '{capability}' (known_agents: {known_agents})")
    else:
        print(f"  Worker: {worker_ens}")
    wallet = AgentWallet()
    print(f"  Payer:  {wallet.address}\n")
    print("  → Worker will return 402 + Bill")
    print("  → You pay via Yellow (session + on-chain settlement)")
    print("  → Worker verifies payment, does work, returns result\n")
    if by_capability:
        result = hire_agent(
            wallet,
            task_type=capability,
            input_data={"query": "Summarize this for the demo"},
            capability=capability,
            known_agents=known_agents,
            job_id="agentpay_client_001",
            pay_fn=get_pay_fn("yellow_full"),
        )
    else:
        result = hire_agent(
            wallet,
            task_type="analyze-data",
            input_data={"query": "Summarize this for the demo"},
            worker_ens_name=worker_ens,
            job_id="agentpay_client_001",
            pay_fn=get_pay_fn("yellow_full"),
        )
    print("\n" + "=" * 70)
    if result.status == "completed":
        print("✅ Result:", result.result or "(ok)")
        tx = getattr(result, "payment_tx_hash", None)
        if tx:
            print(f"   Tx: https://sepolia.etherscan.io/tx/{tx}")
    else:
        print("❌ Failed:", result.error or result.status)
        sys.exit(1)
    print("=" * 70)


def demo_feed_command():
    """Start the demo feed server so two Moltbots can share offers/accepts (no Moltbook API key)."""
    _load_dotenv()
    import sys
    from pathlib import Path
    _root = Path(__file__).resolve().parent.parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))
    from autonomous_adapter.demo_feed_server import main as serve_feed
    print("Starting demo feed (use AGENTPAY_DEMO_FEED_URL in both Moltbots to point here).")
    serve_feed()


def autonomous_worker_command():
    """Start worker server + autonomous loop: watch feed, reply to offers with ENS."""
    _load_dotenv()
    import threading
    from pathlib import Path
    _root = Path(__file__).resolve().parent.parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))
    try:
        from autonomous_adapter import run_autonomous_agent, build_demo_config
    except ImportError as e:
        print("autonomous_adapter required. Run from repo root: pip install -e .")
        sys.exit(1)
    # Prefer .env file (cwd then repo root) so ENS is not truncated by shell (e.g. 13-char export limit)
    ens_name = _ens_name_from_env_file(Path.cwd() / ".env") or _ens_name_from_env_file(_root / ".env")
    if not ens_name:
        ens_name = (os.getenv("AGENTPAY_ENS_NAME") or "").strip().removesuffix(".eth").replace("\r", "").replace("\n", "").strip()
    if not ens_name:
        ens_name = "worker"
    config = build_demo_config("worker", my_ens=ens_name, poll_interval_seconds=20)
    daemon = threading.Thread(target=run_autonomous_agent, args=(config,), daemon=True)
    daemon.start()
    print("Autonomous mode: worker server + background feed watcher.")
    print("  • AGENTPAY_DEMO_FEED_URL = where to watch for offers (e.g. http://localhost:8765 — run agentpay demo-feed there).")
    print("  • OpenClaw = who does the job (OPENCLAW_GATEWAY_* in .env; run 'openclaw gateway' in another terminal).")
    print("Starting worker server...")
    worker_command()


def autonomous_client_command():
    """Run autonomous client: post one offer, watch for one accept, trigger hire, then exit."""
    _load_dotenv()
    from pathlib import Path
    _root = Path(__file__).resolve().parent.parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))
    if not os.getenv("CLIENT_PRIVATE_KEY") and not os.getenv("AGENTPAY_PRIVATE_KEY"):
        print("CLIENT_PRIVATE_KEY required for client (payer). Set in .env or export.")
        sys.exit(1)
    # Only warn if both keys are in env and they're the same address
    try:
        from eth_account import Account
        pk = (os.getenv("CLIENT_PRIVATE_KEY") or os.getenv("AGENTPAY_PRIVATE_KEY") or "").strip()
        worker_pk = (os.getenv("AGENTPAY_WORKER_PRIVATE_KEY") or "").strip()
        if pk and worker_pk:
            client_addr = Account.from_key(pk).address.lower()
            worker_addr = Account.from_key(worker_pk).address.lower()
            if client_addr == worker_addr:
                print("⚠️  Client and worker are the same wallet. Use a different CLIENT_PRIVATE_KEY (payer) for the client.")
    except Exception:
        pass
    try:
        from autonomous_adapter import run_autonomous_agent, build_demo_config
    except ImportError as e:
        print("autonomous_adapter required. Run from repo root: pip install -e .")
        sys.exit(1)
    url = os.getenv("AGENTPAY_DEMO_FEED_URL", "").strip()
    if not url:
        print("Set AGENTPAY_DEMO_FEED_URL to the demo feed URL (e.g. http://localhost:8765)")
        print("Start the feed with: agentpay demo-feed")
        sys.exit(1)
    ens_name = (os.getenv("AGENTPAY_ENS_NAME") or "client").strip().removesuffix(".eth").replace("\r", "").replace("\n", "").strip()
    offer_store = {}
    # One real-looking job: summarize article (~500 words for demo).
    medical_query = (
        "Summarise this medical article in 2-3 sentences:\n\n"
        "Hypertension (high blood pressure) affects approximately one in three adults worldwide and is a major risk factor for cardiovascular disease, stroke, and kidney failure. "
        "Key interventions include lifestyle modification (reduced sodium intake, weight management, regular exercise, and moderation of alcohol) and antihypertensive drug therapy when needed. "
        "Clinical guidelines recommend regular BP monitoring, stepped care with combination therapy if targets are not met, and attention to comorbidities such as diabetes and chronic kidney disease. "
        "Early detection and consistent management significantly reduce the risk of long-term complications. "
        "Population-level strategies include public health campaigns to reduce dietary salt, screening programmes in primary care, and adherence support for prescribed regimens. "
        "Resistant hypertension (uncontrolled despite three or more drugs) may require specialist workup for secondary causes and consideration of device-based therapies. "
        "Blood pressure targets vary by age and comorbidity; recent trials support more intensive targets in many higher-risk patients. "
        "International guidelines are broadly aligned on the importance of out-of-office monitoring (ambulatory or home) to confirm the diagnosis and guide treatment. "
        "Primary hypertension has no single identifiable cause and is influenced by genetics, diet, physical inactivity, obesity, and stress. "
        "Secondary hypertension can result from renal artery stenosis, primary aldosteronism, pheochromocytoma, thyroid disorders, or obstructive sleep apnoea; screening is recommended when onset is sudden, severe, or resistant to treatment. "
        "Lifestyle changes can lower systolic BP by roughly 5–10 mmHg and are first-line for all patients; the DASH diet, weight loss of 5–10% in overweight individuals, and at least 150 minutes of moderate activity per week are commonly recommended. "
        "First-line drug classes include ACE inhibitors, angiotensin receptor blockers, calcium channel blockers, and thiazide or thiazide-like diuretics; choice depends on age, ethnicity, comorbidities, and tolerability. "
        "Combination therapy is often needed; single-pill combinations improve adherence. "
        "Target BP in most adults is below 140/90 mmHg; in those with diabetes, CKD, or high cardiovascular risk, targets of 130/80 mmHg or lower may apply. "
        "White-coat and masked hypertension are common; ambulatory or home BP monitoring helps avoid misclassification and overtreatment or undertreatment. "
        "Pregnancy-related hypertension (gestational hypertension, pre-eclampsia) requires close monitoring and may need delivery for maternal or fetal safety. "
        "In children and adolescents, hypertension is defined by percentiles for age, sex, and height; causes include obesity and renal or cardiac disease. "
        "Patient education on self-monitoring, medication adherence, and when to seek help improves outcomes. "
        "Quality improvement in primary care—audit, reminders, and pharmacist-led titration—increases the proportion of patients at target."
    )
    initial = {
        "task_type": "summarize article",
        "price": "0.05 AP",
        "input_data": {"query": medical_query},
        "input_ref": "Summarise article (see query in job)",
        "poster_ens": ens_name,
    }
    config = build_demo_config("client", my_ens=ens_name, offer_store=offer_store, poll_interval_seconds=20, initial_offer=initial)
    config["exit_after_first_accept"] = True
    print("Autonomous client: posting one offer (summarize article), watching for one accept, then hiring and exiting...")
    run_autonomous_agent(config)
    hire_result = config.get("_hire_result") or {}
    if hire_result.get("completed"):
        print("\n✅ Client finished: one job posted, one hire completed, exiting.")
        outcome = hire_result.get("result")
        if outcome is not None:
            print("\n--- Result from worker (bot's answer) ---")
            if isinstance(outcome, str):
                print(outcome)
            else:
                print(outcome)
            print("---")
    else:
        err = hire_result.get("error") or "hire did not complete"
        print(f"\n⚠️ Client finished: job posted and accept seen, but hire did not complete: {err}")


def install_skill_command():
    """Install the AgentPay skill into OpenClaw so the bot sees it (skills list, hire/work/status)."""
    import json
    import shutil
    _load_dotenv()
    # Find skills/agentpay: repo root is parent of agentpay/ (where cli.py lives), or cwd
    repo_root = Path(__file__).resolve().parent.parent
    skill_src = repo_root / "skills" / "agentpay"
    if not (skill_src.exists() and (skill_src / "SKILL.md").exists()):
        skill_src = Path.cwd() / "skills" / "agentpay"
    if not (skill_src.exists() and (skill_src / "SKILL.md").exists()):
        print("AgentPay skill not found at skills/agentpay/. Run from the repo root (where skills/ lives).")
        sys.exit(1)
    dest_dir = Path.home() / ".openclaw" / "skills"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "agentpay"
    try:
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(skill_src, dest)
        print(f"Installed skill: {dest}")
    except Exception as e:
        print(f"Failed to copy skill: {e}")
        sys.exit(1)
    # Only set skills.entries.agentpay.enabled — do not touch skills.load.extraDirs (can break OpenClaw's skill list)
    config_path = Path.home() / ".openclaw" / "openclaw.json"
    try:
        if config_path.exists():
            config = json.loads(config_path.read_text())
        else:
            config = {}
        skills = config.setdefault("skills", {})
        entries = skills.setdefault("entries", {})
        entries["agentpay"] = entries.get("agentpay") or {}
        if not isinstance(entries["agentpay"], dict):
            entries["agentpay"] = {}
        entries["agentpay"]["enabled"] = True
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(config, indent=2))
        print(f"Updated {config_path} (skills.entries.agentpay.enabled = true)")
    except Exception as e:
        print(f"Could not update openclaw.json: {e}. You may need to add agentpay manually (see agentpay/docs/OPENCLAW_SETUP.md).")
    print("\nNext: Run 'openclaw skills list' to verify. Restart the gateway (or start a new chat) so the skill appears.")


def main():
    """CLI entry point."""
    _load_dotenv()
    if len(sys.argv) < 2:
        print("AgentPay CLI")
        print("\nCommands:")
        print("  agentpay setup    — Interactive setup: generate wallet, register ENS")
        print("  agentpay worker   — Start worker server with setup checks")
        print("  agentpay client   — Send a job and pay a worker (e.g. agentpay client worker.eth)")
        print("  agentpay demo-feed       — Start demo feed server (for autonomous demo)")
        print("  agentpay autonomous-worker — Worker + watch feed, reply to offers")
        print("  agentpay autonomous-client — Client: post offer, watch for accepts, pay")
        print("  agentpay install-skill — Install AgentPay skill into OpenClaw (so the bot sees it)")
        print("\nExamples:")
        print("  agentpay setup")
        print("  agentpay worker")
        print("  agentpay client finaltestcuttlepls.eth")
        sys.exit(1)
    
    command = sys.argv[1]
    
    if command == "setup":
        setup_command()
    elif command == "worker":
        worker_command()
    elif command == "client":
        client_command()
    elif command == "demo-feed":
        demo_feed_command()
    elif command == "autonomous-worker":
        autonomous_worker_command()
    elif command == "autonomous-client":
        autonomous_client_command()
    elif command == "install-skill":
        install_skill_command()
    else:
        print(f"Unknown command: {command}")
        print("Use 'agentpay setup', 'agentpay worker', 'agentpay client <worker.eth>', 'agentpay demo-feed', 'agentpay autonomous-worker', 'agentpay autonomous-client', 'agentpay install-skill'")
        sys.exit(1)


if __name__ == "__main__":
    main()
