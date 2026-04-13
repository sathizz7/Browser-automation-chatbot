import requests
import time
import subprocess
import atexit

print("Starting uvicorn server in background...")
proc = subprocess.Popen(["uv", "run", "uvicorn", "main:app", "--port", "8000"])
atexit.register(proc.kill)

# Wait for server to start
time.sleep(3)

print("\n--- 1. Testing /health ---")
try:
    resp = requests.get("http://localhost:8000/health")
    print(resp.json())
except Exception as e:
    print(f"Error: {e}")

print("\n--- 2. Testing /profile ---")
try:
    resp = requests.get("http://localhost:8000/profile")
    print(resp.json())
except Exception as e:
    print(f"Error: {e}")

print("\n--- 3. Testing /chat ---")
try:
    payload = {
        "message": "What is 2+2?",
        "session_id": "test1",
        "page_url": "https://example.com"
    }
    resp = requests.post("http://localhost:8000/chat", json=payload)
    print(resp.json())
except Exception as e:
    print(f"Error: {e}")

print("\n--- 4. Testing /automate (with fail URL) ---")
try:
    payload = {
        "task_type": "fill_form",
        "target_url": "https://paypal.com/checkout",
        "user_message": "Fill the form"
    }
    resp = requests.post("http://localhost:8000/automate", json=payload)
    print(resp.json())
except Exception as e:
    print(f"Error: {e}")

print("\nAll tests complete. Server is running on port 8000.")
