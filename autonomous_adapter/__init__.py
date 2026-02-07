"""
AgentPay autonomous adapter: turn Moltbook (or feed) posts into AgentPay actions.

- parse_agentpay_intent: parse offer/accept format (see agentpay/docs/MOLTBOOK_CONVENTION.md).
- watch_moltbook: stub; implement with your Moltbook/feed source.
- trigger_agentpay: call pay_agent() when poster sees an accept.

Not a platform — each agent runs its own. AgentPay stays rails only.
"""

from .parse_agentpay_intent import (
    AgentPayOffer,
    AgentPayAccept,
    parse_offer,
    parse_accept,
)
from .trigger_agentpay import trigger_hire, trigger_hire_from_accept
from .run_loop import run_autonomous_agent
from .feed_client import get_recent_posts, post_reply, post_offer
from .demo_config import build_demo_config, format_offer_text, post_offer_and_store

__all__ = [
    "AgentPayOffer",
    "AgentPayAccept",
    "parse_offer",
    "parse_accept",
    "trigger_hire",
    "trigger_hire_from_accept",
    "run_autonomous_agent",
    "get_recent_posts",
    "post_reply",
    "post_offer",
    "build_demo_config",
    "format_offer_text",
    "post_offer_and_store",
]
