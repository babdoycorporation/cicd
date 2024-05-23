import os
import sys
import subprocess
import requests
import json
import time
import atexit
import logging
from http.server import BaseHTTPRequestHandler, HTTPServer
import ssl
from urllib.parse import urlparse
import argparse
import threading

SERVER_URL = 'http://localhost:8000/pipeline'  # Update this to your server URL
AGENT_COMMAND_PORT = 9000
HEARTBEAT_INTERVAL = 60  # Heartbeat interval in seconds

class RequestHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        data = json.loads(post_data.decode('utf-8'))
        command = data.get('command')

        if command:
            if command == 'exit':
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'result': 'Agent exiting...'}).encode('utf-8'))
                os._exit(0)
            else:
                result = self.execute_command(command)
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'result': result}).encode('utf-8'))
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(json.dumps({'error': 'No command provided.'}).encode('utf-8'))

    def execute_command(self, command):
        try:
            process = subprocess.Popen(command.split(), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            stdout, stderr = process.communicate()
            return {
                'stdout': stdout.decode('utf-8'),
                'stderr': stderr.decode('utf-8')
            }
        except Exception as e:
            return f'Error executing command: {e}'

def register_agent(hash_key):
    try:
        hostname = os.environ['COMPUTERNAME']
        ip_address = get_ip_address()

        response = requests.post(f'{SERVER_URL}/agents/register/', json={
            'hostname': hostname,
            'ip_address': ip_address,
            'hash_key': hash_key,
            'operating_system': 'Windows'
        })
        if response.status_code == 200:
            logging.info('Agent registered successfully.')
        else:
            logging.error('Failed to register agent: %s', response.content.decode('utf-8'))
    except Exception as e:
        logging.error('Error during agent registration: %s', e)

def get_ip_address():
    # Logic to get the IP address of the agent machine goes here
    return '127.0.0.1'

def send_heartbeat(hash_key):
    while True:
        try:
            response = requests.post(f'{SERVER_URL}/agents/receive-heartbeat/', json={'hash_key': hash_key})
            if response.status_code == 200:
                logging.info('Heartbeat sent successfully.')
            else:
                logging.error('Failed to send heartbeat: %s', response.content.decode('utf-8'))
        except Exception as e:
            logging.error('Error sending heartbeat: %s', e)
        time.sleep(HEARTBEAT_INTERVAL)

def main(hash_key):
    register_agent(hash_key)
    server_address = ('', AGENT_COMMAND_PORT)

    httpd = HTTPServer(server_address, RequestHandler)
    logging.info('Agent server running with HTTP...')

    def shutdown():
        httpd.shutdown()
        logging.info('Agent server stopped.')

    atexit.register(shutdown)

    # Start the heartbeat thread
    heartbeat_thread = threading.Thread(target=send_heartbeat, args=(hash_key,), daemon=True)
    heartbeat_thread.start()

    # Start the HTTP server
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        shutdown()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Windows Agent for CI/CD Tool')
    parser.add_argument('--hash-key', required=True, help='Hash key for agent registration')
    args = parser.parse_args()
    main(args.hash_key)
