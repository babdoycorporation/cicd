"""
pipeline/utils.py  —  Execution helpers for the CI pipeline runner
"""

import hashlib
import io
import logging
import os
import platform
import shutil
import socket
import subprocess

import git
from django.conf import settings
from django.utils import timezone
from git import Repo

from .models import Agent, Credential

logger = logging.getLogger(__name__)

BASE_RUNS_DIR = os.environ.get(
    'CI_RUNS_DIR',
    getattr(
        settings,
        'CI_RUNS_DIR',
        str(settings.BASE_DIR / 'runs') if os.name != 'nt' else 'D:/cicd/runs',
    ),
)
ARTIFACTS_DIR = os.environ.get(
    'CI_ARTIFACTS_DIR',
    getattr(settings, 'CI_ARTIFACTS_DIR', str(settings.BASE_DIR / 'artifacts')),
)


def _resolve_repo_path(repo_name: str) -> str:
    """Resolve bare/working repository path on disk using GlobalSettings and settings.REPO_BASE_PATH."""
    candidates = []
    try:
        from .models import GlobalSettings
        setting = GlobalSettings.objects.filter(key='REPO_STORAGE_PATH').first()
        if setting and setting.value and setting.value.strip():
            candidates.append(setting.value.strip())
    except Exception:
        pass

    default_base = getattr(settings, 'REPO_BASE_PATH', str(settings.BASE_DIR / 'repos'))
    if default_base not in candidates:
        candidates.append(default_base)

    for base in candidates:
        for suffix in (f"{repo_name}.git", repo_name):
            path = os.path.join(base, suffix)
            if os.path.exists(path):
                return path

    primary = candidates[0] if candidates else default_base
    return os.path.join(primary, f"{repo_name}.git")


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
    if os.name != 'nt':
        current_path = env.get('PATH', '')
        env['PATH'] = f"/opt/cicd/venv/bin:/usr/local/bin:/usr/bin:/bin:{current_path}"
    if credentials:
        env.update({str(k): str(v) for k, v in credentials.items()})

    # ── git clone shortcut ────────────────────────────────────────────────────
    if command.lower().startswith('git clone'):
        return _handle_git_clone(command, run_dir, env)

    # ── General command ───────────────────────────────────────────────────────
    logger.debug(f"Running: {command}")
    popen_kwargs = {
        'shell': True,           # shell=True retained for pipeline flexibility
        'env': env,
        'cwd': run_dir,
        'stdout': subprocess.PIPE,
        'stderr': subprocess.STDOUT,
        'universal_newlines': True,
        'bufsize': 1,
    }
    if os.name != 'nt' and os.path.exists('/bin/bash'):
        popen_kwargs['executable'] = '/bin/bash'

    process = subprocess.Popen(command, **popen_kwargs)
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
                condition: on_success | always | on_failure  (optional)

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

    if not isinstance(parsed, dict):
        return 0

    steps = []

    # ── Top-level steps format (e.g. .rocketci.yml / native flat) ─────────
    if 'steps' in parsed and isinstance(parsed.get('steps'), list):
        for s in parsed['steps']:
            if not isinstance(s, dict):
                continue
            cmd = s.get('command') or s.get('run')
            if cmd:
                name = s.get('name') or str(cmd)[:60]
                cond = str(s.get('condition') or s.get('if') or '').strip().lower()
                steps.append((str(name)[:100], str(cmd), cond))

    # ── rockerci stage-based format: stages → steps → command ─────────────
    elif 'stages' in parsed:
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
                    cond = str(s.get('condition') or '').strip().lower()
                    steps.append((str(name)[:100], str(cmd), cond))

    # ── GitHub Actions format: jobs → steps → run ─────────────────────────
    elif 'jobs' in parsed:
        for job_name, job in (parsed.get('jobs') or {}).items():
            for s in ((job or {}).get('steps') or []):
                if not isinstance(s, dict):
                    continue
                cmd = s.get('run') or s.get('command')
                if cmd:
                    name = s.get('name') or str(cmd)[:60]
                    cond = str(s.get('condition') or s.get('if') or '').strip().lower()
                    if 'failure()' in cond:
                        cond = 'on_failure'
                    elif 'always()' in cond:
                        cond = 'always'
                    elif cond not in ('always', 'on_failure', 'on_success'):
                        cond = ''
                    steps.append((str(name)[:100], str(cmd), cond))

    if not steps:
        logger.warning(f"sync_steps_from_yaml: no steps found in YAML for {pipeline.name}")
        return 0

    PipelineStep.objects.filter(pipeline=pipeline).delete()
    for name, cmd, cond in steps:
        PipelineStep.objects.create(pipeline=pipeline, name=name, command=cmd, condition=cond)
    logger.info(f"Synced {len(steps)} steps from YAML for pipeline {pipeline.name}")
    return len(steps)


def sync_pipeline_from_repo_workdir(pipeline, workdir):
    """
    If a matching YAML config file exists inside the checked-out repository
    workspace, update YamlFileVersion and sync PipelineSteps before running.
    Returns number of synced steps (0 if no valid YAML file was present).
    """
    from .models import YamlFileVersion

    if not pipeline or not workdir or not os.path.isdir(workdir):
        return 0

    yp = (pipeline.yaml_path or '').strip()
    if yp.lower() in ('none', 'manual', 'disabled'):
        return 0

    candidates = [yp] if yp else []
    for alt in ('rockerci.yaml', '.rocketci.yml', 'rocketci.yml', '.rockerci.yaml', '.rockerci.yml'):
        if alt not in candidates:
            candidates.append(alt)

    for rel_path in candidates:
        full_path = os.path.join(workdir, rel_path)
        if os.path.isfile(full_path):
            try:
                with open(full_path, 'r', encoding='utf-8', errors='replace') as fh:
                    yaml_content = fh.read()
                n_steps = sync_steps_from_yaml(pipeline, yaml_content)
                if n_steps > 0:
                    version = YamlFileVersion.objects.filter(pipeline=pipeline).count() + 1
                    YamlFileVersion.objects.create(
                        pipeline=pipeline,
                        version_number=version,
                        yaml_content=yaml_content,
                    )
                    return n_steps
            except Exception as exc:
                logger.warning(f"Failed syncing YAML {rel_path} for {pipeline.name}: {exc}")
    return 0


def checkout_repository(run, run_dir):
    """
    Clone the pipeline's linked repository (local bare repo) into the run
    directory at the monitored branch. Returns (workdir, log_lines).
    Falls back to the run dir when no repository is linked.
    """
    log = []
    app = run.pipeline.application
    repo = app.linked_repository if app else None
    if not repo:
        log.append("[INFO] No repository linked; steps run in an empty workspace.")
        return run_dir, log

    bare_path = _resolve_repo_path(repo.name)
    workdir = os.path.join(run_dir, repo.name)
    branch = run.pipeline.monitored_branch or repo.default_branch or 'main'

    try:
        if os.path.exists(workdir):
            shutil.rmtree(workdir, ignore_errors=True)
        log.append(f"[CHECKOUT] {repo.name} @ {branch} (from {bare_path})")
        Repo.clone_from(bare_path, workdir, branch=branch)
        cloned = Repo(workdir)
        try:
            head = cloned.head.commit
            log.append(f"[CHECKOUT] HEAD {head.hexsha[:10]} — {head.summary}")
        finally:
            cloned.close()
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

    global_creds = Credential.objects.filter(scope_level='global')
    for cred in global_creds:
        clean_svc = cred.service_name.upper().replace(' ', '_').replace('-', '_')
        prefix = f"GLOBAL_{clean_svc}"
        credentials[f"{prefix}_USERNAME"] = cred.username
        credentials[f"{prefix}_PASSWORD"] = cred.password
        credentials[f"{prefix}_TOKEN"] = cred.token

    if project is None:
        return credentials

    local_creds = Credential.objects.filter(scope_level='project', project=project)
    for cred in local_creds:
        clean_svc = cred.service_name.upper().replace(' ', '_').replace('-', '_')
        prefix = f"LOCAL_{clean_svc}"
        credentials[f"{prefix}_USERNAME"] = cred.username
        credentials[f"{prefix}_PASSWORD"] = cred.password
        credentials[f"{prefix}_TOKEN"] = cred.token

    # Also expose project env vars
    if project.environment_variables and isinstance(project.environment_variables, dict):
        credentials.update({str(k): str(v) for k, v in project.environment_variables.items()})

    logger.debug(f"Prepared {len(credentials)} credential/env entries for {project.name}")
    return credentials


# ─────────────────────────────────────────────────────────────────────────────
#  Agent selection & Built-in Local Server Runner
# ─────────────────────────────────────────────────────────────────────────────

def ensure_local_runner_agent():
    """
    Ensure a built-in local CI runner Agent exists and refresh its heartbeat
    when it is not currently executing a run.
    """
    from .models import PipelineRun

    hostname = f"{socket.gethostname()}-local" if socket.gethostname() else "local-cicd-runner"
    hkey = hashlib.sha256(f"local-runner-{hostname}".encode()).hexdigest()[:32]
    os_name = f"{platform.system()} {platform.release()}"

    agent = Agent.objects.filter(hostname=hostname).first()
    if not agent:
        # Also reuse existing 127.0.0.1 agent if registered under another hostname
        agent = Agent.objects.filter(ip_address='127.0.0.1').first()
    if not agent:
        agent, _ = Agent.objects.get_or_create(
            hash_key=hkey,
            defaults={
                'hostname': hostname[:255],
                'ip_address': '127.0.0.1',
                'operating_system': os_name[:100],
                'live': True,
                'last_heartbeat': timezone.now(),
            },
        )
    else:
        is_busy = PipelineRun.objects.filter(agent=agent, status='running').exists()
        agent.last_heartbeat = timezone.now()
        update_fields = ['last_heartbeat']
        if not is_busy and not agent.live:
            agent.live = True
            update_fields.append('live')
        agent.save(update_fields=update_fields)
    return agent


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
    base = getattr(settings, 'CI_RUNS_DIR', os.environ.get('CI_RUNS_DIR', str(settings.BASE_DIR / 'runs')))
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

    Looks up the DeploymentTarget, builds/runs the deployment command from its
    fields and attached credential, and returns a CompletedProcess-like object
    with .returncode and .stdout.
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
    env = os.environ.copy()
    log = [f'[DEPLOY] Target: {target.name} ({target.get_target_type_display()})']

    # Inject credential values as env vars
    if cred:
        clean_svc = cred.service_name.upper().replace(' ', '_').replace('-', '_')
        pfx = f'DEPLOY_{clean_svc}'
        if cred.username: env[f'{pfx}_USERNAME'] = cred.username
        if cred.password: env[f'{pfx}_PASSWORD'] = cred.password
        if cred.token:    env[f'{pfx}_TOKEN']    = cred.token
        for k, v in (cred.extra or {}).items():
            env[f'{pfx}_{str(k).upper()}'] = str(v)

    run_dir = workdir or os.path.join(BASE_RUNS_DIR, str(run_id))
    os.makedirs(run_dir, exist_ok=True)

    # Use native Paramiko SSH handler when target_type == 'ssh'
    if target.target_type == 'ssh':
        return _execute_ssh_deploy(command, target, cred, env, run_dir, log)

    cli_cmd = _build_deploy_cli(target, cred, env, run_dir)
    log.append(f'[DEPLOY] Running: {cli_cmd}')

    popen_kwargs = {
        'shell': True,
        'env': env,
        'cwd': run_dir,
        'stdout': subprocess.PIPE,
        'stderr': subprocess.STDOUT,
        'universal_newlines': True,
        'bufsize': 1,
    }
    if os.name != 'nt' and os.path.exists('/bin/bash'):
        popen_kwargs['executable'] = '/bin/bash'

    process = subprocess.Popen(cli_cmd, **popen_kwargs)
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


def _parse_ssh_target(target, cred):
    """Resolve host, port, username, remote deploy command, key and password."""
    extra = (cred.extra or {}) if cred else {}

    raw_ep = (target.endpoint or 'localhost').strip()
    host = raw_ep
    port = 22
    if ':' in raw_ep and not raw_ep.startswith('['):
        h_part, p_part = raw_ep.rsplit(':', 1)
        if p_part.isdigit():
            host = h_part.strip()
            port = int(p_part)

    if extra.get('port') and str(extra.get('port')).isdigit():
        port = int(extra['port'])
    elif (target.region or '').strip().isdigit():
        port = int(target.region.strip())

    user = (cred.username if cred and cred.username else None) or 'deploy'

    deploy_cmd = (extra.get('deploy_command') or '').strip()
    if not deploy_cmd:
        ns = (target.namespace or '').strip()
        if ns.startswith('/'):
            deploy_cmd = f'cd "{ns}" && ./deploy.sh'
        elif ns:
            deploy_cmd = ns
        else:
            deploy_cmd = 'cd /app && ./deploy.sh'

    # Detect whether key material is provided in token or password
    key_text = ''
    password = ''
    if cred:
        if cred.token and 'PRIVATE KEY' in cred.token:
            key_text = cred.token.strip()
            password = cred.password or ''
        elif cred.password and 'PRIVATE KEY' in cred.password:
            key_text = cred.password.strip()
        else:
            password = cred.password or ''

    return host, port, user, deploy_cmd, key_text, password


def _execute_ssh_deploy(command, target, cred, env, run_dir, log):
    """Execute SSH deployment over custom port with key or password auth."""
    host, port, user, deploy_cmd, key_text, password = _parse_ssh_target(target, cred)
    log.append(f'[DEPLOY-SSH] Connecting to {user}@{host}:{port}')
    log.append(f'[DEPLOY-SSH] Remote command: {deploy_cmd}')

    try:
        import paramiko
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        connect_kwargs = {
            'hostname': host,
            'port': port,
            'username': user,
            'timeout': 30,
        }
        if key_text:
            pkey = None
            for key_cls in (paramiko.Ed25519Key, paramiko.RSAKey, paramiko.ECDSAKey):
                try:
                    pkey = key_cls.from_private_key(io.StringIO(key_text), password=password or None)
                    break
                except Exception:
                    continue
            if pkey is None:
                raise ValueError("Unable to parse SSH private key (supported: Ed25519, RSA, ECDSA).")
            connect_kwargs['pkey'] = pkey
        elif password:
            connect_kwargs['password'] = password

        client.connect(**connect_kwargs)
        try:
            stdin, stdout, stderr = client.exec_command(deploy_cmd, get_pty=False)
            for line in iter(stdout.readline, ''):
                log.append(line.rstrip())
            err_out = stderr.read().decode('utf-8', errors='replace')
            if err_out.strip():
                for el in err_out.splitlines():
                    log.append(f'[STDERR] {el}')
            rc = stdout.channel.recv_exit_status()
        finally:
            client.close()

        if rc == 0:
            log.append(f'[DEPLOY-OK] {target.name} deployed successfully.')
        else:
            log.append(f'[DEPLOY-FAILED] {target.name} exited {rc}.')
        return subprocess.CompletedProcess(args=command, returncode=rc, stdout='\n'.join(log))
    except ImportError:
        log.append('[DEPLOY-SSH] paramiko not installed; falling back to OpenSSH CLI...')
    except Exception as exc:
        log.append(f'[DEPLOY-FAILED] SSH error: {exc}')
        return subprocess.CompletedProcess(args=command, returncode=1, stdout='\n'.join(log))

    # OpenSSH fallback (key auth on custom port)
    cli_cmd = _build_deploy_cli(target, cred, env, run_dir)
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
    return subprocess.CompletedProcess(args=command, returncode=process.returncode, stdout='\n'.join(log))


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
        host, port, user, deploy_cmd, key_text, _ = _parse_ssh_target(target, cred)
        ssh_key_path = os.path.join(run_dir, 'ssh_key')
        if key_text:
            with open(ssh_key_path, 'w') as fh:
                fh.write(key_text + '\n')
            os.chmod(ssh_key_path, 0o600)
            return (f'ssh -i {ssh_key_path} -p {port} -o StrictHostKeyChecking=no '
                    f'{user}@{host} "{deploy_cmd}"')
        return f'ssh -p {port} -o StrictHostKeyChecking=no {user}@{host} "{deploy_cmd}"'

    return f'echo "No connector defined for target type: {t}"; exit 1'
