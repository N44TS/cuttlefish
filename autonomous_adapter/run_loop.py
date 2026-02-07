"""
Daemon entrypoint: run the autonomous AgentPay loop (watch feed → parse → callbacks).

Use this so the agent can read from (and react to) Moltbook from inside a Codespace.
You supply feed_provider (e.g. your Moltbook client); AgentPay does not ship one.
"""

from typing import Any, Callable, Dict, List, Optional

from .watch_moltbook import watch_moltbook_feed


def run_autonomous_agent(config: Dict[str, Any]) -> None:
    """
    Run forever: poll feed, parse AgentPay intents, call your callbacks.

    This is the daemon entrypoint. No scripts, no manual steps after setup.
    Moltbot (or your integration) calls this at startup.

    Config:
        feed_provider: Callable[[], List[dict]]. Returns feed items; each item
            should have "text" or "body" (optional "id", "thread_id"). Use your
            Moltbook client here so the agent reads from Moltbook inside the Codespace.
        on_offer: Callable[[dict], None]. Called when an AgentPay offer is parsed.
            Your code can post "I accept. My ENS: your.eth" via your Moltbook client.
        on_accept: Callable[[dict], None]. Called when an AgentPay accept is parsed.
            Your code can call trigger_hire_from_accept(accept, task_type, input_data).
        poll_interval_seconds: Optional. Default 60.

    Example (pseudo):
        config = {
            "feed_provider": my_moltbook_client.get_recent_posts,
            "on_offer": lambda o: my_moltbook_client.post_reply(o["_item"]["id"], "I accept. My ENS: worker.eth"),
            "on_accept": lambda a: trigger_hire_from_accept(a, task_type="...", input_data={}),
        }
        run_autonomous_agent(config)
    """
    feed_provider = config.get("feed_provider")
    on_offer = config.get("on_offer")
    on_accept = config.get("on_accept")
    poll_interval_seconds = config.get("poll_interval_seconds", 60)

    if not callable(on_offer):
        on_offer = _noop
    if not callable(on_accept):
        on_accept = _noop

    watch_moltbook_feed(
        on_offer=on_offer,
        on_accept=on_accept,
        poll_interval_seconds=poll_interval_seconds,
        feed_provider=feed_provider,
    )


def _noop(_: dict) -> None:
    pass
