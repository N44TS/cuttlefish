# test_delegate.py
import time
from queue import Queue
from job_schema import Job

# Shared queue
job_queue = Queue()

# Worker function
def execute_job(job: Job):
    print(f"Worker received job: {job.task_type}")
    time.sleep(1)
    print(f"Worker finished job: {job.task_type} for {job.requester}\n")

def worker_loop():
    while not job_queue.empty():
        job = job_queue.get()
        execute_job(job)
        job_queue.task_done()

# Client creates jobs
jobs = [
    Job(job_id="job_001", requester="agent_a", task_type="analyze-data", input_data={"dataset": "data1.csv"}),
    Job(job_id="job_002", requester="agent_a", task_type="summarize-report", input_data={"report": "report.docx"}),
]

for job in jobs:
    print(f"Client: Sending job {job.job_id} - {job.task_type}")
    job_queue.put(job)

print("\nClient: All jobs sent!\n")

# Start worker loop
worker_loop()
