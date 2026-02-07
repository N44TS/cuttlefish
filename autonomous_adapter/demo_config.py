"""
Build config for run_autonomous_agent so the demo works with the demo feed (or Moltbook).

Use with feed_client for get_recent_posts / post_reply / post_offer.
Worker: sees offers, replies with "I accept. My ENS: {my_ens}".
Client: sees accepts, looks up offer by thread_id, calls trigger_hire_from_accept.
"""

import os
from typing import Any, Callable, Dict, List, Optional

from . import feed_client
from .trigger_agentpay import trigger_hire_from_accept


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
    my_ens = (my_ens or os.getenv("AGENTPAY_ENS_NAME") or "").strip().rstrip(".eth")
    if role == "worker" and not my_ens:
        my_ens = "worker"
    ens_suffix = f"{my_ens}.eth" if my_ens else "me.eth"

    if offer_store is None and role == "client":
        offer_store = {}

    def feed_provider() -> List[Dict[str, Any]]:
        return feed_client.get_recent_posts()

    if role == "worker":
        def on_offer(o: Dict[str, Any]) -> None:
            item = o.get("_item") or {}
            thread_id = item.get("thread_id") or item.get("id")
            if not thread_id:
                return
            text = f"[AGENTPAY_ACCEPT]\nens: {ens_suffix}"
            feed_client.post_reply(str(thread_id), text)

        def on_accept(_: Dict[str, Any]) -> None:
            pass

        config = {
            "feed_provider": feed_provider,
            "on_offer": on_offer,
            "on_accept": on_accept,
            "poll_interval_seconds": poll_interval_seconds,
        }
        return config

    # client
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
            trigger_hire_from_accept(a, task_type=task_type, input_data=input_data)
        except Exception:
            pass  # log in real use

    def on_offer(_: Dict[str, Any]) -> None:
        pass

    config = {
        "feed_provider": feed_provider,
        "on_offer": on_offer,
        "on_accept": on_accept,
        "poll_interval_seconds": poll_interval_seconds,
    }

    if initial_offer and offer_store is not None:
        task_type = initial_offer.get("task_type") or "analyze-data"
        price = initial_offer.get("price") or "0.05 AP"
        input_data = initial_offer.get("input_data") or {"query": "Demo task"}
        poster_ens = initial_offer.get("poster_ens") or my_ens or "client"
        text = format_offer_text(task_type, price, initial_offer.get("input_ref"), poster_ens)
        created = feed_client.post_offer(text)
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
