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
from git import Repo
import logging
from .models import Credential, Agent

logger = logging.getLogger(__name__)

def execute_step(step, run_id, credentials):
    logger.debug(f"Executing step: {step.name}, command: {step.command}")
    command = step.command.strip()
    run_dir = os.path.join('D:/cicd/runs/', str(run_id))
    os.makedirs(run_dir, exist_ok=True)
    os.chdir(run_dir)

    env = os.environ.copy()
    if credentials:
        env.update(credentials)

    if command.startswith('git clone'):
        repo_url = command.split()[-1]
        repo_name = repo_url.split('/')[-1].replace('.git', '')
        repo_dir = os.path.join(run_dir, repo_name)

        output = []
        if os.path.exists(repo_dir) and os.path.isdir(repo_dir):
            logger.info(f"Repository {repo_name} already exists. Pulling latest changes...")
            output.append(f"Repository {repo_name} already exists. Pulling latest changes...")
            repo = git.Repo(repo_dir)
            origin = repo.remotes.origin
            for info in origin.pull(progress=git.RemoteProgress()):
                logger.info(f"Updated {info.name} to {info.commit}")
                output.append(f"Updated {info.name} to {info.commit}")
        else:
            logger.info(f"Cloning repository {repo_name}...")
            output.append(f"Cloning repository {repo_name}...")
            git.Repo.clone_from(repo_url, repo_dir, progress=git.RemoteProgress())
            logger.info(f"Repository {repo_name} cloned successfully.")
            output.append(f"Repository {repo_name} cloned successfully.")
        
        return subprocess.CompletedProcess(args=command, returncode=0, stdout="\n".join(output))

    else:
        process = subprocess.Popen(
            command,
            shell=True,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            bufsize=1
        )

        output = []
        for line in process.stdout:
            logger.debug(f"Command output: {line.strip()}")
            output.append(line.strip())

        process.wait()
        logger.debug(f"Command completed with return code: {process.returncode}")
        return subprocess.CompletedProcess(
            args=command,
            returncode=process.returncode,
            stdout='\n'.join(output)
        )

def prepare_credentials(project):
    logger.debug(f"Preparing credentials for project: {project.name}")
    global_credentials = Credential.objects.filter(scope_level='global')
    local_credentials = Credential.objects.filter(scope_level='project', project=project)

    credentials = {}
    for cred in global_credentials:
        credentials[f"GLOBAL_{cred.service_name.upper()}_USERNAME"] = cred.username
        credentials[f"GLOBAL_{cred.service_name.upper()}_PASSWORD"] = cred.password
        credentials[f"GLOBAL_{cred.service_name.upper()}_TOKEN"] = cred.token

    for cred in local_credentials:
        credentials[f"LOCAL_{cred.service_name.upper()}_USERNAME"] = cred.username
        credentials[f"LOCAL_{cred.service_name.upper()}_PASSWORD"] = cred.password
        credentials[f"LOCAL_{cred.service_name.upper()}_TOKEN"] = cred.token

    logger.debug(f"Prepared {len(credentials)} credential entries")
    return credentials


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

