"""
Creates a job and sends it to the worker.
"""

import time
from queue import Queue
from job_schema import Job
from worker import job_queue  # Import the same queue for local testing

def main():
    print("Client: Creating and sending jobs...\n")

    # Example jobs
    jobs = [
        Job(job_id="job_001", requester="agent_a", task_type="analyze-data", input_data={"dataset": "data1.csv"}),
        Job(job_id="job_002", requester="agent_a", task_type="summarize-report", input_data={"report": "report.docx"}),
    ]

    for job in jobs:
        print(f"Client: Sending job {job.job_id} - {job.task_type}")
        job_queue.put(job)
        time.sleep(1)  # Slight delay between sending jobs

    print("\nClient: All jobs sent!")

if __name__ == "__main__":
    main()
