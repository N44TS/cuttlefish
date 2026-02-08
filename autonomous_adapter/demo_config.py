"""
Build config for run_autonomous_agent so the demo works with the demo feed (or Moltbook).

Use with feed_client for get_recent_posts / post_reply / post_offer.
Worker: sees offers, replies with "I accept. My ENS: {my_ens}".
Client: sees accepts, looks up offer by thread_id, calls trigger_hire_from_accept.
"""

import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from . import feed_client
from .trigger_agentpay import trigger_hire_from_accept, trigger_hire_by_capability


def _ens_from_env_file() -> str:
    """Read AGENTPAY_ENS_NAME from .env so we avoid shell truncation (e.g. 13-char export limit)."""
    for path in (Path.cwd() / ".env", Path(__file__).resolve().parent.parent / ".env"):
        if not path.exists():
            continue
        try:
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if line.startswith("AGENTPAY_ENS_NAME="):
                    val = line.split("=", 1)[1].strip().strip("'\"")
                    val = val.replace("\r", "").replace("\n", "").strip().removesuffix(".eth")
                    if val:
                        return val
        except Exception:
            continue
    return ""


def format_offer_text(
    task_type: str,
    price: str = "0.05 AP",
    input_ref: Optional[str] = None,
    poster_ens: str = "",
) -> str:
    """Build [AGENTPAY_OFFER] convention text."""
    poster_ens = (poster_ens or "").strip()
    if poster_ens and not poster_ens.endswith(".eth"):
        poster_ens = poster_ens + ".eth"
    lines = [
        "[AGENTPAY_OFFER]",
        f"task: {task_type}",
        f"price: {price}",
        "payment: agentpay",
        f"ens: {poster_ens}" if poster_ens else "",
    ]
    if input_ref:
        lines.insert(3, f"input: {input_ref}")
    return "\n".join(l for l in lines if l)


def build_demo_config(
    role: str,
    my_ens: Optional[str] = None,
    offer_store: Optional[Dict[str, Dict[str, Any]]] = None,
    poll_interval_seconds: int = 30,
    initial_offer: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Build config for run_autonomous_agent using the demo feed client.

    role: "worker" | "client"
      - worker: on_offer posts "I accept. My ENS: {my_ens}.eth"
      - client: on_accept looks up offer by thread_id and calls trigger_hire_from_accept
    my_ens: ENS name for this agent (e.g. "worker" -> worker.eth). Required for role=worker.
    offer_store: Dict[post_id, { task_type, input_data }]. Required for role=client; used to
      look up task_type/input_data when an accept is seen (thread_id = offer post id).
    initial_offer: If role=client, optional dict { task_type, price?, input_data?, poster_ens? }.
      When provided, we post this offer once before the loop and store it so we can trigger hire later.
    """
    # Prefer .env file so ENS is not truncated by shell. We use the full value (no slicing).
    raw = (my_ens or _ens_from_env_file() or os.getenv("AGENTPAY_ENS_NAME") or "").strip().rstrip(".eth").replace("\r", "").replace("\n", "").strip()
    my_ens = raw
    if role == "worker" and not my_ens:
        my_ens = "worker"
    ens_suffix = f"{my_ens}.eth" if my_ens else "me.eth"  # Full name; nothing in this code truncates it.

    if offer_store is None and role == "client":
        offer_store = {}

    def feed_provider() -> List[Dict[str, Any]]:
        return feed_client.get_recent_posts()

    if role == "worker":
        replied_offer_ids: set = set()  # post accept only once per offer

        def on_offer(o: Dict[str, Any]) -> None:
            item = o.get("_item") or {}
            thread_id = item.get("thread_id") or item.get("id")
            if not thread_id:
                return
            tid = str(thread_id)
            if tid in replied_offer_ids:
                return
            replied_offer_ids.add(tid)
            text = f"[AGENTPAY_ACCEPT]\nens: {ens_suffix}"
            feed_client.post_reply(tid, text)

        def on_accept(_: Dict[str, Any]) -> None:
            pass

        config = {
            "feed_provider": feed_provider,
            "on_offer": on_offer,
            "on_accept": on_accept,
            "poll_interval_seconds": poll_interval_seconds,
        }
        return config

    # client — track whether hire completed and the job result (for autonomous_client exit + show outcome)
    hire_result: Dict[str, Any] = {"completed": False, "error": None, "result": None}

    def on_accept(a: Dict[str, Any]) -> None:
        item = a.get("_item") or {}
        thread_id = item.get("thread_id") or item.get("id")
        if not thread_id or not offer_store:
            return
        ctx = offer_store.get(str(thread_id))
        if not ctx:
            return
        task_type = ctx.get("task_type") or "analyze-data"
        input_data = ctx.get("input_data") or {"query": "Demo task"}
        try:
            # Optional: hire by capability (demo) — set AGENTPAY_HIRE_BY_CAPABILITY=1 and AGENTPAY_KNOWN_AGENTS=ens.eth
            known_agents_raw = (os.getenv("AGENTPAY_KNOWN_AGENTS") or "").strip()
            if os.getenv("AGENTPAY_HIRE_BY_CAPABILITY") and known_agents_raw:
                # Normalize ENS: avoid double .eth (e.g. democuttlefish.eth.eth -> democuttlefish.eth)
                known_agents = [(n.strip().removesuffix(".eth").strip() + ".eth") for n in known_agents_raw.split(",") if n.strip()]
                if known_agents:
                    # Discovery: use first word of task_type so "summarize article" matches ENS "summarize" or "summarize medical articles"
                    cap_for_discovery = (task_type.split() or ["analyze-data"])[0].lower()
                    print(f"[CLIENT] Hiring by capability '{cap_for_discovery}' (known_agents: {known_agents})")
                    result = trigger_hire_by_capability(cap_for_discovery, known_agents, task_type, input_data)
                else:
                    result = trigger_hire_from_accept(a, task_type=task_type, input_data=input_data)
            else:
                result = trigger_hire_from_accept(a, task_type=task_type, input_data=input_data)
            if result and getattr(result, "status", None) == "completed":
                hire_result["completed"] = True
                hire_result["error"] = None
                hire_result["result"] = getattr(result, "result", None)
                hire_result["payment_tx_hash"] = getattr(result, "payment_tx_hash", None)
            else:
                err = getattr(result, "error", None) or str(result)
                hire_result["completed"] = False
                hire_result["error"] = err
                hire_result["result"] = None
                print(f"[CLIENT] Hire failed: {err}")
                if "ENS lookup failed" in str(err) or "no agent info" in str(err).lower():
                    print("[CLIENT] Tip: Accept had wrong ENS (e.g. truncated). Worker must post correct ENS; check AGENTPAY_ENS_NAME in worker .env.")
        except Exception as e:
            hire_result["completed"] = False
            hire_result["error"] = str(e)
            hire_result["result"] = None
            print(f"[CLIENT] Hire error: {e}")

    def on_offer(_: Dict[str, Any]) -> None:
        pass

    config = {
        "feed_provider": feed_provider,
        "on_offer": on_offer,
        "on_accept": on_accept,
        "poll_interval_seconds": poll_interval_seconds,
        "_hire_result": hire_result,
    }

    if initial_offer and offer_store is not None:
        task_type = initial_offer.get("task_type") or "analyze-data"
        price = initial_offer.get("price") or "0.05 AP"
        input_data = initial_offer.get("input_data") or {"query": "Demo task"}
        poster_ens = initial_offer.get("poster_ens") or my_ens or "client"
        text = format_offer_text(task_type, price, initial_offer.get("input_ref"), poster_ens)
        full_text = input_data.get("query") or input_data.get("text") or ""
        created = feed_client.post_offer(text, full_text=full_text if full_text else None)
        if created and created.get("id"):
            offer_store[created["id"]] = {"task_type": task_type, "input_data": input_data}

    return config


def post_offer_and_store(
    task_type: str,
    input_data: Optional[Dict[str, Any]] = None,
    price: str = "0.05 AP",
    poster_ens: str = "",
    offer_store: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Optional[str]:
    """
    Post an offer to the demo feed and store context for trigger_hire_from_accept.
    Returns post id if successful. Call this (e.g. once at startup) so the client can later match accepts.
    """
    store = offer_store if offer_store is not None else {}
    poster_ens = (poster_ens or os.getenv("AGENTPAY_ENS_NAME") or "client").strip()
    if poster_ens and not poster_ens.endswith(".eth"):
        poster_ens = poster_ens + ".eth"
    text = format_offer_text(task_type, price, None, poster_ens)
    created = feed_client.post_offer(text)
    if not created or not created.get("id"):
        return None
    pid = created["id"]
    store[pid] = {"task_type": task_type, "input_data": input_data or {"query": "Demo task"}}
    return pid
