"""
test_agent_connection.py — Standalone Diagnostic Tool for CogFocus One™ Agent Streaming
Run this on your Windows laptop to test direct real-time connectivity to the server.

Usage (PowerShell on Windows):
    python test_agent_connection.py --server http://103.67.239.62:8007 --hash-key f4c9b72ac868420b87e2f6beb9e8cf0a
"""

import argparse
import json
import os
import subprocess
import time
import requests

def test_connection(server_url, hash_key):
    print("==================================================")
    print(" 🔌 CogFocus One™ Real-Time Agent Stream Diagnostic")
    print(f" Server URL: {server_url}")
    print(f" Hash Key  : {hash_key[:12]}...")
    print("==================================================")

    # 1. Test registration endpoint
    reg_url = f"{server_url.rstrip('/')}/ci/agents/register/"
    try:
        r = requests.post(reg_url, json={
            'hostname': os.environ.get('COMPUTERNAME', 'TEST_AGENT'),
            'ip_address': '127.0.0.1',
            'hash_key': hash_key,
            'operating_system': 'Windows'
        }, timeout=10)
        print(f"✓ Agent Registration: HTTP {r.status_code}")
    except Exception as e:
        print(f"❌ Registration Failed: {e}")
        return

    # 2. Test Stream Connection
    stream_url = f"{server_url.rstrip('/')}/ci/agents/stream/"
    print(f"Connecting to Agent Stream Tunnel: {stream_url}...")
    try:
        with requests.post(stream_url, json={'hash_key': hash_key}, stream=True, timeout=35) as resp:
            print(f"✓ Stream Connection: HTTP {resp.status_code}")
            if resp.status_code == 200:
                print("\n⚡ REAL-TIME STREAM TUNNEL CONNECTED SUCCESSFULLY!")
                print("Listening for stream frames from server...")
                count = 0
                for line in resp.iter_lines():
                    if not line:
                        continue
                    msg = json.loads(line.decode('utf-8'))
                    print(f"  📥 [RECV FRAME]: {msg}")
                    count += 1
                    if count >= 4:
                        print("\n==================================================")
                        print("✅ VERIFICATION SUCCESSFUL: Your agent stream is 100% connected & responsive!")
                        print("==================================================")
                        break
            else:
                print(f"❌ Stream rejected with status {resp.status_code}: {resp.text}")
    except Exception as e:
        print(f"❌ Stream Error: {e}")

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--server', default='http://103.67.239.62:8007')
    parser.add_argument('--hash-key', required=True)
    args = parser.parse_args()
    test_connection(args.server, args.hash_key)
