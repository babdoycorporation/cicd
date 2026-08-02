"""
windows_agent.py — CogFocus One™ build agent for Windows.

Registers itself with the CogFocus One™ server, then keeps itself alive with
heartbeats so the pipeline worker can dispatch runs to it.

Usage (PowerShell):
    python windows_agent.py --hash-key "my-secret-key"
    python windows_agent.py --server http://127.0.0.1:8001 --hash-key "my-secret-key"
"""

import argparse
import atexit
import json
import logging
import os
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s [agent] %(levelname)s %(message)s')

DEFAULT_SERVER = 'http://127.0.0.1:8001'
AGENT_COMMAND_PORT = 9000
HEARTBEAT_INTERVAL = 30  # seconds

SERVER_URL = DEFAULT_SERVER  # set in main()


class RequestHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # quieter default logging
        logging.debug(fmt % args)

    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)
        try:
            data = json.loads(post_data.decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            self._reply(400, {'error': 'Invalid JSON'})
            return

        command = data.get('command')
        if not command:
            self._reply(400, {'error': 'No command provided.'})
            return

        if command == 'exit':
            self._reply(200, {'result': 'Agent exiting...'})
            os._exit(0)

        result = self.execute_command(command)
        self._reply(200, {'result': result})

    def _reply(self, status, payload):
        self.send_response(status)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode('utf-8'))

    def execute_command(self, command):
        try:
            env = os.environ.copy()
            env['PIP_NO_INPUT'] = '1'
            env['PYTHONUNBUFFERED'] = '1'
            env['CI'] = 'true'
            process = subprocess.run(
                command, shell=True, env=env, capture_output=True, timeout=300)
            return {
                'stdout': process.stdout.decode('utf-8', errors='replace'),
                'stderr': process.stderr.decode('utf-8', errors='replace'),
                'returncode': process.returncode,
            }
        except subprocess.TimeoutExpired:
            return {'stdout': '', 'stderr': 'Command timed out (300s)', 'returncode': 1}
        except Exception as e:
            return {'stdout': '', 'stderr': f'Error executing command: {e}', 'returncode': 1}


def get_ip_address():
    """Best-effort LAN IP; falls back to loopback."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return '127.0.0.1'


def register_agent(hash_key):
    hostname = os.environ.get('COMPUTERNAME') or socket.gethostname()
    payload = {
        'hostname': hostname,
        'ip_address': get_ip_address(),
        'hash_key': hash_key,
        'operating_system': 'Windows',
    }
    try:
        r = requests.post(f'{SERVER_URL}/ci/agents/register/', json=payload, timeout=10)
        if r.status_code == 200:
            logging.info('Registered with server: %s', r.json().get('status'))
        else:
            logging.error('Registration failed (%s): %s', r.status_code, r.text[:200])
    except requests.RequestException as e:
        logging.error('Cannot reach server %s — %s', SERVER_URL, e)


def send_heartbeat(hash_key):
    while True:
        try:
            r = requests.post(f'{SERVER_URL}/ci/agents/receive-heartbeat/',
                              json={'hash_key': hash_key}, timeout=10)
            if r.status_code == 200:
                logging.info('Heartbeat OK')
            else:
                logging.warning('Heartbeat rejected (%s): %s', r.status_code, r.text[:200])
        except requests.RequestException as e:
            logging.warning('Heartbeat failed: %s', e)
        time.sleep(HEARTBEAT_INTERVAL)


def poll_agent_tasks(hash_key):
    handler = RequestHandler
    while True:
        try:
            r = requests.post(f'{SERVER_URL}/ci/agents/poll/', json={'hash_key': hash_key}, timeout=10)
            if r.status_code == 200:
                data = r.json()
                task_id = data.get('task_id')
                command = data.get('command')
                if task_id and command:
                    step_name = data.get('step_name', 'Step Execution')
                    logging.info("Received task #%s ('%s'): %s", task_id, step_name, command[:60])
                    env = os.environ.copy()
                    env['PIP_NO_INPUT'] = '1'
                    env['PYTHONUNBUFFERED'] = '1'
                    env['CI'] = 'true'
                    process = subprocess.run(command, shell=True, env=env, capture_output=True, timeout=600)
                    stdout = process.stdout.decode('utf-8', errors='replace')
                    stderr = process.stderr.decode('utf-8', errors='replace')
                    rc = process.returncode
                    report_payload = {
                        'hash_key': hash_key,
                        'task_id': task_id,
                        'returncode': rc,
                        'stdout': stdout,
                        'stderr': stderr
                    }
                    requests.post(f'{SERVER_URL}/ci/agents/report-task/', json=report_payload, timeout=15)
                    logging.info("Completed task #%s (exit code %s)", task_id, rc)
        except Exception as e:
            logging.debug('Task polling error: %s', e)
        time.sleep(2)


def main(server, hash_key, port):
    global SERVER_URL, AGENT_COMMAND_PORT
    SERVER_URL = server.rstrip('/')
    AGENT_COMMAND_PORT = port

    register_agent(hash_key)

    heartbeat_thread = threading.Thread(target=send_heartbeat, args=(hash_key,), daemon=True)
    heartbeat_thread.start()

    task_thread = threading.Thread(target=poll_agent_tasks, args=(hash_key,), daemon=True)
    task_thread.start()

    logging.info('Agent listening on server %s for outbound tasks...', SERVER_URL)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logging.info('Agent stopped.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='ReleaseRocket Windows build agent')
    parser.add_argument('--server', default=DEFAULT_SERVER,
                        help=f'ReleaseRocket server URL (default: {DEFAULT_SERVER})')
    parser.add_argument('--hash-key', required=True, help='Shared key identifying this agent')
    parser.add_argument('--port', type=int, default=AGENT_COMMAND_PORT,
                        help=f'Local command port (default: {AGENT_COMMAND_PORT})')
    args = parser.parse_args()
    main(args.server, args.hash_key, args.port)
