"""
Define the minimal job structure
"""

from typing import Dict, Any

class Job:
    def __init__(self, job_id: str, requester: str, task_type: str, input_data: Dict[str, Any]):
        self.job_id = job_id
        self.requester = requester
        self.task_type = task_type
        self.input_data = input_data

    def to_dict(self):
        return {
            "job_id": self.job_id,
            "requester": self.requester,
            "task_type": self.task_type,
            "input_data": self.input_data,
        }
