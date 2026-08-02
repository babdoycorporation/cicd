"""
test_server_to_agent.py — Server-to-Agent Direct Remote Execution Verification Tool
Run this on your server (uk-hyd-preprod) inside cicd_tool directory:

    python test_server_to_agent.py
"""

import os
import sys
import django

# Initialize Django environment
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cicd_tool.settings')
django.setup()

from pipeline.models import Agent, AgentTask
from pipeline.agent_tunnel import tunnel_manager

def run_verification():
    print("==================================================")
    print(" 🚀 CogFocus One™ Server-to-Agent Remote Dispatcher")
    print("==================================================")

    agent = Agent.objects.filter(hostname__icontains='LAPTOP').first() or Agent.objects.first()
    if not agent:
        print("❌ No active agent found in database!")
        return

    print(f"✓ Target Agent Hostname : {agent.hostname}")
    print(f"✓ Target Agent LAN IP   : {agent.ip_address}")
    print(f"✓ Target Agent Hash Key : {agent.hash_key}")

    test_cmd = (
        'python -c "import os; '
        'path = \'D:/deployed_apps/unlockian-app\'; '
        'os.makedirs(path, exist_ok=True); '
        'print(f\'DIRECT SERVER-TO-AGENT VERIFICATION SUCCESSFUL: Created {path}\')"'
    )

    task = AgentTask.objects.create(
        agent=agent,
        step_name="Server-to-Agent Remote Verification",
        command=test_cmd,
        status="running"
    )

    print(f"\n[DISPATCH] Sending remote command to {agent.hostname}...")
    print(f"[CMD] {test_cmd}\n")

    res = tunnel_manager.dispatch_task(agent.pk, task.pk, test_cmd, "Server-to-Agent Remote Verification", timeout=30)

    rc = res.get('returncode', 0)
    stdout = res.get('stdout', '')
    stderr = res.get('stderr', '')

    print("==================================================")
    print(f" 📥 AGENT EXECUTION RESULT (Exit Code: {rc})")
    print("==================================================")
    if stdout:
        print(f"STDOUT:\n{stdout}")
    if stderr:
        print(f"STDERR:\n{stderr}")

    if rc == 0:
        print("\n🎉 SUCCESSFUL: Server connected to agent and folder D:\\deployed_apps\\unlockian-app was created on Windows!")
    else:
        print(f"\n❌ FAILED: Agent execution returned exit code {rc}")

if __name__ == '__main__':
    run_verification()
