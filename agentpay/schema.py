"""
Job and payment schema for the 402 flow.

Contract: Requester sends Job → Worker returns 402 + Bill → Requester pays →
Worker verifies payment, does work, returns JobResult.
"""

from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class Job(BaseModel):
    """Task request from requester (agent) to worker (agent)."""

    job_id: str = Field(..., description="Unique job identifier")
    requester: str = Field(..., description="Requester identity: ENS name or 0x address")
    task_type: str = Field(..., description="Capability/category e.g. analyze-data, summarize")
    input_data: Dict[str, Any] = Field(default_factory=dict)
    price_usdc: Optional[float] = Field(None, description="Expected price; worker may override via Bill")

    def to_submit_payload(self) -> Dict[str, Any]:
        """Payload for POST to worker endpoint."""
        return {
            "job_id": self.job_id,
            "requester": self.requester,
            "task_type": self.task_type,
            "input_data": self.input_data,
        }


class Bill(BaseModel):
    """402 response: how much to pay and where."""

    amount: float = Field(..., description="Amount in USDC (or stablecoin units)")
    recipient: str = Field(..., description="Worker payment address (0x)")
    chain_id: Optional[int] = Field(None, description="Chain for on-chain payment")
    message: Optional[str] = Field(None, description="Human-readable bill description")
    payment_method: Optional[str] = Field(
        None, description="Payment method: 'onchain', 'yellow', or None (defaults to 'onchain')"
    )


class JobResult(BaseModel):
    """Worker response after payment verified and work done."""

    status: str = Field(..., description="e.g. completed, failed")
    result: Optional[Any] = None
    worker: Optional[str] = Field(None, description="Worker address or ENS")
    attestation_uid: Optional[str] = Field(None, description="EAS attestation UID for this job (receipt)")
    error: Optional[str] = None
    yellow_session_id: Optional[str] = Field(
        None, description="Yellow app session ID (set by client flow so caller can close session)"
    )
    payment_tx_hash: Optional[str] = Field(
        None, description="On-chain payment tx hash (e.g. Yellow channel close); for Etherscan lookup"
    )
