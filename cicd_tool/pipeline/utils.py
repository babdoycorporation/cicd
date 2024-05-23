import os

# Define BASE_REPO_DIR here
BASE_REPO_DIR = 'D:/cicd/'  # Adjust this path as needed

def get_repository_files(project):
    repo_dir = os.path.join(BASE_REPO_DIR, project.name)
    if not os.path.exists(repo_dir):
        return []  # Return an empty list if the repository directory doesn't exist

    files = []
    for root, _, filenames in os.walk(repo_dir):
        for filename in filenames:
            files.append(os.path.relpath(os.path.join(root, filename), repo_dir))
    return files

import os
import subprocess
import git

import os
import uuid

def execute_step(step, run_id):
    command = step.command.strip()  # Remove leading/trailing whitespace

    try:
        run_dir = os.path.join('D:/cicd/runs/', str(run_id))  # Path for the pipeline run directory
        os.makedirs(run_dir, exist_ok=True)  # Create the directory if it doesn't exist

        os.chdir(run_dir)  # Change directory to the pipeline run directory

        if command.startswith('git clone'):
            repo_url = command.split()[-1]
            repo_name = repo_url.split('/')[-1].replace('.git', '')
            repo_dir = os.path.join(run_dir, repo_name)

            if os.path.exists(repo_dir) and os.path.isdir(repo_dir):
                # Repository already exists, pull the latest changes
                try:
                    repo = git.Repo(repo_dir)
                    origin = repo.remotes.origin
                    result = origin.pull()
                    return result
                except Exception as e:
                    raise subprocess.CalledProcessError(returncode=1, cmd=command, output=str(e))
            else:
                # Clone the repository
                result = subprocess.run(command, shell=True, capture_output=True, text=True)
                return result
        else:
            # Execute other commands
            result = subprocess.run(command, shell=True, capture_output=True, text=True)
            return result
    except Exception as e:
        raise subprocess.CalledProcessError(returncode=1, cmd=command, output=str(e))



from django.db.models import Min
from .models import Agent

def get_available_agent():
    try:
        agents = Agent.objects.filter(live=True).order_by('last_heartbeat')
        if not agents.exists():
            raise ValueError("No available agents")

        agent = agents.first()
        print(f"Selected Agent: {agent.hostname} with IPs {agent.ip_address}")
        return agent
    except Agent.DoesNotExist:
        raise ValueError("No available agents")
