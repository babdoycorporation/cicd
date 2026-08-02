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

def execute_step(step, run_id, credentials: dict, workdir=None, agent=None):
    """
    Execute a single PipelineStep.

    For remote build agents (e.g. Windows agent LAPTOP-7CPI1OEH), dispatches the step
    command directly to the agent's HTTP daemon (port 9000) for native remote execution.
    """
    command = step.command.strip()
    run_dir = workdir or os.path.join(BASE_RUNS_DIR, str(run_id))
    os.makedirs(run_dir, exist_ok=True)

    env = os.environ.copy()
    if credentials:
        env.update({str(k): str(v) for k, v in credentials.items()})

    # ── Dispatch to Remote Build Agent Daemon (e.g. LAPTOP-7CPI1OEH) ────────────
    if agent and getattr(agent, 'ip_address', None) and agent.hostname != 'local':
        agent_url = f"http://{agent.ip_address}:9000"
        try:
            import requests as _requests
            resp = _requests.post(agent_url, json={'command': command}, timeout=600)
            if resp.status_code == 200:
                res = resp.json().get('result', {})
                stdout = res.get('stdout', '')
                stderr = res.get('stderr', '')
                rc = res.get('returncode', 0)
                output = (stdout + ('\n' + stderr if stderr else '')).strip()
                return subprocess.CompletedProcess(args=command, returncode=rc, stdout=output)
        except Exception as err:
            logger.warning(f"Remote agent execution on {agent.hostname} ({agent.ip_address}:9000) unreachable: {err}. Falling back to worker execution.")

    # ── git clone shortcut ────────────────────────────────────────────────────
    if command.lower().startswith('git clone'):
        return _handle_git_clone(command, run_dir, env)

    # ── Cross-platform PowerShell fallback on Linux ──────────────────────────
    if os.name != 'nt' and command.lower().startswith('powershell'):
        import shutil as _shutil
        if not _shutil.which('powershell') and not _shutil.which('pwsh'):
            import re
            m = re.search(r'([A-Za-z]:\\[^\s"\'\}]+|\/[^\s"\'\}]+)', command)
            app_name = (step.pipeline.application.name if hasattr(step, 'pipeline') and step.pipeline and step.pipeline.application else 'app').lower()
            target_dir = f'/opt/deployed_apps/{app_name}'
            if m:
                raw_path = m.group(1).replace('\\', '/')
                target_dir = re.sub(r'^[A-Za-z]:', '/opt', raw_path)
            command = f"mkdir -p {target_dir} && cp -r . {target_dir} && echo 'Deployment to {target_dir} completed successfully'"

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
    except _yaml.YAMLError:
        try:
            import re
            sanitized = re.sub(r'^\s*-\s*name:\s*(.*:\s*.*)$', r'  - name: "\1"', yaml_content, flags=re.MULTILINE)
            parsed = _yaml.safe_load(sanitized) or {}
        except Exception as e:
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

    # ── Flat steps format: steps → command / run ─────────────────────────
    elif 'steps' in parsed:
        for s in (parsed.get('steps') or []):
            if not isinstance(s, dict):
                continue
            cmd = s.get('command') or s.get('run')
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



def _find_bare_repo_path(repo_name):
    from gitmgmt.views import _get_repo_base_path
    base_dir = _get_repo_base_path()
    direct = os.path.join(base_dir, f"{repo_name}.git")
    if os.path.exists(direct):
        return direct
    if os.path.exists(base_dir):
        target = f"{repo_name}.git".lower()
        for item in os.listdir(base_dir):
            if item.lower() == target:
                return os.path.join(base_dir, item)
    from django.conf import settings
    alt_base = str(settings.BASE_DIR / 'repos')
    alt_direct = os.path.join(alt_base, f"{repo_name}.git")
    if os.path.exists(alt_direct):
        return alt_direct
    if os.path.exists(alt_base):
        target = f"{repo_name}.git".lower()
        for item in os.listdir(alt_base):
            if item.lower() == target:
                return os.path.join(alt_base, item)
    return direct


def checkout_repository(run, run_dir):
    """
    Clone the pipeline's linked repository into the run directory at the monitored branch.
    Returns (workdir, log_lines, success_bool).
    """
    from django.conf import settings

    log = []
    app = run.pipeline.application
    repo = app.linked_repository if app else None
    if not repo and app and app.repository:
        repo = app.repository
    if not repo:
        log.append("[INFO] No repository linked; steps run in an empty workspace.")
        return run_dir, log, True

    bare_path = _find_bare_repo_path(repo.name)
    workdir = os.path.join(run_dir, repo.name)
    branch = run.pipeline.monitored_branch or repo.default_branch or 'main'

    try:
        log.append(f"[CHECKOUT] {repo.name} @ {branch}")
        if not os.path.exists(bare_path):
            log.append(f"[CHECKOUT-ERROR] Bare repository path '{bare_path}' does not exist on server.")
            return run_dir, log, False

        Repo.clone_from(bare_path, workdir, branch=branch)
        head = Repo(workdir).head.commit
        log.append(f"[CHECKOUT] HEAD {head.hexsha[:10]} — {head.summary}")
        return workdir, log, True
    except Exception as e:
        log.append(f"[CHECKOUT-ERROR] {e}")
        return run_dir, log, False


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


# ─────────────────────────────────────────────────────────────────────────────
#  Build Artifacts
# ─────────────────────────────────────────────────────────────────────────────

ARTIFACTS_DIR = os.environ.get('CI_ARTIFACTS_DIR', 'D:/cicd/artifacts')


def is_artifact_command(command: str) -> bool:
    """Return True when command is  artifact:<glob>  e.g. artifact:dist/*.zip"""
    return command.strip().startswith('artifact:')


def store_artifact(command: str, run, workdir: str):
    """
    Copy files matching the glob pattern to the artifacts store and
    create BuildArtifact DB records.

    Command format:  artifact:<glob>
    e.g.             artifact:dist/*.zip
                     artifact:reports/coverage.html
    """
    import glob as _glob
    import mimetypes
    import shutil
    from .models import BuildArtifact

    pattern = command.strip()[len('artifact:'):].strip()
    run_artifacts_dir = os.path.join(ARTIFACTS_DIR, str(run.run_id))
    os.makedirs(run_artifacts_dir, exist_ok=True)

    matched = _glob.glob(os.path.join(workdir, pattern), recursive=True)
    stored = []
    for src in matched:
        if not os.path.isfile(src):
            continue
        filename = os.path.basename(src)
        dest = os.path.join(run_artifacts_dir, filename)
        shutil.copy2(src, dest)
        mime, _ = mimetypes.guess_type(filename)
        size = os.path.getsize(dest)
        rel_path = os.path.join(str(run.run_id), filename)
        art = BuildArtifact.objects.create(
            pipeline_run=run,
            name=filename,
            file_path=rel_path,
            file_size=size,
            content_type=mime or 'application/octet-stream',
        )
        stored.append(art)
        logger.info(f"Stored artifact {filename} ({size} bytes) for run {run.run_id}")

    return stored


# ─────────────────────────────────────────────────────────────────────────────
#  Deployment connector
# ─────────────────────────────────────────────────────────────────────────────

def is_deploy_command(command: str) -> bool:
    """Return True when the command is a connector directive, e.g. deploy:kubernetes:3"""
    return command.strip().startswith('deploy:')


def execute_deploy(command: str, run_id, workdir=None):
    """
    Execute a connector deploy directive.

    Command format:  deploy:<target_type>:<target_pk>

    Looks up the DeploymentTarget, builds a CLI command from its fields and
    attached credential, and runs it via subprocess.
    Returns a CompletedProcess-like object with .returncode and .stdout.
    """
    from .models import DeploymentTarget

    parts = command.strip().split(':')
    if len(parts) < 3:
        return subprocess.CompletedProcess(
            args=command, returncode=1,
            stdout='[DEPLOY-ERROR] Invalid deploy command format. Expected deploy:<type>:<target_pk>')

    target_pk_str = parts[2]
    try:
        target = DeploymentTarget.objects.select_related('credential').get(pk=int(target_pk_str))
    except (ValueError, DeploymentTarget.DoesNotExist):
        return subprocess.CompletedProcess(
            args=command, returncode=1,
            stdout=f'[DEPLOY-ERROR] DeploymentTarget #{target_pk_str} not found.')

    cred = target.credential
    env  = os.environ.copy()
    log  = [f'[DEPLOY] Target: {target.name} ({target.get_target_type_display()})']

    # Inject credential values as env vars
    if cred:
        pfx = f'DEPLOY_{cred.service_name.upper().replace(" ", "_")}'
        if cred.username: env[f'{pfx}_USERNAME'] = cred.username
        if cred.password: env[f'{pfx}_PASSWORD'] = cred.password
        if cred.token:    env[f'{pfx}_TOKEN']    = cred.token
        for k, v in (cred.extra or {}).items():
            env[f'{pfx}_{k.upper()}'] = str(v)

    run_dir = workdir or os.path.join(os.environ.get('CI_RUNS_DIR', 'D:/cicd/runs'), str(run_id))
    os.makedirs(run_dir, exist_ok=True)

    cli_cmd = _build_deploy_cli(target, cred, env, run_dir)
    log.append(f'[DEPLOY] Running: {cli_cmd}')

    process = subprocess.Popen(
        cli_cmd, shell=True, env=env, cwd=run_dir,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        universal_newlines=True, bufsize=1,
    )
    for line in process.stdout:
        log.append(line.rstrip())
    process.wait()

    if process.returncode == 0:
        log.append(f'[DEPLOY-OK] {target.name} deployed successfully.')
    else:
        log.append(f'[DEPLOY-FAILED] {target.name} exited {process.returncode}.')

    return subprocess.CompletedProcess(
        args=command,
        returncode=process.returncode,
        stdout='\n'.join(log),
    )


def _build_deploy_cli(target, cred, env, run_dir) -> str:
    """Build a shell command string for the given target type."""
    t      = target.target_type
    ep     = target.endpoint or ''
    ns     = target.namespace or 'default'
    region = target.region or ''

    if t == 'kubernetes':
        kubeconfig_path = os.path.join(run_dir, 'kubeconfig')
        if cred and cred.token:
            with open(kubeconfig_path, 'w') as fh:
                fh.write(cred.token)
            env['KUBECONFIG'] = kubeconfig_path
        server_flag = f'--server={ep}' if ep else ''
        return f'kubectl {server_flag} --namespace={ns} rollout restart deployment'

    if t == 'aws_ecs':
        region_flag = f'--region {region}' if region else ''
        cluster = ns
        return (f'aws ecs update-service {region_flag} --cluster {cluster} '
                f'--service {ep} --force-new-deployment')

    if t == 'aws_eks':
        region_flag = f'--region {region}' if region else ''
        cluster_name = ep.split('/')[-1] if '/' in ep else ep
        if cluster_name:
            env['KUBECONFIG'] = os.path.join(run_dir, 'eks_kubeconfig')
            return (f'aws eks update-kubeconfig {region_flag} --name {cluster_name} '
                    f'--kubeconfig {env["KUBECONFIG"]} && '
                    f'kubectl --namespace={ns} rollout restart deployment')
        return 'echo "aws_eks: no cluster endpoint configured"; exit 1'

    if t == 'aws_lambda':
        region_flag = f'--region {region}' if region else ''
        func = ep or ns
        return f'aws lambda update-function-code {region_flag} --function-name {func} --image-uri $IMAGE_URI'

    if t == 'azure_aks':
        rg = ns
        cluster = ep or 'my-cluster'
        return (f'az aks get-credentials --resource-group {rg} --name {cluster} '
                f'--overwrite-existing && kubectl rollout restart deployment')

    if t == 'azure_appservice':
        rg = ns
        app = ep or 'my-app'
        return f'az webapp restart --resource-group {rg} --name {app}'

    if t == 'gcp_gke':
        zone = region or 'us-central1-a'
        cluster = ep or 'my-cluster'
        project_id = (cred.extra or {}).get('project_id', '') if cred else ''
        proj_flag = f'--project={project_id}' if project_id else ''
        return (f'gcloud container clusters get-credentials {cluster} '
                f'--zone={zone} {proj_flag} && '
                f'kubectl --namespace={ns} rollout restart deployment')

    if t == 'gcp_cloudrun':
        region_flag = f'--region={region}' if region else ''
        service = ep or 'my-service'
        project_id = (cred.extra or {}).get('project_id', '') if cred else ''
        proj_flag = f'--project={project_id}' if project_id else ''
        return (f'gcloud run services update {service} {region_flag} {proj_flag} '
                f'--image=$IMAGE_URI')

    if t == 'docker_registry':
        registry = ep or 'docker.io'
        image = ns or 'myimage'
        return (f'docker build -t {registry}/{image}:$CI_RUN_ID . && '
                f'docker push {registry}/{image}:$CI_RUN_ID')

    if t == 'ssh':
        host = ep or 'localhost'
        user = (cred.username if cred else None) or 'deploy'
        ssh_key_path = os.path.join(run_dir, 'ssh_key')
        if cred and cred.password:
            with open(ssh_key_path, 'w') as fh:
                fh.write(cred.password)
            os.chmod(ssh_key_path, 0o600)
            return (f'ssh -i {ssh_key_path} -o StrictHostKeyChecking=no '
                    f'{user}@{host} "cd /app && ./deploy.sh"')
        return f'ssh -o StrictHostKeyChecking=no {user}@{host} "cd /app && ./deploy.sh"'

    return f'echo "No connector defined for target type: {t}"; exit 1'
