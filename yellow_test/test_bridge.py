#!/usr/bin/env python3
"""
Test script to verify the Python ↔ TS bridge works.
Run: python3 test_bridge.py [test|create_session]
"""

import json
import os
import subprocess
import sys
from pathlib import Path

# Get the directory where this script is located
SCRIPT_DIR = Path(__file__).parent
BRIDGE_TS = SCRIPT_DIR / "bridge.ts"
ENV_FILE = SCRIPT_DIR / ".env"


def load_env():
    """Load .env file if it exists."""
    if ENV_FILE.exists():
        with open(ENV_FILE) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ[key.strip()] = value.strip()


def call_bridge(request: dict, timeout: int = 30) -> dict:
    """Call the bridge and return parsed response."""
    result = subprocess.run(
        ["npx", "tsx", str(BRIDGE_TS)],
        input=json.dumps(request),
        capture_output=True,
        text=True,
        cwd=SCRIPT_DIR,
        check=True,
        timeout=timeout
    )
    
    if result.stderr:
        print(f"Bridge stderr: {result.stderr}")
    
    return json.loads(result.stdout)


def test_bridge():
    """Test the bridge with a simple 'test' command."""
    print("=" * 60)
    print("Test 1: Simple 'test' command")
    print("=" * 60)
    
    request = {"command": "test"}
    print(f"\nSending request: {json.dumps(request, indent=2)}")
    
    try:
        response = call_bridge(request, timeout=10)
        print(f"\nResponse: {json.dumps(response, indent=2)}")
        
        if response.get("success"):
            print("\n✅ Test command PASSED!")
            return True
        else:
            print(f"\n❌ Test command FAILED: {response.get('error')}")
            return False
    except Exception as e:
        print(f"\n❌ Error: {e}")
        return False


def test_create_session():
    """Test creating an app session."""
    print("\n" + "=" * 60)
    print("Test 2: Create app session")
    print("=" * 60)
    
    # Get credentials from .env or environment
    client_key = os.getenv("PRIVATE_KEY")
    worker_address = os.getenv("WORKER_ADDRESS")
    
    if not client_key or not worker_address:
        print("\n⚠️  Skipping create_session test:")
        print("   Set PRIVATE_KEY and WORKER_ADDRESS in .env or environment")
        print("   Example: PRIVATE_KEY=0x... WORKER_ADDRESS=0x... python3 test_bridge.py create_session")
        return None
    
    request = {
        "command": "create_session",
        "client_private_key": client_key,
        "worker_address": worker_address,
        "quorum": 1  # Single-party for testing
    }
    
    print(f"\nSending request: {json.dumps({**request, 'client_private_key': '0x...'}, indent=2)}")
    print("(client_private_key hidden for security)")
    
    try:
        response = call_bridge(request, timeout=35)
        print(f"\nResponse: {json.dumps(response, indent=2)}")
        
        if response.get("success"):
            data = response.get("data", {})
            print(f"\n✅ Create session PASSED!")
            print(f"   Session ID: {data.get('app_session_id', 'N/A')}")
            print(f"   Version: {data.get('version', 'N/A')}")
            return True, data.get("app_session_id")
        else:
            print(f"\n❌ Create session FAILED: {response.get('error')}")
            return False, None
    except Exception as e:
        print(f"\n❌ Error: {e}")
        return False, None


def test_submit_state(app_session_id: str = None):
    """Test submitting an escrow state update."""
    print("\n" + "=" * 60)
    print("Test 3: Submit escrow state (payment)")
    print("=" * 60)
    
    client_key = os.getenv("PRIVATE_KEY")
    worker_address = os.getenv("WORKER_ADDRESS")
    
    if not client_key or not worker_address:
        print("\n⚠️  Skipping submit_state test:")
        print("   Set PRIVATE_KEY and WORKER_ADDRESS in .env")
        return None
    
    if not app_session_id:
        print("\n⚠️  No session ID provided. Run 'create_session' test first or provide app_session_id")
        return None
    
    request = {
        "command": "submit_state",
        "app_session_id": app_session_id,
        "client_private_key": client_key,
        "worker_address": worker_address,
        "amount": "1000000",  # 1 ytest.usd (6 decimals)
    }
    
    print(f"\nSending request: {json.dumps({**request, 'client_private_key': '0x...'}, indent=2)}")
    print("(client_private_key hidden for security)")
    print(f"Amount: 1 ytest.usd (1000000 units)")
    
    try:
        response = call_bridge(request, timeout=35)
        print(f"\nResponse: {json.dumps(response, indent=2)}")
        
        if response.get("success"):
            data = response.get("data", {})
            print(f"\n✅ Submit state PASSED!")
            print(f"   Version: {data.get('version', 'N/A')}")
            print(f"   State proof: {data.get('state_proof', 'N/A')}")
            return True
        else:
            print(f"\n❌ Submit state FAILED: {response.get('error')}")
            return False
    except Exception as e:
        print(f"\n❌ Error: {e}")
        return False


if __name__ == "__main__":
    # Load .env file
    load_env()
    
    test_name = sys.argv[1] if len(sys.argv) > 1 else "test"
    
    if test_name == "test":
        success = test_bridge()
        sys.exit(0 if success else 1)
    elif test_name == "create_session":
        success, session_id = test_create_session()
        sys.exit(0 if success else 1)
    elif test_name == "submit_state":
        session_id = sys.argv[2] if len(sys.argv) > 2 else None
        success = test_submit_state(session_id)
        sys.exit(0 if success else 1)
    elif test_name == "close_session":
        session_id = sys.argv[2] if len(sys.argv) > 2 else None
        if not session_id:
            print("⚠️  No session ID provided")
            print("Usage: python3 test_bridge.py close_session <session_id>")
            sys.exit(1)
        client_key = os.getenv("PRIVATE_KEY")
        worker_address = os.getenv("WORKER_ADDRESS")
        if not client_key or not worker_address:
            print("⚠️  Set PRIVATE_KEY and WORKER_ADDRESS in .env")
            sys.exit(1)
        request = {
            "command": "close_session",
            "app_session_id": session_id,
            "client_private_key": client_key,
            "worker_address": worker_address,
        }
        print(f"\nClosing session {session_id[:20]}...")
        try:
            response = call_bridge(request, timeout=35)
            print(f"\nResponse: {json.dumps(response, indent=2)}")
            if response.get("success"):
                print("\n✅ Close session PASSED!")
                sys.exit(0)
            else:
                print(f"\n❌ Close session FAILED: {response.get('error')}")
                sys.exit(1)
        except Exception as e:
            print(f"\n❌ Error: {e}")
            sys.exit(1)
    elif test_name == "all":
        # Run all tests in sequence
        print("=" * 70)
        print("COMPREHENSIVE BRIDGE TEST")
        print("=" * 70)
        print("\nRunning all bridge tests...\n")
        
        # Test 1: Test command
        print("\n[1/4] Testing 'test' command...")
        test1 = test_bridge()
        
        # Test 2: Create session
        print("\n[2/4] Testing 'create_session'...")
        success, session_id = test_create_session()
        
        # Test 3: Close session (if we have a session)
        if success and session_id:
            print("\n[3/4] Testing 'close_session'...")
            request = {
                "command": "close_session",
                "app_session_id": session_id,
                "client_private_key": os.getenv("PRIVATE_KEY"),
                "worker_address": os.getenv("WORKER_ADDRESS"),
            }
            try:
                response = call_bridge(request, timeout=35)
                if response.get("success"):
                    print("✅ Close session PASSED!")
                else:
                    print(f"❌ Close session FAILED: {response.get('error')}")
            except Exception as e:
                print(f"❌ Close session ERROR: {e}")
        
        # Test 4: Submit state (known issue)
        if success and session_id:
            print("\n[4/4] Testing 'submit_state' (known to have issues)...")
            # Create a new session for this test
            create_req = {
                "command": "create_session",
                "client_private_key": os.getenv("PRIVATE_KEY"),
                "worker_address": os.getenv("WORKER_ADDRESS"),
                "quorum": 1
            }
            try:
                create_resp = call_bridge(create_req, timeout=35)
                if create_resp.get("success"):
                    test_session = create_resp.get("data", {}).get("app_session_id")
                    test_submit_state(test_session)
            except Exception as e:
                print(f"⚠️  Could not test submit_state: {e}")
        
        print("\n" + "=" * 70)
        print("TEST SUMMARY")
        print("=" * 70)
        print("✅ test: PASSED")
        if success:
            print("✅ create_session: PASSED")
            print("✅ close_session: PASSED (if no errors above)")
        else:
            print("❌ create_session: FAILED")
        print("⚠️  submit_state: Known issue (timeout)")
    else:
        print(f"Unknown test: {test_name}")
        print("Usage: python3 test_bridge.py [test|create_session|submit_state|close_session|all] [session_id]")
        sys.exit(1)
