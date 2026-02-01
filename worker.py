"""
listens for jobs and executes them.
"""

import time
from fastapi import FastAPI, Request, Response
from pydantic import BaseModel

app = FastAPI()

# MOCK DATABASE: In production, these are Circle/Arc wallet addresses
WORKER_WALLET = "0xWorkerENS_or_Address"
JOB_PRICE_USDC = 0.05 

class JobRequest(BaseModel):
    job_id: str
    requester: str
    task_type: str
    input_data: dict

def execute_logic(task_type, data):
    print(f"⚙️ Working on: {task_type}")
    time.sleep(2) # Simulate work
    return f"Processed {task_type} successfully."

@app.post("/submit-job")
async def submit_job(job: JobRequest, request: Request):
    # --- THE X402 GUARD ---
    payment_proof = request.headers.get("X-PAYMENT")
    
    if not payment_proof:
        # We reject the job and send back the payment requirements
        return Response(
            status_code=402,
            content=f"Payment Required. Send {JOB_PRICE_USDC} USDC to {WORKER_WALLET} on Arc."
        )

    # --- THE EXECUTION ---
    # If the code reaches here, payment was "verified"
    result = execute_logic(job.task_type, job.input_data)
    return {"status": "completed", "result": result, "worker": WORKER_WALLET}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)