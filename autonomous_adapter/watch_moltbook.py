"""
Watch Moltbook (or any feed) for AgentPay offers and accepts.

To read from Moltbook inside a Codespace (or any env): pass a feed_provider
that returns feed items from your Moltbook client. AgentPay does not ship
a Moltbook client; you or Moltbot provide it.
"""

import time
from typing import Callable, List, Optional

from .parse_agentpay_intent import parse_offer, parse_accept


def watch_moltbook_feed(
    on_offer: Callable[[dict], None],
    on_accept: Callable[[dict], None],
    poll_interval_seconds: int = 60,
    feed_provider: Optional[Callable[[], List[dict]]] = None,
) -> None:
    """
    Run forever: poll feed, parse posts, call on_offer / on_accept.

    Args:
        on_offer: Called with parsed offer dict (task_type, poster_ens, price, input_ref).
        on_accept: Called with parsed accept dict (worker_ens).
        poll_interval_seconds: How often to poll.
        feed_provider: Optional. Callable that returns a list of feed items.
            Each item should have "text" or "body" (and optionally "id", "thread_id").
            If None, no items are fetched (stub mode for testing).
    """
    while True:
        items = (feed_provider() if feed_provider else []) or []
        for item in items:
            text = (item.get("text") or item.get("body") or "").strip()
            if not text:
                continue
            o = parse_offer(text)
            if o:
                on_offer({
                    "task_type": o.task_type,
                    "poster_ens": o.poster_ens,
                    "price": o.price,
                    "input_ref": o.input_ref,
                    "_item": item,
                })
            a = parse_accept(text)
            if a:
                on_accept({"worker_ens": a.worker_ens, "_item": item})
        time.sleep(poll_interval_seconds)
