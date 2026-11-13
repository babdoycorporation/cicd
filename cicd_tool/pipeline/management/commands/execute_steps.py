# execute_steps.py
import os
import subprocess
import git
import requests
from django.core.management.base import BaseCommand

BASE_REPO_DIR = 'D:/cicd/'  # Set this to a suitable directory
SERVER_URL = 'http://localhost:8000/pipeline'  # Update with your server URL
COMMANDS_URL = f'{SERVER_URL}/agents/receive-command/'

class Command(BaseCommand):
    help = 'Execute pipeline steps'

    def add_arguments(self, parser):
        parser.add_argument('name', type=str, help='Step name')
        parser.add_argument('command', type=str, help='Command to execute')

    def handle(self, *args, **options):
        name = options['name']
        command = options['command']
        repo_dir = os.path.join(BASE_REPO_DIR, name)

        self.stdout.write(f"Executing step '{name}': {command}")

        output = ""

        try:
            if command.startswith('git clone'):
                repo_url = command.split()[-1]
                repo_name = repo_url.split('/')[-1].replace('.git', '')
                repo_dir = os.path.join(BASE_REPO_DIR, repo_name)

                if os.path.exists(repo_dir) and os.path.isdir(repo_dir):
                    # Repository already exists, pull the latest changes
                    self.stdout.write(f"Fetching latest changes for repository {repo_url}")
                    repo = git.Repo(repo_dir)
                    origin = repo.remotes.origin
                    origin.pull()
                    output = 'Repository updated with latest changes.\n'
                else:
                    # Clone the repository
                    self.stdout.write(f"Cloning repository {repo_url} into {repo_dir}")
                    result = subprocess.run(command, shell=True, capture_output=True, text=True)
                    output = result.stdout + result.stderr

                self.stdout.write(output)
            else:
                # Execute other commands
                result = subprocess.run(command, shell=True, capture_output=True, text=True)
                output = result.stdout + result.stderr
                self.stdout.write(output)

                if result.returncode != 0:
                    raise subprocess.CalledProcessError(result.returncode, command, output=output)

            self.stdout.write(f"Step '{name}' executed successfully.")

        except git.exc.GitError as git_error:
            error_message = f"Git error: {git_error}\n"
            self.stderr.write(error_message)
            output += error_message
        except subprocess.CalledProcessError as e:
            error_message = f"Error executing step '{name}': {e.output}\n"
            self.stderr.write(error_message)
            output += error_message
        except Exception as e:
            error_message = f"An unexpected error occurred: {e}\n"
            self.stderr.write(error_message)
            output += error_message

        return output

    # Override the execute method to receive instructions from the server
    def execute(self, *args, **options):
        try:
            # Make an HTTP GET request to receive instructions from the server
            response = requests.get(COMMANDS_URL)
            response.raise_for_status()  # Raise an exception for HTTP errors
            data = response.json()
            command = data.get('command')
            
            if command:
                # If a command is received, execute it
                self.handle(name="step", command=command)
        except requests.RequestException as e:
            self.stderr.write(f"Error communicating with the server: {e}")