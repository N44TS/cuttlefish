"""
Payment backends: on-chain (default, no API key), Circle/Arc (optional), Yellow (optional).
"""

from agentpay.payments.onchain import pay_onchain
from agentpay.payments.circle_arc import is_circle_configured, pay_circle_arc
from agentpay.payments.yellow import pay_yellow, pay_yellow_channel, pay_yellow_full, close_yellow_session, steps_1_to_3, create_channel, channel_transfer, close_channel


def get_pay_fn(payment_method: str = "yellow_channel"):
    """Yellow only. Default: yellow_channel. yellow_full = session + channel (prize demo)."""
    if payment_method == "yellow_channel":
        return pay_yellow_channel
    if payment_method == "yellow_full":
        return pay_yellow_full
    if payment_method == "yellow":
        return pay_yellow
    if payment_method == "circle_arc" and is_circle_configured():
        return pay_circle_arc
    if payment_method == "onchain":
        return pay_onchain
    return pay_yellow_channel


__all__ = [
    "pay_onchain",
    "pay_yellow",
    "pay_yellow_channel",
    "pay_yellow_full",
    "close_yellow_session",
    "steps_1_to_3",
    "create_channel",
    "channel_transfer",
    "close_channel",
    "pay_circle_arc",
    "is_circle_configured",
    "get_pay_fn",
]
