import requests
import json
from datetime import datetime

# Define the URL of the receive_heartbeat endpoint
receive_heartbeat_url = "http://localhost:8000/pipeline/agents/receive-heartbeat/"

# Sample data (hash_key and timestamp)
data = {
    "hash_key": "8bf2940c0d0046ed92503516c8a70a26",
    "timestamp": str(datetime.now())  # Current timestamp
}

# Convert data to JSON format
json_data = json.dumps(data)

# Make a POST request to the receive_heartbeat endpoint
response = requests.post(receive_heartbeat_url, data=json_data)

# Check the response
if response.status_code == 200:
    print("Heartbeat received successfully.")
else:
    print("Failed to receive heartbeat. Status code:", response.status_code)
    print("Response content:", response.text)
