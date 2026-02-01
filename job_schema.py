"""
Define the minimal job structure
"""

from typing import Dict, Any

class Job:
    def __init__(self, job_id: str, requester_ens: str, task_type: str, input_data: Dict[str, Any], price_usdc: float = 0.01):
        self.job_id = job_id
        self.requester_ens = requester_ens  # Use ENS instead of just a name
        self.task_type = task_type
        self.input_data = input_data
        self.price_usdc = price_usdc # The "Cost" of the job
        self.payment_signature = None # This will be filled by the Client after the 402 challenge

    def to_dict(self):
        return {
            "job_id": self.job_id,
            "requester": self.requester_ens,
            "task_type": self.task_type,
            "price": self.price_usdc,
            "payment_signature": self.payment_signature
        }