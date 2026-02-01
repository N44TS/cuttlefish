"""
Creates a job and sends it to the worker.
"""

import requests
import json

WORKER_URL = "http://localhost:8000/submit-job"

def send_job_with_payment_logic(job_id, task, data):
    payload = {
        "job_id": job_id,
        "requester": "agent_a.molt.eth",
        "task_type": task,
        "input_data": data
    }

    print(f"🚀 Client: Sending job {job_id}...")
    
    # Attempt 1: Standard request (No payment header)
    response = requests.post(WORKER_URL, json=payload)

    if response.status_code == 402:
        print(f"⚠️ Worker demanded payment! Details: {response.text}")
        
        # INTERACTION: This is where your SDK "signs" the transaction
        print("💸 SDK: Signing 0.05 USDC payment for Arc Network...")
        mock_payment_proof = "signed_tx_hash_0x123abc" 
        
        # Attempt 2: Retrying with the X-PAYMENT header
        headers = {"X-PAYMENT": mock_payment_proof}
        print("🔄 Client: Retrying with payment proof...")
        response = requests.post(WORKER_URL, json=payload, headers=headers)

    if response.status_code == 200:
        print(f"✅ Job Complete! Result: {response.json()['result']}")
        
        # --- REPUTATION (TV) ---
        print(f"⭐ Client: Submitting EAS Attestation for {response.json()['worker']} (Rating: 5/5)")
    else:
        print(f"❌ Failed: {response.status_code}")

if __name__ == "__main__":
    send_job_with_payment_logic("job_001", "analyze-data", {"file": "test.csv"})
