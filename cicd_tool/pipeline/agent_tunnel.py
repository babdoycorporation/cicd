"""
pipeline/agent_tunnel.py  —  Real-Time Agent Tunnel Manager for CogFocus One™
Manages active persistent agent streaming connections and queues tasks for sub-second push execution.
"""

import json
import logging
import queue
import threading
import time

logger = logging.getLogger(__name__)

class AgentTunnelManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(AgentTunnelManager, cls).__new__(cls)
                cls._instance._channels = {}  # agent_id -> queue.Queue()
                cls._instance._results = {}   # task_id -> queue.Queue()
            return cls._instance

    def register_agent(self, agent_id):
        with self._lock:
            if agent_id not in self._channels:
                self._channels[agent_id] = queue.Queue()
            return self._channels[agent_id]

    def dispatch_task(self, agent_id, task_id, command, step_name, timeout=60):
        """Pushes task directly to agent stream and waits for result."""
        with self._lock:
            q = self._channels.get(agent_id)
            if q is None:
                q = queue.Queue()
                self._channels[agent_id] = q
            result_q = queue.Queue()
            self._results[task_id] = result_q

        task_payload = {
            'task_id': task_id,
            'command': command,
            'step_name': step_name
        }
        q.put(task_payload)
        logger.info(f"[TUNNEL] Dispatched task #{task_id} to agent #{agent_id} via real-time stream.")

        try:
            res = result_q.get(timeout=timeout)
            return res
        except queue.Empty:
            logger.warning(f"[TUNNEL] Task #{task_id} timed out after {timeout}s.")
            return {'returncode': 124, 'stdout': f"❌ [TIMEOUT ERROR] Agent #{agent_id} did not complete execution within {timeout} seconds.", 'stderr': ''}
        finally:
            with self._lock:
                self._results.pop(task_id, None)

    def submit_result(self, task_id, returncode, stdout, stderr):
        with self._lock:
            result_q = self._results.get(task_id)
        if result_q:
            result_q.put({
                'returncode': returncode,
                'stdout': stdout,
                'stderr': stderr
            })
            return True
        return False

tunnel_manager = AgentTunnelManager()
