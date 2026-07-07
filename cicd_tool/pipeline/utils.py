"""
pipeline/utils.py  —  Execution helpers for the CI pipeline runner
"""

import logging
import os
import shlex
import subprocess

import git
from git import Repo

from .models import Agent, Credential

logger = logging.getLogger(__name__)

BASE_RUNS_DIR = os.environ.get('CI_RUNS_DIR', 'D:/cicd/runs')


# ─────────────────────────────────────────────────────────────────────────────
#  Step execution
# ─────────────────────────────────────────────────────────────────────────────

def execute_step(step, run_id, credentials: dict, workdir=None):
    """
    Execute a single PipelineStep.

    For `git clone …` commands the repo is cloned/pulled into the run directory.
    All other commands are run via subprocess with the credentials injected as
    environment variables.

    `workdir` — optional working directory (e.g. the checked-out repository);
    defaults to the run directory.

    Returns a subprocess.CompletedProcess-like object with .returncode and .stdout.
    """
    command = step.command.strip()
    run_dir = workdir or os.path.join(BASE_RUNS_DIR, str(run_id))
    os.makedirs(run_dir, exist_ok=True)

    env = os.environ.copy()
    if credentials:
        env.update({str(k): str(v) for k, v in credentials.items()})

    # ── git clone shortcut ────────────────────────────────────────────────────
    if command.lower().startswith('git clone'):
        return _handle_git_clone(command, run_dir, env)

    # ── General command ───────────────────────────────────────────────────────
    logger.debug(f"Running: {command}")
    process = subprocess.Popen(
        command,
        shell=True,           # shell=True retained for pipeline flexibility
        env=env,
        cwd=run_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
        bufsize=1,
    )
    output_lines = []
    for line in process.stdout:
        stripped = line.rstrip()
        logger.debug(f"  {stripped}")
        output_lines.append(stripped)
    process.wait()
    return subprocess.CompletedProcess(
        args=command,
        returncode=process.returncode,
        stdout='\n'.join(output_lines),
    )


def _handle_git_clone(command, run_dir, env):
    """Clone or pull a git repository as part of a pipeline step."""
    parts = command.split()
    repo_url = parts[-1]
    repo_name = repo_url.rstrip('/').split('/')[-1].replace('.git', '')
    repo_dir = os.path.join(run_dir, repo_name)
    output = []

    try:
        if os.path.isdir(repo_dir):
            logger.info(f"Pulling existing repo: {repo_name}")
            output.append(f"Pulling {repo_name}…")
            repo = Repo(repo_dir)
            repo.remotes.origin.pull()
            output.append("Pull complete.")
        else:
            logger.info(f"Cloning {repo_url}")
            output.append(f"Cloning {repo_url}…")
            Repo.clone_from(repo_url, repo_dir)
            output.append(f"Cloned to {repo_dir}")
        return subprocess.CompletedProcess(args=command, returncode=0, stdout='\n'.join(output))
    except Exception as e:
        output.append(f"Git error: {e}")
        return subprocess.CompletedProcess(args=command, returncode=1, stdout='\n'.join(output))


# ─────────────────────────────────────────────────────────────────────────────
#  YAML → PipelineStep sync
# ─────────────────────────────────────────────────────────────────────────────

def sync_steps_from_yaml(pipeline, yaml_content):
    """
    Parse a rockerci.yaml document and rebuild the pipeline's PipelineStep
    records from it, so the worker executes exactly what the repo defines.

    Supported schema (rockerci native):
        stages:
          - name: <stage-name>
            steps:
              - name: <display name>
                command: <shell command>

    Also supports GitHub Actions style:
        jobs:
          <job-name>:
            steps:
              - name: <display name>
                run:  <shell command>

    Returns the number of steps created (0 if the YAML defines none).
    """
    import yaml as _yaml
    from .models import PipelineStep

    try:
        parsed = _yaml.safe_load(yaml_content) or {}
    except _yaml.YAMLError as e:
        logger.error(f"sync_steps_from_yaml: invalid YAML for {pipeline.name}: {e}")
        return 0

    steps = []

    # ── rockerci native format: stages → steps → command ─────────────────
    if 'stages' in parsed:
        for stage in (parsed.get('stages') or []):
            if not isinstance(stage, dict):
                continue
            stage_name = stage.get('name', 'unnamed')
            for s in (stage.get('steps') or []):
                if not isinstance(s, dict):
                    continue
                cmd = s.get('command') or s.get('run')
                if cmd:
                    name = s.get('name') or f"{stage_name}: {str(cmd)[:40]}"
                    steps.append((str(name)[:100], str(cmd)))

    # ── GitHub Actions format: jobs → steps → run ─────────────────────────
    elif 'jobs' in parsed:
        for job_name, job in (parsed.get('jobs') or {}).items():
            for s in ((job or {}).get('steps') or []):
                if not isinstance(s, dict):
                    continue
                cmd = s.get('run') or s.get('command')
                if cmd:
                    name = s.get('name') or str(cmd)[:60]
                    steps.append((str(name)[:100], str(cmd)))

    if not steps:
        logger.warning(f"sync_steps_from_yaml: no steps found in YAML for {pipeline.name}")
        return 0

    PipelineStep.objects.filter(pipeline=pipeline).delete()
    for name, cmd in steps:
        PipelineStep.objects.create(pipeline=pipeline, name=name, command=cmd)
    logger.info(f"Synced {len(steps)} steps from YAML for pipeline {pipeline.name}")
    return len(steps)



def checkout_repository(run, run_dir):
    """
    Clone the pipeline's linked repository (local bare repo) into the run
    directory at the monitored branch. Returns (workdir, log_lines).
    Falls back to the run dir when no repository is linked.
    """
    from django.conf import settings

    log = []
    app = run.pipeline.application
    repo = app.linked_repository if app else None
    if not repo:
        log.append("[INFO] No repository linked; steps run in an empty workspace.")
        return run_dir, log

    repo_base = getattr(settings, 'REPO_BASE_PATH', 'D:/repos')
    bare_path = os.path.join(repo_base, f"{repo.name}.git")
    workdir = os.path.join(run_dir, repo.name)
    branch = run.pipeline.monitored_branch or repo.default_branch or 'main'

    try:
        log.append(f"[CHECKOUT] {repo.name} @ {branch}")
        Repo.clone_from(bare_path, workdir, branch=branch)
        head = Repo(workdir).head.commit
        log.append(f"[CHECKOUT] HEAD {head.hexsha[:10]} — {head.summary}")
        return workdir, log
    except Exception as e:
        log.append(f"[CHECKOUT-ERROR] {e}")
        return run_dir, log


# ─────────────────────────────────────────────────────────────────────────────
#  Credential preparation
# ─────────────────────────────────────────────────────────────────────────────

def prepare_credentials(project) -> dict:
    """
    Build a flat dict of environment variables from global and project-scoped
    Credential records.  Keys follow the pattern:
        GLOBAL_<SERVICE>_USERNAME / _PASSWORD / _TOKEN
        LOCAL_<SERVICE>_USERNAME  / _PASSWORD / _TOKEN
    """
    credentials = {}
    if project is None:
        return credentials

    global_creds = Credential.objects.filter(scope_level='global')
    local_creds = Credential.objects.filter(scope_level='project', project=project)

    for cred in global_creds:
        prefix = f"GLOBAL_{cred.service_name.upper()}"
        credentials[f"{prefix}_USERNAME"] = cred.username
        credentials[f"{prefix}_PASSWORD"] = cred.password
        credentials[f"{prefix}_TOKEN"] = cred.token

    for cred in local_creds:
        prefix = f"LOCAL_{cred.service_name.upper()}"
        credentials[f"{prefix}_USERNAME"] = cred.username
        credentials[f"{prefix}_PASSWORD"] = cred.password
        credentials[f"{prefix}_TOKEN"] = cred.token

    # Also expose project env vars
    if project.environment_variables and isinstance(project.environment_variables, dict):
        credentials.update({str(k): str(v) for k, v in project.environment_variables.items()})

    logger.debug(f"Prepared {len(credentials)} credential/env entries for {project.name}")
    return credentials


# ─────────────────────────────────────────────────────────────────────────────
#  Agent selection
# ─────────────────────────────────────────────────────────────────────────────

def get_available_agent():
    """
    Return the live agent that has been idle longest (oldest heartbeat).
    Raises ValueError if no agents are available.
    """
    agent = Agent.objects.filter(live=True).order_by('last_heartbeat').first()
    if agent is None:
        raise ValueError("No live agents available. Register and start an agent first.")
    logger.info(f"Selected agent: {agent.hostname} ({agent.ip_address})")
    return agent


# ─────────────────────────────────────────────────────────────────────────────
#  Repository file listing (used by project workspace browser)
# ─────────────────────────────────────────────────────────────────────────────

def get_repository_files(project):
    base = os.environ.get('CI_RUNS_DIR', 'D:/cicd')
    repo_dir = os.path.join(base, project.name)
    if not os.path.exists(repo_dir):
        return []
    files = []
    for root, _, filenames in os.walk(repo_dir):
        for name in filenames:
            full = os.path.join(root, name)
            files.append(os.path.relpath(full, repo_dir))
    return files
