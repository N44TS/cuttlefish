"""
listens for jobs and executes them.
"""

import time
from queue import Queue
from job_schema import Job

# Simulate a message queue (in real life, could be HTTP, messaging service, etc.)
job_queue = Queue()

def execute_job(job: Job):
    print(f"Worker received job: {job.task_type}")
    # Simulate doing some work
    time.sleep(2)
    result = f"Completed {job.task_type} for {job.requester}"
    print(f"Worker finished job: {job.task_type}")
    print(f"Result: {result}\n")
    return result

def worker_loop():
    print("Worker is listening for jobs...\n")
    while True:
        job = job_queue.get()  # Blocks until a job is available
        execute_job(job)
        job_queue.task_done()

if __name__ == "__main__":
    # Start the worker loop
    worker_loop()
