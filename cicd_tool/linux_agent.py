# linux_agent.py
import os
import subprocess
import requests
import json
import hashlib
import time
import atexit
from http.server import BaseHTTPRequestHandler, HTTPServer
import ssl
from urllib.parse import urlparse

SERVER_URL = 'http://your-ci-cd-tool.com'
REGISTER_URL = f'{SERVER_URL}/register/'
COMMANDS_URL = f'{SERVER_URL}/commands/'
HEARTBEAT_URL = f'{SERVER_URL}/heartbeat/'
HASH_KEY = 'your_secret_hash_key'  # Secret key for hash generation
SSL_CERT = 'path_to_your_ssl_certificate.pem'  # Path to SSL certificate
SSL_KEY = 'path_to_your_ssl_private_key.pem'   # Path to SSL private key

class RequestHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        data = json.loads(post_data.decode('utf-8'))
        command = data.get('command')

        if command:
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
            result = subprocess.check_output(command, shell=True, text=True)
            return result
        except subprocess.CalledProcessError as e:
            return f'Error: {e.output}'
        except Exception as e:
            return f'Error: {e}'

def register_agent():
    try:
        hostname = os.uname().nodename
        ip_address = subprocess.check_output('hostname -I', shell=True, text=True).split()[0]

        # Generate hash key
        hash_value = hashlib.sha256(f'{hostname}-{ip_address}-{HASH_KEY}'.encode()).hexdigest()

        # Send registration request to server
        response = requests.post(REGISTER_URL, json={'hostname': hostname, 'ip_address': ip_address, 'hash_key': hash_value})
        if response.status_code == 200:
            print('Agent registered successfully.')
        else:
            print('Failed to register agent.')
    except Exception as e:
        print(f'Error during agent registration: {e}')

def send_heartbeat():
    try:
        # Send heartbeat signal to server
        requests.post(HEARTBEAT_URL)
    except Exception as e:
        print(f'Error sending heartbeat: {e}')

def main():
    register_agent()
    server_address = ('', 8080)

    parsed_url = urlparse(SERVER_URL)
    if parsed_url.scheme == 'https':
        # Enable HTTPS with SSL certificate
        httpd = HTTPServer(server_address, RequestHandler)
        httpd.socket = ssl.wrap_socket(httpd.socket, certfile=SSL_CERT, keyfile=SSL_KEY, server_side=True)
        print('Agent server running with HTTPS...')
    else:
        httpd = HTTPServer(server_address, RequestHandler)
        print('Agent server running with HTTP...')

    # Set up heartbeat signal
    while True:
        send_heartbeat()
        time.sleep(60)  # Send heartbeat every 60 seconds

    # Gracefully shutdown
    def shutdown():
        httpd.shutdown()
        print('Agent server stopped.')

    atexit.register(shutdown)
    httpd.serve_forever()

if __name__ == '__main__':
    main()
