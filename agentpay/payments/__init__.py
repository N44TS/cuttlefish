"""
Payment backends: on-chain (default, no API key), Circle/Arc (optional), Yellow (optional).
"""

from agentpay.payments.onchain import pay_onchain
from agentpay.payments.circle_arc import is_circle_configured, pay_circle_arc
from agentpay.payments.yellow import pay_yellow, close_yellow_session


def get_pay_fn(payment_method: str = "onchain"):
    """
    Single entry point: returns payment function based on method.
    
    Args:
        payment_method: "onchain", "yellow", or "circle_arc"
    
    Returns:
        Payment function (pay_onchain, pay_yellow, or pay_circle_arc)
    """
    if payment_method == "yellow":
        return pay_yellow
    if payment_method == "circle_arc" and is_circle_configured():
        return pay_circle_arc
    return pay_onchain


__all__ = [
    "pay_onchain",
    "pay_yellow",
    "close_yellow_session",
    "pay_circle_arc",
    "is_circle_configured",
    "get_pay_fn",
]
