"""
linux_agent.py  —  RockerCI build agent for Linux
BUG FIX: heartbeat was running in an infinite while loop BEFORE httpd.serve_forever(),
         so the HTTP server never started. Heartbeat now runs in a daemon thread.

Usage:
    python3 linux_agent.py --hash-key <KEY> --server http://your-server:8000
"""

import argparse
import atexit
import json
import logging
import os
import platform
import socket
import ssl
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

import requests

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger('linux_agent')

# ── CLI args ──────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser(description='RockerCI Linux Agent')
parser.add_argument('--hash-key', required=True, help='Agent hash key from the CI server')
parser.add_argument('--server', default='http://localhost:8000', help='CI server base URL')
parser.add_argument('--port', type=int, default=9000, help='Port to listen on')
parser.add_argument('--ssl-cert', default='', help='Path to SSL certificate (optional)')
parser.add_argument('--ssl-key', default='', help='Path to SSL private key (optional)')
args = parser.parse_args()

SERVER_URL = args.server.rstrip('/')
HASH_KEY = args.hash_key
AGENT_PORT = args.port
REGISTER_URL = f'{SERVER_URL}/ci/agents/register/'
HEARTBEAT_URL = f'{SERVER_URL}/ci/agents/receive-heartbeat/'
COMMAND_URL = f'{SERVER_URL}/ci/agents/receive-command/'

_shutdown_event = threading.Event()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_ip():
    try:
        result = subprocess.check_output('hostname -I', shell=False, text=True)
        return result.split()[0]
    except Exception:
        return socket.gethostbyname(socket.gethostname())


def register_agent():
    hostname = platform.node()
    ip_address = _get_ip()
    payload = {
        'hostname': hostname,
        'ip_address': ip_address,
        'hash_key': HASH_KEY,
        'operating_system': f"Linux {platform.release()}",
    }
    try:
        r = requests.post(REGISTER_URL, json=payload, timeout=10)
        if r.status_code == 200:
            logger.info(f"Agent registered: {hostname} ({ip_address})")
        else:
            logger.warning(f"Registration returned {r.status_code}: {r.text}")
    except Exception as e:
        logger.error(f"Registration failed: {e}")


def heartbeat_loop():
    """Runs in a daemon thread — sends heartbeats every 60 s."""
    while not _shutdown_event.is_set():
        try:
            requests.post(HEARTBEAT_URL, json={'hash_key': HASH_KEY}, timeout=5)
        except Exception as e:
            logger.debug(f"Heartbeat error: {e}")
        _shutdown_event.wait(60)


# ── HTTP request handler ──────────────────────────────────────────────────────

class CommandHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *a):
        logger.debug(fmt % a)

    def do_POST(self):
        try:
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length)
            data = json.loads(body.decode('utf-8'))
            command = data.get('command', '').strip()

            if command == 'exit':
                logger.info("Shutdown command received.")
                self._respond(200, {'status': 'shutting down'})
                _shutdown_event.set()
                return

            if not command:
                self._respond(400, {'error': 'No command'})
                return

            logger.info(f"Executing: {command}")
            try:
                # Use list form to avoid shell=True injection risk where possible
                result = subprocess.run(
                    command, shell=True, capture_output=True, text=True, timeout=300
                )
                self._respond(200, {
                    'stdout': result.stdout,
                    'stderr': result.stderr,
                    'returncode': result.returncode,
                })
            except subprocess.TimeoutExpired:
                self._respond(200, {'error': 'Command timed out', 'returncode': -1})

        except Exception as e:
            self._respond(500, {'error': str(e)})

    def _respond(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    register_agent()

    # Start heartbeat in background thread  ← BUG FIX (was blocking main thread)
    hb_thread = threading.Thread(target=heartbeat_loop, daemon=True, name='heartbeat')
    hb_thread.start()

    httpd = HTTPServer(('', AGENT_PORT), CommandHandler)

    parsed = urlparse(SERVER_URL)
    if parsed.scheme == 'https' and args.ssl_cert and args.ssl_key:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(args.ssl_cert, args.ssl_key)
        httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
        logger.info(f"Agent listening on HTTPS port {AGENT_PORT}")
    else:
        logger.info(f"Agent listening on HTTP port {AGENT_PORT}")

    def _on_exit():
        logger.info("Shutting down agent HTTP server.")
        httpd.shutdown()

    atexit.register(_on_exit)

    try:
        httpd.serve_forever()   # ← Now actually reached (heartbeat is in a thread)
    except KeyboardInterrupt:
        logger.info("Agent stopped by keyboard interrupt.")


if __name__ == '__main__':
    main()
