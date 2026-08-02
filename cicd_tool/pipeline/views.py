"""
pipeline/views.py — All CI/CD views
Bugs fixed:
  • pipeline_create: pipeline_id undefined, application_name undefined, wrong FK
  • run_pipeline: pipeline.project undefined, pipeline_id undefined
  • local_credential_delete: project_name undefined
  • local_credential_update: redirect used project_id instead of project_name
  • create_yaml_pipeline: Pipeline.get_or_create used non-existent project FK
  • check_agent_status: last_heartbeat could be None → now guarded
"""

import json
import logging
import os
import subprocess
import uuid
from datetime import timedelta

import yaml
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.management import call_command
from django.db.models import Count
from django.db.models.functions import TruncDate
from django.http import (Http404, HttpResponse, JsonResponse,
                          StreamingHttpResponse)
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from gitmgmt.models import Repository
from .forms import (AgentForm, ApplicationForm, DeploymentTargetForm,
                     GlobalCredentialForm, GlobalSettingsForm,
                     LocalCredentialForm, PipelineForm,
                     ProjectConfigurationForm, ProjectForm)
from .models import (Agent, Application, BuildArtifact, Command, Credential,
                      DeploymentTarget, Environment, GlobalSettings,
                      Heartbeat, NotificationIntegration, Pipeline,
                      PipelineRun, PipelineStep, Project, ProjectPipeline,
                      ProjectPipelineRun, ProjectOrchestrationStep, Stage,
                      Step, UserNotificationPreference, YamlFileVersion)
from .utils import execute_step, get_available_agent, prepare_credentials

logger = logging.getLogger(__name__)
BASE_REPO_DIR = 'D:/cicd/'


# ─────────────────────────────────────────────────────────────────────────────
#  Dashboard
# ─────────────────────────────────────────────────────────────────────────────

class DashboardView(View):
    def get(self, request):
        total_projects = Project.objects.count()
        total_applications = Application.objects.count()
        total_pipelines = Pipeline.objects.count()
        total_pipeline_runs = PipelineRun.objects.count()
        total_agents = Agent.objects.count()
        successful_runs = PipelineRun.objects.filter(status='success').count()
        failed_runs = PipelineRun.objects.filter(status='failed').count()
        pending_runs = PipelineRun.objects.filter(status='pending').count()
        running_runs = PipelineRun.objects.filter(status='running').count()
        total_repos = Repository.objects.count()
        latest_pipeline_runs = (
            PipelineRun.objects.select_related('pipeline', 'agent')
            .order_by('-started_at')[:10]
        )
        live_agents = Agent.objects.filter(live=True).count()

        # All-time success/fail chart data grouped by date
        chart_data = (
            PipelineRun.objects
            .annotate(date=TruncDate('started_at'))
            .values('date', 'status')
            .annotate(count=Count('id'))
            .order_by('date')
        )
        date_set = sorted({row['date'] for row in chart_data if row['date']})
        stats = {d: {'success': 0, 'failed': 0} for d in date_set}
        for row in chart_data:
            if row['date'] in stats and row['status'] in ('success', 'failed'):
                stats[row['date']][row['status']] = row['count']
        chart_labels = [d.isoformat() for d in date_set]
        chart_success = [stats[d]['success'] for d in date_set]
        chart_failed = [stats[d]['failed'] for d in date_set]

        context = {
            'total_projects': total_projects,
            'total_applications': total_applications,
            'total_pipelines': total_pipelines,
            'total_pipeline_runs': total_pipeline_runs,
            'total_agents': total_agents,
            'successful_runs': successful_runs,
            'failed_runs': failed_runs,
            'pending_runs': pending_runs,
            'running_runs': running_runs,
            'latest_pipeline_runs': latest_pipeline_runs,
            'total_repos': total_repos,
            'live_agents': live_agents,
            'chart_labels': json.dumps(chart_labels),
            'chart_success': json.dumps(chart_success),
            'chart_failed': json.dumps(chart_failed),
        }
        return render(request, 'pipeline/dashboard.html', context)


# ─────────────────────────────────────────────────────────────────────────────
#  Projects
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def project_list(request):
    projects = Project.objects.all()
    return render(request, 'pipeline/project_list.html', {'projects': projects})


@login_required
def project_detail(request, project_name):
    project = get_object_or_404(Project, name=project_name)
    orchestrator_runs = ProjectPipelineRun.objects.filter(project_pipeline__project=project).order_by('-started_at')[:20]
    pipeline_runs = PipelineRun.objects.filter(
        pipeline__application__project=project
    ).select_related('pipeline', 'agent').order_by('-started_at')[:20]
    applications = Application.objects.filter(project=project).prefetch_related('pipelines')
    project_pipelines = ProjectPipeline.objects.filter(project=project)
    
    my_role = project.get_member_role(request.user)
    if not my_role and (request.user.is_superuser or (project.members.count() == 0 and project.organization is None)):
        my_role = 'maintainer'
    elif not my_role:
        my_role = 'viewer'

    return render(request, 'pipeline/project_detail.html', {
        'project': project, 'orchestrator_runs': orchestrator_runs, 'pipeline_runs': pipeline_runs,
        'applications': applications, 'project_pipelines': project_pipelines,
        'my_role': my_role,
    })


@login_required
def project_create(request):
    if request.method == 'POST':
        form = ProjectForm(request.POST)
        if form.is_valid():
            org = form.cleaned_data.get('organization')
            # Enforce the organization's project-creation policy
            if org and not (request.user.is_superuser or org.user_can_create_projects(request.user)):
                form.add_error('organization',
                    f"Your role in {org.name} does not allow creating projects "
                    f"(policy: {org.get_project_creation_policy_display()}).")
            else:
                project = form.save()
                # The creator becomes the project's first maintainer
                from .models import ProjectMember
                ProjectMember.objects.get_or_create(
                    project=project, user=request.user, defaults={'role': 'maintainer'})
                return redirect('project_list')
    else:
        form = ProjectForm()
    return render(request, 'pipeline/project_form.html', {'form': form})


@login_required
def project_edit(request, project_name):
    project = get_object_or_404(Project, name=project_name)
    if request.method == 'POST':
        form = ProjectForm(request.POST, instance=project)
        if form.is_valid():
            form.save()
            return redirect('project_list')
    else:
        form = ProjectForm(instance=project)
    return render(request, 'pipeline/project_form.html', {'form': form})


@login_required
def project_delete(request, project_name):
    project = get_object_or_404(Project, name=project_name)
    if request.method == 'POST':
        project.delete()
        return redirect('project_list')
    return render(request, 'pipeline/project_confirm_delete.html', {'project': project})


@login_required
def configure_project(request, project_name):
    project = get_object_or_404(Project, name=project_name)
    if request.method == 'POST':
        form = ProjectConfigurationForm(request.POST, instance=project)
        if form.is_valid():
            form.save()
            return redirect('project_detail', project_name=project_name)
    else:
        form = ProjectConfigurationForm(instance=project)
    return render(request, 'pipeline/configure_project.html', {'form': form, 'project': project})


@login_required
def project_settings(request, project_name):
    """Project settings — general, members with roles, CI/CD variables, notifications."""
    import json as _json
    from django.contrib.auth.models import User
    from .models import ProjectMember

    project = get_object_or_404(Project, name=project_name)

    my_role = project.get_member_role(request.user)
    is_open_project = project.members.count() == 0 and project.organization is None
    can_manage = (request.user.is_superuser or my_role == 'maintainer' or is_open_project)
    if not can_manage:
        messages.error(request, "You need the Maintainer role to manage project settings.")
        return redirect('project_detail', project_name=project.name)

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'update_general':
            project.description = request.POST.get('description', project.description)
            project.repository_url = request.POST.get('repository_url', '') or None
            project.save()
            messages.success(request, "Project details updated.")

        elif action == 'update_variables':
            raw = request.POST.get('environment_variables', '{}').strip() or '{}'
            try:
                parsed = _json.loads(raw)
                if not isinstance(parsed, dict):
                    raise ValueError('Must be a JSON object')
                project.environment_variables = parsed
                project.save()
                messages.success(request, "CI/CD variables updated.")
            except ValueError:
                messages.error(request, 'Variables must be a JSON object, e.g. {"KEY": "value"}.')

        elif action == 'update_notifications':
            project.notifications_enabled = request.POST.get('notifications_enabled') == 'on'
            project.notification_emails = request.POST.get('notification_emails', '')
            project.slack_webhook_url = request.POST.get('slack_webhook_url', '')
            project.save()
            messages.success(request, "Notification settings updated.")

        elif action == 'add_member':
            username = request.POST.get('username', '').strip()
            role = request.POST.get('role', 'developer')
            if role not in ('maintainer', 'developer', 'viewer'):
                role = 'developer'
            user = User.objects.filter(username=username).first()
            if user:
                ProjectMember.objects.update_or_create(
                    project=project, user=user, defaults={'role': role})
                messages.success(request, f"{username} added as {role}.")
            else:
                messages.error(request, f"User '{username}' not found.")

        elif action == 'update_member_role':
            member = ProjectMember.objects.filter(
                project=project, id=request.POST.get('member_id')).first()
            new_role = request.POST.get('role')
            if member and new_role in ('maintainer', 'developer', 'viewer'):
                member.role = new_role
                member.save()
                messages.success(request, f"{member.user.username} is now {new_role}.")

        elif action == 'remove_member':
            member = ProjectMember.objects.filter(
                project=project, id=request.POST.get('member_id')).first()
            if member:
                member.delete()
                messages.success(request, f"{member.user.username} removed from the project.")

        return redirect('project_settings', project_name=project.name)

    members = project.members.select_related('user').order_by('user__username')
    import json as _json
    env_vars_json = _json.dumps(project.environment_variables or {}, indent=2)
    return render(request, 'pipeline/project_settings.html', {
        'project': project,
        'members': members,
        'env_vars_json': env_vars_json,
        'my_role': my_role or ('maintainer' if request.user.is_superuser or is_open_project else None),
    })

@login_required
def trigger_project_pipeline(request, project_name):
    project = get_object_or_404(Project, name=project_name)
    if request.method == 'POST':
        pipeline_id = request.POST.get('project_pipeline_id')
        project_pipeline = get_object_or_404(ProjectPipeline, id=pipeline_id, project=project)
        # Create a new run
        run = ProjectPipelineRun.objects.create(project_pipeline=project_pipeline, status='pending', log='Orchestrator run queued.')
        # We will dispatch this to the background worker
        return redirect('project_pipeline_run_detail', run_id=run.run_id)
    return redirect('project_detail', project_name=project.name)

@login_required
def project_pipeline_run_detail(request, run_id):
    run = get_object_or_404(ProjectPipelineRun, run_id=run_id)
    return render(request, 'pipeline/project_pipeline_run_detail.html', {'run': run})

@login_required
def project_pipeline_history(request, project_name):
    project = get_object_or_404(Project, name=project_name)
    runs = ProjectPipelineRun.objects.filter(project_pipeline__project=project).order_by('-started_at')
    
    # 7-day build stats
    end = timezone.now()
    start = end - timedelta(days=7)
    build_history_data = (
        ProjectPipelineRun.objects
        .filter(started_at__gte=start, project_pipeline__project=project)
        .annotate(date=TruncDate('started_at'))
        .values('date', 'status')
        .annotate(count=Count('id'))
        .order_by('date')
    )
    date_range = [(start + timedelta(days=i)).date() for i in range(8)]
    build_stats = {d: {'success': 0, 'failed': 0} for d in date_range}
    for entry in build_history_data:
        d = entry['date']
        if d in build_stats and entry['status'] in ('success', 'failed'):
            build_stats[d][entry['status']] = entry['count']

    data = {
        'dates': [d.isoformat() for d in date_range],
        'successful_builds': [build_stats[d]['success'] for d in date_range],
        'failed_builds': [build_stats[d]['failed'] for d in date_range],
    }
    return render(request, 'pipeline/build_history.html', {
        'build_history_data': json.dumps(data), 'project': project,
    })

@login_required
def project_pipeline_create(request, project_name):
    import yaml
    project = get_object_or_404(Project, name=project_name)
    if request.method == 'POST':
        yaml_content = request.POST.get('yaml_content', '')
        try:
            config = yaml.safe_load(yaml_content)
            if not config or 'name' not in config:
                raise ValueError("YAML must contain a 'name' field.")
            
            project_pipeline = ProjectPipeline.objects.create(
                project=project,
                name=config['name'],
                description=config.get('description', ''),
                yaml_path='ui-defined'
            )
            
            steps = config.get('steps', [])
            for step_data in steps:
                target_pipeline_name = step_data.get('target_pipeline')
                target = Pipeline.objects.filter(name=target_pipeline_name, application__project=project).first()
                if not target:
                    raise ValueError(f"Target pipeline '{target_pipeline_name}' not found in this project.")
                ProjectOrchestrationStep.objects.create(
                    project_pipeline=project_pipeline,
                    order=step_data.get('order', 0),
                    target_pipeline=target,
                    parallel=step_data.get('parallel', False)
                )
            messages.success(request, f"Successfully created orchestrator '{project_pipeline.name}'.")
            return redirect('project_detail', project_name=project.name)
        except Exception as e:
            messages.error(request, f"Error parsing YAML: {str(e)}")
            return render(request, 'pipeline/project_pipeline_form.html', {'project': project, 'yaml_content': yaml_content})
            
    # Default template
    default_yaml = '''name: Release To Production
description: Deploys backend then frontend
steps:
  - target_pipeline: your-backend-ci
    order: 1
    parallel: false
  - target_pipeline: your-frontend-ci
    order: 2
    parallel: false
'''
    return render(request, 'pipeline/project_pipeline_form.html', {'project': project, 'yaml_content': default_yaml})

@login_required
def project_pipeline_delete(request, project_name, pipeline_id):
    project = get_object_or_404(Project, name=project_name)
    pipeline = get_object_or_404(ProjectPipeline, id=pipeline_id, project=project)
    if request.method == 'POST':
        pipeline.delete()
        messages.success(request, f"Orchestrator '{pipeline.name}' deleted.")
    return redirect('project_detail', project_name=project.name)

# ==============================================================================
#  Pipelines
# ==============================================================================─────────────────────────────────────────────────────────────────────────────

@login_required
def pipeline_list(request, project_name):
    project = get_object_or_404(Project, name=project_name)
    pipelines = Pipeline.objects.filter(application__project=project)
    return render(request, 'pipeline/pipeline_list.html', {'project': project, 'pipelines': pipelines})


@login_required
def pipeline_create(request, project_name):
    """BUG FIX: removed references to undefined pipeline_id / application_name."""
    project = get_object_or_404(Project, name=project_name)
    applications = project.applications.all()

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()
        application_id = request.POST.get('application')
        yaml_path = request.POST.get('yaml_path', 'rockerci.yaml').strip()
        monitored_branch = request.POST.get('monitored_branch', 'main').strip()

        if not name:
            return render(request, 'pipeline/pipeline_form.html', {
                'project': project, 'applications': applications,
                'error': 'Pipeline name is required.',
            })

        application = get_object_or_404(Application, id=application_id, project=project)
        Pipeline.objects.create(
            name=name,
            description=description,
            application=application,
            yaml_path=yaml_path,
            monitored_branch=monitored_branch,
        )
        return redirect('pipeline_list', project_name=project.name)

    return render(request, 'pipeline/pipeline_form.html', {
        'project': project, 'applications': applications,
    })


@login_required
def pipeline_update(request, project_name, pipeline_name):
    project = get_object_or_404(Project, name=project_name)
    pipeline = get_object_or_404(Pipeline, name=pipeline_name)
    if request.method == 'POST':
        pipeline.name = request.POST.get('name', pipeline.name)
        pipeline.description = request.POST.get('description', pipeline.description)
        pipeline.yaml_path = request.POST.get('yaml_path', pipeline.yaml_path)
        pipeline.monitored_branch = request.POST.get('monitored_branch', pipeline.monitored_branch)
        pipeline.save()
        return redirect('pipeline_list', project_name=project.name)
    return render(request, 'pipeline/pipeline_form.html', {'project': project, 'pipeline': pipeline})


@login_required
def pipeline_delete(request, project_name, pipeline_name):
    project = get_object_or_404(Project, name=project_name)
    pipeline = get_object_or_404(Pipeline, name=pipeline_name)
    if request.method == 'POST':
        pipeline.delete()
        return redirect('pipeline_list', project_name=project.name)
    return render(request, 'pipeline/pipeline_confirm_delete.html', {'project': project, 'pipeline': pipeline})


@login_required
def pipeline_detail(request, pipeline_name):
    pipeline = get_object_or_404(Pipeline, name=pipeline_name)
    steps = pipeline.pipelinestep_set.all().order_by('id')
    runs = pipeline.runs.order_by('-started_at')[:20]
    yaml_versions = YamlFileVersion.objects.filter(pipeline=pipeline).order_by('-created_at')[:10]
    return render(request, 'pipeline/pipeline_detail.html', {
        'pipeline': pipeline, 'steps': steps, 'runs': runs, 'yaml_versions': yaml_versions,
    })


# ─────────────────────────────────────────────────────────────────────────────
#  Pipeline Steps
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def pipeline_step_list(request, pipeline_name):
    pipeline = get_object_or_404(Pipeline, name=pipeline_name)
    steps = PipelineStep.objects.filter(pipeline=pipeline).order_by('id')
    return render(request, 'pipeline/pipeline_step_list.html', {'pipeline': pipeline, 'steps': steps})


@login_required
def pipeline_step_create(request, pipeline_name):
    pipeline = get_object_or_404(Pipeline, name=pipeline_name)
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()
        condition = request.POST.get('condition', '').strip()
        command = request.POST.get('command', '').strip()
        if not name or not command:
            return render(request, 'pipeline/pipeline_step_form.html', {
                'pipeline': pipeline, 'error': 'Name and command are required.',
            })
        PipelineStep.objects.create(
            pipeline=pipeline, name=name,
            description=description, condition=condition, command=command,
        )
        return redirect('pipeline_step_list', pipeline_name=pipeline.name)
    return render(request, 'pipeline/pipeline_step_form.html', {'pipeline': pipeline})


@login_required
def pipeline_step_update(request, pipeline_name, step_id):
    pipeline = get_object_or_404(Pipeline, name=pipeline_name)
    step = get_object_or_404(PipelineStep, id=step_id, pipeline=pipeline)
    if request.method == 'POST':
        step.name = request.POST.get('name', step.name)
        step.description = request.POST.get('description', step.description)
        step.condition = request.POST.get('condition', step.condition)
        step.command = request.POST.get('command', step.command)
        step.save()
        return redirect('pipeline_step_list', pipeline_name=pipeline.name)
    return render(request, 'pipeline/pipeline_step_form.html', {'pipeline': pipeline, 'step': step})


@login_required
def pipeline_step_delete(request, pipeline_name, step_id):
    pipeline = get_object_or_404(Pipeline, name=pipeline_name)
    step = get_object_or_404(PipelineStep, id=step_id, pipeline=pipeline)
    if request.method == 'POST':
        step.delete()
        return redirect('pipeline_step_list', pipeline_name=pipeline.name)
    return render(request, 'pipeline/pipeline_step_confirm_delete.html', {'pipeline': pipeline, 'step': step})


# ─────────────────────────────────────────────────────────────────────────────
#  Run Pipeline  (SSE streaming)
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def run_pipeline(request, pipeline_name):
    pipeline = get_object_or_404(Pipeline, name=pipeline_name)
    
    # Create a pending PipelineRun. The background worker will pick it up.
    pipeline_run = PipelineRun.objects.create(pipeline=pipeline, status='pending')
    
    return redirect('pipeline_run_detail', run_id=pipeline_run.run_id)


from django.http import JsonResponse

@login_required
def pipeline_run_api(request, run_id):
    run = get_object_or_404(PipelineRun, run_id=run_id)
    return JsonResponse({
        'status': run.status,
        'log': run.log or '',
        'finished_at': run.finished_at.isoformat() if run.finished_at else None,
    })

def project_pipeline_run_api(request, run_id):
    run = get_object_or_404(ProjectPipelineRun, run_id=run_id)
    return JsonResponse({
        'status': run.status,
        'log': run.log or '',
        'finished_at': run.finished_at.isoformat() if run.finished_at else None,
    })

@login_required
def pipeline_run_detail(request, run_id):
    run = get_object_or_404(PipelineRun, run_id=run_id)
    log_lines = run.log.splitlines() if run.log else []
    duration = None
    if run.finished_at and run.started_at:
        duration = (run.finished_at - run.started_at).seconds
    return render(request, 'pipeline/pipeline_run_detail.html', {
        'pipeline_run': run, 'log_lines': log_lines, 'duration': duration,
    })


@login_required
def pipeline_run_list(request, pipeline_name):
    pipeline = get_object_or_404(Pipeline, name=pipeline_name)
    runs = pipeline.runs.select_related('agent').order_by('-started_at')
    return render(request, 'pipeline/pipeline_run_list.html', {'pipeline': pipeline, 'runs': runs})


@login_required
def cancel_pipeline_run(request, run_id):
    run = get_object_or_404(PipelineRun, run_id=run_id)
    if request.method == 'POST' and run.status in ('pending', 'running'):
        run.status = 'failed'
        run.finished_at = timezone.now()
        run.log = (run.log or '') + '\n[CANCELLED by user]'
        run.save()
        if run.agent:
            run.agent.live = True
            run.agent.save(update_fields=['live'])
    return redirect('pipeline_run_detail', run_id=str(run.run_id))


# ─────────────────────────────────────────────────────────────────────────────
#  Webhooks
# ─────────────────────────────────────────────────────────────────────────────

@csrf_exempt
def github_webhook(request):
    if request.method == 'POST':
        try:
            payload = json.loads(request.body.decode('utf-8'))
            project_name = payload.get('repository', {}).get('name')
            project = Project.objects.filter(name=project_name).first()
            if project:
                # Webhook received, do nothing for now since git-receive-pack handles it
                pass
                return JsonResponse({'status': 'success'})
            return JsonResponse({'status': 'project not found'}, status=404)
        except Exception as e:
            return JsonResponse({'status': 'error', 'detail': str(e)}, status=400)
    return JsonResponse({'status': 'method not allowed'}, status=405)


# ─────────────────────────────────────────────────────────────────────────────
#  Agents
# ─────────────────────────────────────────────────────────────────────────────

def _check_agent_status():
    """Mark agents live/dead based on heartbeat timestamp."""
    threshold = timedelta(minutes=1)
    now = timezone.now()
    for agent in Agent.objects.all():
        if agent.last_heartbeat is None:
            # Never heartbeated — treat as dead
            if agent.live:
                agent.live = False
                agent.save(update_fields=['live'])
            continue
        is_live = (now - agent.last_heartbeat) <= threshold
        if agent.live != is_live:
            agent.live = is_live
            agent.save(update_fields=['live'])


@login_required
def agent_list(request):
    _check_agent_status()
    agents = Agent.objects.all().order_by('-live', 'hostname')
    return render(request, 'pipeline/agent_list.html', {'agents': agents})


@login_required
def agent_detail(request, agent_hostname):
    agent = get_object_or_404(Agent, hostname=agent_hostname)
    pipeline_runs = PipelineRun.objects.filter(agent=agent).order_by('-started_at')[:20]
    return render(request, 'pipeline/agent_detail.html', {
        'agent': agent, 'pipeline_runs': pipeline_runs,
    })


@login_required
def add_agent(request):
    hash_key = uuid.uuid4().hex
    base = request.build_absolute_uri('/').rstrip('/')
    command_windows = (
        f'Invoke-WebRequest -Uri "{base}/static/agents/windows_agent.py" -OutFile agent.py; '
        f'python agent.py --hash-key {hash_key} --server {base}'
    )
    command_linux = (
        f'curl -O {base}/static/agents/linux_agent.py && '
        f'python3 linux_agent.py --hash-key {hash_key} --server {base}'
    )
    return render(request, 'pipeline/add_agent.html', {
        'hash_key': hash_key,
        'command_windows': command_windows,
        'command_linux': command_linux,
    })


@login_required
def send_command(request):
    if request.method == 'POST':
        hostname = request.POST.get('hostname')
        command = request.POST.get('command')
        agent = get_object_or_404(Agent, hostname=hostname)
        Command.objects.create(agent=agent, command=command)
        try:
            agent.send_command({'command': command})
            return JsonResponse({'status': 'success'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'detail': str(e)}, status=500)
    return JsonResponse({'status': 'error', 'message': 'POST required'}, status=405)


@login_required
def agent_instructions(request):
    return render(request, 'pipeline/agent_instructions.html')


@csrf_exempt
def register_agent(request):
    """Agent self-registration — validated by hash_key existence check."""
    if request.method != 'POST':
        return HttpResponse(status=405)
    try:
        data = json.loads(request.body.decode('utf-8'))
        hash_key = data.get('hash_key', '').strip()
        if not hash_key:
            return JsonResponse({'error': 'hash_key required'}, status=400)
        agent, created = Agent.objects.update_or_create(
            hash_key=hash_key,
            defaults={
                'hostname': data.get('hostname', ''),
                'ip_address': data.get('ip_address', ''),
                'operating_system': data.get('operating_system', ''),
                'last_heartbeat': timezone.now(),
                'live': True,
            }
        )
        status_msg = 'Agent registered.' if created else 'Agent updated.'
        return JsonResponse({'status': status_msg})
    except Exception as e:
        logger.error(f"Agent registration error: {e}")
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
def receive_heartbeat(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    try:
        data = json.loads(request.body.decode('utf-8'))
        hash_key = data.get('hash_key', '').strip()
        agent = Agent.objects.filter(hash_key=hash_key).first()
        if not agent:
            return JsonResponse({'error': 'Agent not found'}, status=404)
        agent.last_heartbeat = timezone.now()
        # Don't mark the agent available while it is executing a run
        busy = PipelineRun.objects.filter(agent=agent, status='running').exists()
        if not busy:
            agent.live = True
        agent.save(update_fields=['last_heartbeat', 'live'])
        return JsonResponse({'status': 'ok'})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
def receive_command(request):
    """Agents poll this for pending commands."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    try:
        data = json.loads(request.body.decode('utf-8'))
        hash_key = data.get('hash_key', '').strip()
        agent = Agent.objects.filter(hash_key=hash_key).first()
        if not agent:
            return JsonResponse({'error': 'Not found'}, status=404)
        cmd = Command.objects.filter(agent=agent).order_by('timestamp').first()
        if cmd:
            command_text = cmd.command
            cmd.delete()
            return JsonResponse({'status': 'ok', 'command': command_text})
        return JsonResponse({'status': 'ok', 'command': None})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


# ─────────────────────────────────────────────────────────────────────────────
#  Credentials
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def global_credential_list(request):
    credentials = Credential.objects.filter(scope_level='global')
    return render(request, 'pipeline/global_credential_list.html', {'credentials': credentials})


@login_required
def global_credential_detail(request, pk):
    cred = get_object_or_404(Credential, pk=pk)
    return render(request, 'pipeline/global_credential_detail.html', {'credential': cred})


@login_required
def global_credential_create(request):
    if request.method == 'POST':
        form = GlobalCredentialForm(request.POST)
        if form.is_valid():
            cred = form.save(commit=False)
            cred.scope_level = 'global'
            cred.save()
            return redirect('global_credential_list')
    else:
        form = GlobalCredentialForm()
    return render(request, 'pipeline/global_credential_form.html', {'form': form})


@login_required
def global_credential_update(request, pk):
    cred = get_object_or_404(Credential, pk=pk)
    if request.method == 'POST':
        form = GlobalCredentialForm(request.POST, instance=cred)
        if form.is_valid():
            form.save()
            return redirect('global_credential_list')
    else:
        form = GlobalCredentialForm(instance=cred)
    return render(request, 'pipeline/global_credential_form.html', {'form': form})


@login_required
def global_credential_delete(request, pk):
    cred = get_object_or_404(Credential, pk=pk)
    if request.method == 'POST':
        cred.delete()
        return redirect('global_credential_list')
    return render(request, 'pipeline/global_credential_confirm_delete.html', {'credential': cred})


@login_required
def local_credential_list(request, project_name):
    project = get_object_or_404(Project, name=project_name)
    credentials = Credential.objects.filter(scope_level='project', project=project)
    return render(request, 'pipeline/local_credential_list.html', {
        'credentials': credentials, 'project': project, 'project_name': project.name,
    })


@login_required
def local_credential_detail(request, pk):
    cred = get_object_or_404(Credential, pk=pk)
    return render(request, 'pipeline/local_credential_detail.html', {'credential': cred})


@login_required
def local_credential_create(request, project_name):
    project = get_object_or_404(Project, name=project_name)
    if request.method == 'POST':
        form = LocalCredentialForm(request.POST)
        if form.is_valid():
            cred = form.save(commit=False)
            cred.project = project
            cred.scope_level = 'project'
            cred.save()
            return redirect('local_credential_list', project_name=project_name)
    else:
        form = LocalCredentialForm()
    return render(request, 'pipeline/local_credential_form.html', {'form': form, 'project': project})


@login_required
def local_credential_update(request, pk):
    cred = get_object_or_404(Credential, pk=pk)
    if request.method == 'POST':
        form = LocalCredentialForm(request.POST, instance=cred)
        if form.is_valid():
            form.save()
            return redirect('local_credential_list', project_name=cred.project.name)  # ← FIXED
    else:
        form = LocalCredentialForm(instance=cred)
    return render(request, 'pipeline/local_credential_form.html', {'form': form})


@login_required
def local_credential_delete(request, pk):
    cred = get_object_or_404(Credential, pk=pk)
    project_name = cred.project.name if cred.project else None   # ← FIXED
    if request.method == 'POST':
        cred.delete()
        if project_name:
            return redirect('local_credential_list', project_name=project_name)
        return redirect('project_list')
    return render(request, 'pipeline/local_credential_confirm_delete.html', {'credential': cred})


# ─────────────────────────────────────────────────────────────────────────────
#  Applications
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def create_application(request, project_name=None):
    if project_name:
        project = get_object_or_404(Project, name=project_name)
    else:
        project = Project.objects.first()
        if not project:
            return redirect('project_create')
    if request.method == 'POST':
        form = ApplicationForm(request.POST)
        if form.is_valid():
            app = form.save(commit=False)
            app.project = project

            repo_mode = form.cleaned_data['repo_mode']
            if repo_mode == 'create':
                # Initialize a real Git repository backing this application
                from gitmgmt.models import Repository, Branch
                from gitmgmt.views import _initialize_repository, _create_default_labels
                visibility = (project.organization.default_repo_visibility
                              if project.organization else 'private')
                try:
                    _initialize_repository(app.name, user=request.user)
                except Exception as e:
                    form.add_error(None, f"Failed to initialize repository: {e}")
                    return render(request, 'pipeline/create_application.html',
                                  {'form': form, 'project': project})
                app.save()
                repo = Repository.objects.create(
                    name=app.name,
                    description=form.cleaned_data.get('description', ''),
                    owner=request.user,
                    organization=project.organization if project else None,
                    visibility=visibility,
                    default_branch=app.default_branch or 'main',
                    application=app,
                )
                Branch.objects.create(repository=repo, name=repo.default_branch, is_default=True)
                _create_default_labels(repo)
            elif repo_mode == 'link':
                app.save()
                repo = form.cleaned_data['existing_repository']
                repo.application = app
                repo.save()
            else:
                app.save()
            return redirect('application_detail', application_name=app.name)
    else:
        form = ApplicationForm()
    return render(request, 'pipeline/create_application.html', {'form': form, 'project': project})


@login_required
def application_list(request):
    project_name = request.GET.get('project')
    project = None
    if project_name:
        project = get_object_or_404(Project, name=project_name)
        applications = Application.objects.filter(project=project).select_related('project')
    else:
        applications = Application.objects.select_related('project').all()
    return render(request, 'pipeline/application_list.html', {
        'applications': applications,
        'project': project,
    })


@login_required
def application_detail(request, application_name):
    app = get_object_or_404(Application, name=application_name)
    pipelines = app.pipelines.all()
    return render(request, 'pipeline/application_detail.html', {'application': app, 'pipelines': pipelines})


@login_required
def application_settings(request, application_name):
    """Application settings — general, linked repository, danger zone."""
    from .forms import ApplicationSettingsForm
    app = get_object_or_404(Application, name=application_name)
    project = app.project

    my_role = project.get_member_role(request.user)
    is_open_project = project.members.count() == 0 and project.organization is None
    if not (request.user.is_superuser or my_role == 'maintainer' or is_open_project):
        messages.error(request, "You need the Maintainer role to manage application settings.")
        return redirect('application_detail', application_name=app.name)

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'delete':
            name = app.name
            app.delete()
            messages.success(request, f"Application '{name}' deleted. Its repository was kept.")
            return redirect('project_detail', project_name=project.name)

        form = ApplicationSettingsForm(request.POST, instance=app)
        if form.is_valid():
            form.save()
            # Re-link the backing repository (link lives on gitmgmt.Repository)
            from gitmgmt.models import Repository
            new_repo = form.cleaned_data.get('repository')
            current = Repository.objects.filter(application=app).first()
            if current and current != new_repo:
                current.application = None
                current.save()
            if new_repo and new_repo != current:
                new_repo.application = app
                new_repo.save()
            messages.success(request, "Application settings updated.")
            return redirect('application_settings', application_name=app.name)
    else:
        form = ApplicationSettingsForm(instance=app)

    return render(request, 'pipeline/application_settings.html', {
        'application': app,
        'project': project,
        'form': form,
        'linked_repo': app.linked_repository,
    })


# ─────────────────────────────────────────────────────────────────────────────
#  YAML pipeline creator
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def create_yaml_pipeline(request):
    """
    BUG FIX: Pipeline.get_or_create used project= which doesn't exist on Pipeline.
    Now correctly uses application= FK.
    """
    if request.method == 'POST':
        yaml_data = request.POST.get('yaml_data', '').strip()
        if not yaml_data:
            return JsonResponse({'error': 'YAML data is empty'}, status=400)
        try:
            parsed = yaml.safe_load(yaml_data)
        except yaml.YAMLError:
            return JsonResponse({'error': 'Invalid YAML format'}, status=400)

        project_name = parsed.get('project_name')
        project = Project.objects.filter(name=project_name).first()
        if not project:
            return JsonResponse({'error': f"Project '{project_name}' not found"}, status=404)

        agent_name = parsed.get('agent')
        if agent_name and not Agent.objects.filter(hostname=agent_name).exists():
            return JsonResponse({'error': f"Agent '{agent_name}' not found"}, status=404)

        pipeline_name = parsed.get('pipeline_name', '').strip()
        if not pipeline_name:
            return JsonResponse({'error': 'pipeline_name is required'}, status=400)

        # Use the first application of the project (create one if none)
        app = project.applications.first()
        if not app:
            app = Application.objects.create(name=project_name, project=project)

        pipeline, created = Pipeline.objects.get_or_create(
            name=pipeline_name,
            defaults={
                'description': parsed.get('description', ''),
                'application': app,
                'yaml_path': parsed.get('yaml_path', 'rockerci.yaml'),
                'monitored_branch': parsed.get('monitored_branch', 'main'),
            }
        )
        if not created:
            pipeline.description = parsed.get('description', pipeline.description)
            pipeline.save()

        for step_data in parsed.get('steps', []):
            name = step_data.get('name', '').strip()
            command = step_data.get('command', '').strip()
            if name and command:
                PipelineStep.objects.update_or_create(
                    pipeline=pipeline, name=name,
                    defaults={
                        'condition': step_data.get('condition', ''),
                        'command': command,
                    }
                )
        return JsonResponse({'success': True, 'pipeline': pipeline.name}, status=201)

    projects = Project.objects.all()
    return render(request, 'pipeline/create_yaml_pipeline.html', {'projects': projects})


# ─────────────────────────────────────────────────────────────────────────────
#  Global pipeline list + settings
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def global_pipeline_list(request):
    pipelines = Pipeline.objects.all().select_related('application__project')
    return render(request, 'pipeline/global_pipeline_list.html', {'pipelines': pipelines})


import socket
import ssl

def check_redis_connection(host='127.0.0.1', port=6379, password='', use_tls=False, timeout=3):
    """
    Test Redis server reachability and RESP protocol PING response.
    Supports both Non-TLS (redis://) and TLS/SSL (rediss://).
    """
    try:
        raw_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        raw_socket.settimeout(timeout)
        
        port_num = int(port) if str(port).isdigit() else 6379

        if use_tls:
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            sock = context.wrap_socket(raw_socket, server_hostname=host)
        else:
            sock = raw_socket

        sock.connect((host, port_num))

        # Send AUTH if password provided
        if password:
            auth_cmd = f"*2\r\n$4\r\nAUTH\r\n${len(password)}\r\n{password}\r\n"
            sock.sendall(auth_cmd.encode('utf-8'))
            auth_resp = sock.recv(1024).decode('utf-8', errors='ignore')
            if not auth_resp.startswith('+OK'):
                sock.close()
                return False, f"Authentication failed: {auth_resp.strip()}"

        # Send PING command
        sock.sendall(b"*1\r\n$4\r\nPING\r\n")
        ping_resp = sock.recv(1024).decode('utf-8', errors='ignore')
        sock.close()

        if ping_resp.startswith('+PONG') or 'PONG' in ping_resp:
            scheme = "rediss" if use_tls else "redis"
            return True, f"Successfully connected to Redis server at {scheme}://{host}:{port_num} (Response: PONG)"
        else:
            return False, f"Unexpected response from server: {ping_resp.strip()}"

    except socket.timeout:
        return False, f"Connection timed out while connecting to {host}:{port}"
    except ConnectionRefusedError:
        return False, f"Connection refused at {host}:{port}. Ensure Redis service is running."
    except Exception as e:
        return False, f"Connection failed: {str(e)}"


@login_required
def global_settings(request):
    settings_list = GlobalSettings.objects.all()
    settings_dict = {s.key: s.value for s in settings_list}
    show_email_modal = False
    if request.method == 'POST':
        form = GlobalSettingsForm(request.POST)
        if form.is_valid():
            key = form.cleaned_data['key']
            value = form.cleaned_data['value']
            GlobalSettings.objects.update_or_create(key=key, defaults={'value': value})
            return redirect('global_settings')
    else:
        form = GlobalSettingsForm()

    # Build integration map
    integrations = {
        obj.integration_type: obj
        for obj in NotificationIntegration.objects.all()
    }

    # Scaling & Infrastructure config
    task_engine = settings_dict.get('BACKGROUND_TASK_ENGINE', 'internal')
    redis_host = settings_dict.get('REDIS_HOST', '127.0.0.1')
    redis_port = settings_dict.get('REDIS_PORT', '6379')
    redis_password = settings_dict.get('REDIS_PASSWORD', '')
    redis_use_tls = settings_dict.get('REDIS_USE_TLS', 'false').lower() == 'true'
    redis_db_index = settings_dict.get('REDIS_DB_INDEX', '0')

    # Test redis connection status
    redis_ok, redis_status = check_redis_connection(
        host=redis_host,
        port=redis_port,
        password=redis_password,
        use_tls=redis_use_tls
    )

    secret_engine = settings_dict.get('SECRET_STORAGE_ENGINE', 'builtin')
    vault_url = settings_dict.get('SECRET_STORAGE_VAULT_URL', '')
    vault_token = settings_dict.get('SECRET_STORAGE_VAULT_TOKEN', '')

    repo_storage_path = settings_dict.get('REPO_STORAGE_PATH', '')

    keycloak_enabled = settings_dict.get('KEYCLOAK_ENABLED', 'false').lower() == 'true'
    keycloak_server_url = settings_dict.get('KEYCLOAK_SERVER_URL', '')
    keycloak_realm = settings_dict.get('KEYCLOAK_REALM', '')
    keycloak_client_id = settings_dict.get('KEYCLOAK_CLIENT_ID', '')
    keycloak_client_secret = settings_dict.get('KEYCLOAK_CLIENT_SECRET', '')

    return render(request, 'pipeline/global_settings.html', {
        'settings': settings_list,
        'form': form,
        'integrations': integrations,
        'show_email_modal': show_email_modal,

        # Task Engine & Scaling
        'task_engine': task_engine,
        'redis_host': redis_host,
        'redis_port': redis_port,
        'redis_password': redis_password,
        'redis_use_tls': redis_use_tls,
        'redis_db_index': redis_db_index,
        'redis_ok': redis_ok,
        'redis_status': redis_status,

        # Secrets Storage Engine
        'secret_engine': secret_engine,
        'vault_url': vault_url,
        'vault_token': vault_token,

        # Git Storage
        'repo_storage_path': repo_storage_path,

        # Keycloak SSO
        'keycloak_enabled': keycloak_enabled,
        'keycloak_server_url': keycloak_server_url,
        'keycloak_realm': keycloak_realm,
        'keycloak_client_id': keycloak_client_id,
        'keycloak_client_secret': keycloak_client_secret,
    })


@login_required
def save_repo_storage_settings(request):
    """Save custom Git repository storage path in GlobalSettings."""
    if request.method == 'POST':
        repo_storage_path = request.POST.get('repo_storage_path', '').strip()
        if repo_storage_path:
            import os
            try:
                os.makedirs(repo_storage_path, exist_ok=True)
                test_file = os.path.join(repo_storage_path, '.perm_test')
                with open(test_file, 'w') as f:
                    f.write('ok')
                if os.path.exists(test_file):
                    os.remove(test_file)
                GlobalSettings.objects.update_or_create(key='REPO_STORAGE_PATH', defaults={'value': repo_storage_path})
                messages.success(request, f"Git repository storage path updated to: {repo_storage_path}")
            except Exception as e:
                messages.error(request, f"Failed to verify repository storage directory '{repo_storage_path}': {e}")
        else:
            GlobalSettings.objects.filter(key='REPO_STORAGE_PATH').delete()
            messages.success(request, "Reset Git repository storage path to default internal storage.")
    return redirect('global_settings')


@login_required
def save_keycloak_settings(request):
    """Save Keycloak Enterprise SSO configuration."""
    if request.method == 'POST':
        kc_url = request.POST.get('keycloak_server_url', '').strip().rstrip('/')
        kc_realm = request.POST.get('keycloak_realm', '').strip()
        kc_client_id = request.POST.get('keycloak_client_id', '').strip()
        kc_client_secret = request.POST.get('keycloak_client_secret', '').strip()
        kc_enabled = 'true' if request.POST.get('keycloak_enabled') == 'true' else 'false'

        GlobalSettings.objects.update_or_create(key='KEYCLOAK_SERVER_URL', defaults={'value': kc_url})
        GlobalSettings.objects.update_or_create(key='KEYCLOAK_REALM', defaults={'value': kc_realm})
        GlobalSettings.objects.update_or_create(key='KEYCLOAK_CLIENT_ID', defaults={'value': kc_client_id})
        if kc_client_secret:
            GlobalSettings.objects.update_or_create(key='KEYCLOAK_CLIENT_SECRET', defaults={'value': kc_client_secret})
        GlobalSettings.objects.update_or_create(key='KEYCLOAK_ENABLED', defaults={'value': kc_enabled})

        if kc_enabled == 'true':
            messages.success(request, "Keycloak Enterprise SSO enabled and configured.")
        else:
            messages.success(request, "Keycloak SSO configuration saved (Disabled).")
    return redirect('global_settings')


@login_required
def test_keycloak_connection_api(request):
    """AJAX endpoint to test Keycloak realm OIDC openid-configuration discovery endpoint."""
    if request.method == 'POST':
        kc_url = request.POST.get('keycloak_server_url', '').strip().rstrip('/')
        kc_realm = request.POST.get('keycloak_realm', '').strip()
        if not kc_url or not kc_realm:
            return JsonResponse({'ok': False, 'message': 'Please enter Keycloak Server URL and Realm Name.'})

        discovery_url = f"{kc_url}/realms/{kc_realm}/.well-known/openid-configuration"
        try:
            import requests
            resp = requests.get(discovery_url, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                issuer = data.get('issuer', '')
                return JsonResponse({'ok': True, 'message': f"Keycloak Realm OK! Discovered Issuer: {issuer}"})
            else:
                return JsonResponse({'ok': False, 'message': f"Keycloak endpoint returned status {resp.status_code}."})
        except Exception as e:
            return JsonResponse({'ok': False, 'message': f"Connection to Keycloak failed: {e}"})
    return JsonResponse({'ok': False, 'message': 'Invalid request.'})


def keycloak_login(request):
    """Initiate Keycloak OIDC authorization flow (Workloop pattern)."""
    settings_dict = {s.key: s.value for s in GlobalSettings.objects.all()}
    kc_enabled = settings_dict.get('KEYCLOAK_ENABLED', 'false').lower() == 'true'
    kc_url = settings_dict.get('KEYCLOAK_SERVER_URL', '').rstrip('/')
    kc_realm = settings_dict.get('KEYCLOAK_REALM', '')
    kc_client_id = settings_dict.get('KEYCLOAK_CLIENT_ID', '')

    if not (kc_enabled and kc_url and kc_realm and kc_client_id):
        messages.error(request, "Keycloak SSO is not enabled or configured by admin.")
        return redirect('login')

    from urllib.parse import urlencode
    redirect_uri = request.build_absolute_uri('/ci/auth/keycloak/callback/')
    auth_url = f"{kc_url}/realms/{kc_realm}/protocol/openid-connect/auth?" + urlencode({
        'client_id': kc_client_id,
        'response_type': 'code',
        'scope': 'openid profile email',
        'redirect_uri': redirect_uri,
    })
    return redirect(auth_url)


def keycloak_callback(request):
    """Keycloak OIDC callback endpoint — exchanges auth code for token & provisions basic user."""
    code = request.GET.get('code')
    if not code:
        messages.error(request, "Keycloak authentication failed: missing authorization code.")
        return redirect('login')

    settings_dict = {s.key: s.value for s in GlobalSettings.objects.all()}
    kc_url = settings_dict.get('KEYCLOAK_SERVER_URL', '').rstrip('/')
    kc_realm = settings_dict.get('KEYCLOAK_REALM', '')
    kc_client_id = settings_dict.get('KEYCLOAK_CLIENT_ID', '')
    kc_client_secret = settings_dict.get('KEYCLOAK_CLIENT_SECRET', '')

    redirect_uri = request.build_absolute_uri('/ci/auth/keycloak/callback/')
    token_url = f"{kc_url}/realms/{kc_realm}/protocol/openid-connect/token"
    userinfo_url = f"{kc_url}/realms/{kc_realm}/protocol/openid-connect/userinfo"

    import requests
    from django.contrib.auth import login as auth_login
    from django.contrib.auth.models import User

    try:
        token_data = {
            'grant_type': 'authorization_code',
            'client_id': kc_client_id,
            'code': code,
            'redirect_uri': redirect_uri,
        }
        if kc_client_secret:
            token_data['client_secret'] = kc_client_secret

        logger.info(f"Exchanging Keycloak code for client '{kc_client_id}' at {token_url}")
        token_resp = requests.post(token_url, data=token_data, timeout=8)
        if token_resp.status_code != 200:
            logger.error(f"Keycloak token exchange error {token_resp.status_code}: {token_resp.text}")
            messages.error(request, f"Keycloak SSO Token Error: {token_resp.text}")
            return redirect('login')

        tokens = token_resp.json()
        access_token = tokens.get('access_token')

        userinfo_resp = requests.get(userinfo_url, headers={'Authorization': f"Bearer {access_token}"}, timeout=8)
        userinfo_resp.raise_for_status()
        claims = userinfo_resp.json()

        # Extract Azure AD / Keycloak claims
        email = claims.get('email') or claims.get('upn') or claims.get('unique_name') or ''
        raw_user = claims.get('preferred_username') or claims.get('upn') or email or 'azure_user'
        
        # Clean username for Django compatibility
        import re
        username = re.sub(r'[^a-zA-Z0-9_@.-]', '_', raw_user)
        first_name = claims.get('given_name') or claims.get('name', '').split(' ')[0] or ''
        last_name = claims.get('family_name') or (claims.get('name', '').split(' ')[1] if ' ' in claims.get('name', '') else '')

        # Match existing user by username or email
        user = User.objects.filter(username=username).first()
        if not user and email:
            user = User.objects.filter(email=email).first()

        if not user:
            user = User.objects.create(
                username=username,
                email=email,
                first_name=first_name,
                last_name=last_name,
            )
        else:
            if email and not user.email:
                user.email = email
            if first_name and not user.first_name:
                user.first_name = first_name
            if last_name and not user.last_name:
                user.last_name = last_name
            user.save()

        # Log the user into Django session with explicit auth backend
        auth_login(request, user, backend='django.contrib.auth.backends.ModelBackend')
        messages.success(request, f"Welcome, {user.first_name or user.username}! Signed in via Keycloak (Azure AD SSO).")
        return redirect('dashboard')

    except Exception as e:
        logger.exception("Keycloak SSO callback exception occurred")
        messages.error(request, f"Keycloak SSO callback error: {e}")
        return redirect('login')


@login_required
def save_task_scaling_settings(request):
    """Save Background Task Scaling engine (Internal Django vs External Redis/Celery)."""
    if request.method == 'POST':
        task_engine = request.POST.get('task_engine', 'internal').strip()
        redis_host = request.POST.get('redis_host', '127.0.0.1').strip()
        redis_port = request.POST.get('redis_port', '6379').strip()
        redis_password = request.POST.get('redis_password', '').strip()
        redis_use_tls = 'true' if request.POST.get('redis_use_tls') == 'true' else 'false'
        redis_db_index = request.POST.get('redis_db_index', '0').strip()

        GlobalSettings.objects.update_or_create(key='BACKGROUND_TASK_ENGINE', defaults={'value': task_engine})
        GlobalSettings.objects.update_or_create(key='REDIS_HOST', defaults={'value': redis_host})
        GlobalSettings.objects.update_or_create(key='REDIS_PORT', defaults={'value': redis_port})
        GlobalSettings.objects.update_or_create(key='REDIS_PASSWORD', defaults={'value': redis_password})
        GlobalSettings.objects.update_or_create(key='REDIS_USE_TLS', defaults={'value': redis_use_tls})
        GlobalSettings.objects.update_or_create(key='REDIS_DB_INDEX', defaults={'value': redis_db_index})

        if task_engine == 'external':
            ok, msg = check_redis_connection(redis_host, redis_port, redis_password, redis_use_tls == 'true')
            if ok:
                messages.success(request, f'Task scaling engine set to External Redis. {msg}')
            else:
                messages.warning(request, f'Task scaling set to External Redis, but auto-detection warning: {msg}')
        else:
            messages.success(request, 'Task scaling engine set to Internal (Django Built-in DB & Thread Worker).')

    return redirect('global_settings')


@login_required
def test_redis_connection_api(request):
    """AJAX endpoint to test Redis connection for TLS (rediss://) or Non-TLS (redis://)."""
    if request.method == 'POST':
        host = request.POST.get('redis_host', '127.0.0.1').strip()
        port = request.POST.get('redis_port', '6379').strip()
        password = request.POST.get('redis_password', '').strip()
        use_tls = request.POST.get('redis_use_tls') in ('true', '1', 'True')

        ok, msg = check_redis_connection(host, port, password, use_tls)
        return JsonResponse({'ok': ok, 'message': msg})

    return JsonResponse({'ok': False, 'message': 'Invalid request method.'})


@login_required
def save_secret_storage_settings(request):
    """Save Secret Storage & KMS configuration."""
    if request.method == 'POST':
        secret_engine = request.POST.get('secret_engine', 'builtin').strip()
        vault_url = request.POST.get('vault_url', '').strip()
        vault_token = request.POST.get('vault_token', '').strip()

        GlobalSettings.objects.update_or_create(key='SECRET_STORAGE_ENGINE', defaults={'value': secret_engine})
        GlobalSettings.objects.update_or_create(key='SECRET_STORAGE_VAULT_URL', defaults={'value': vault_url})
        if vault_token:
            GlobalSettings.objects.update_or_create(key='SECRET_STORAGE_VAULT_TOKEN', defaults={'value': vault_token})

        if secret_engine == 'vault':
            messages.success(request, 'Secret Storage set to External KMS / HashiCorp Vault.')
        else:
            messages.success(request, 'Secret Storage set to Built-in (Standard Django Secret Key Encryption).')

    return redirect('global_settings')


@login_required
def save_email_integration(request):
    """Save SMTP config into NotificationIntegration for email."""
    if request.method != 'POST':
        return redirect('global_settings')

    existing = NotificationIntegration.objects.filter(integration_type='email').first()
    smtp_host     = request.POST.get('smtp_host', '').strip()
    smtp_port     = request.POST.get('smtp_port', '587').strip()
    smtp_user     = request.POST.get('smtp_user', '').strip()
    smtp_password = request.POST.get('smtp_password', '').strip()
    smtp_from     = request.POST.get('smtp_from', '').strip()
    use_tls       = bool(request.POST.get('use_tls'))

    config = {
        'smtp_host': smtp_host,
        'smtp_port': int(smtp_port) if smtp_port.isdigit() else 587,
        'smtp_user': smtp_user,
        'smtp_from': smtp_from or f'CogFocus One <noreply@{smtp_host}>',
        'use_tls': use_tls,
    }
    # Only update password if a new one was provided
    if smtp_password:
        config['smtp_password'] = smtp_password
    elif existing and existing.config.get('smtp_password'):
        config['smtp_password'] = existing.config['smtp_password']

    NotificationIntegration.objects.update_or_create(
        integration_type='email',
        defaults={
            'name': 'Email (SMTP)',
            'config': config,
            'is_active': bool(smtp_host),
        }
    )
    messages.success(request, 'Email integration saved and activated.' if smtp_host else 'Email integration saved (inactive — no host).')
    return redirect('global_settings')


@login_required
def test_email_integration(request):
    """
    GET  → Send test email to request.user.email (or ?to= email parameter).
    POST → AJAX test of connection + optional test email send to specified recipient.
    """
    import os
    from django.conf import settings
    from .notifications import test_smtp_connection, _send_smtp, _get_email_integration_config
    integration = NotificationIntegration.objects.filter(integration_type='email').first()

    if request.method == 'POST':
        config = integration.config.copy() if (integration and integration.config) else {}

        for field in ('smtp_host', 'smtp_port', 'smtp_user', 'smtp_password', 'smtp_from', 'use_tls'):
            val = request.POST.get(field)
            if val is not None and val != '':
                config[field] = int(val) if field == 'smtp_port' else (val in ('1', 'true', 'True') if field == 'use_tls' else val)

        if not config.get('smtp_host'):
            config['smtp_host'] = getattr(settings, 'EMAIL_HOST', os.environ.get('EMAIL_HOST', ''))
        if not config.get('smtp_port'):
            config['smtp_port'] = int(getattr(settings, 'EMAIL_PORT', os.environ.get('EMAIL_PORT', 587)))
        if not config.get('smtp_user'):
            config['smtp_user'] = getattr(settings, 'EMAIL_HOST_USER', os.environ.get('EMAIL_HOST_USER', ''))
        if not config.get('smtp_password'):
            config['smtp_password'] = getattr(settings, 'EMAIL_HOST_PASSWORD', os.environ.get('EMAIL_HOST_PASSWORD', ''))

        if not config.get('smtp_host'):
            return JsonResponse({'ok': False, 'message': 'Please enter an SMTP Host before testing the connection.'})

        # Test SMTP connection & auth first
        ok, msg = test_smtp_connection(config)
        if not ok:
            return JsonResponse({'ok': False, 'message': msg})

        # If a specific test recipient is provided, also send a test email!
        test_recipient = request.POST.get('test_recipient', '').strip() or request.user.email
        if test_recipient and '@' in test_recipient:
            try:
                _send_smtp(
                    config,
                    recipients=[test_recipient],
                    subject='Test notification from CogFocus One',
                    body='This is a test email to confirm your SMTP settings are working properly.'
                )
                return JsonResponse({'ok': True, 'message': f'Connection successful! Test email sent to {test_recipient}.'})
            except Exception as exc:
                return JsonResponse({'ok': False, 'message': f'Connection OK, but failed to send email: {exc}'})

        return JsonResponse({'ok': True, 'message': 'SMTP Connection successful!'})

    # GET → Send test email
    config = _get_email_integration_config()
    if not config or not config.get('smtp_host'):
        messages.error(request, 'Email integration is not configured or active.')
        return redirect('global_settings')

    recipient = request.GET.get('to', '').strip() or request.user.email

    if not recipient:
        messages.error(
            request, 
            f'Your user account ({request.user.username}) has no email address set on your profile. Please add your email at /profile/ or specify a recipient email.'
        )
        return redirect('global_settings')

    try:
        _send_smtp(
            config,
            recipients=[recipient],
            subject='Test notification from CogFocus One',
            body='This is a test email to confirm your SMTP configuration is working correctly.'
        )
        messages.success(request, f'Test email successfully sent to {recipient}.')
    except Exception as exc:
        messages.error(request, f'Failed to send test email: {exc}')

    return redirect('global_settings')


@login_required
def notification_preferences(request):
    """Per-user notification preference toggles."""
    prefs = UserNotificationPreference.for_user(request.user)
    if request.method == 'POST':
        prefs.pipeline_success = bool(request.POST.get('pipeline_success'))
        prefs.pipeline_failure = bool(request.POST.get('pipeline_failure'))
        prefs.pr_assigned      = bool(request.POST.get('pr_assigned'))
        prefs.pr_merged        = bool(request.POST.get('pr_merged'))
        prefs.issue_assigned   = bool(request.POST.get('issue_assigned'))
        prefs.issue_commented  = bool(request.POST.get('issue_commented'))
        prefs.save()
        messages.success(request, 'Notification preferences saved.')
        return redirect('notification_preferences')
    return render(request, 'pipeline/notification_preferences.html', {'prefs': prefs})


def documentation(request):
    """Official in-app documentation page."""
    return render(request, 'pipeline/documentation.html')


# ─────────────────────────────────────────────────────────────────────────────
#  File download from project workspace
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def project_file_download(request, project_name, path):
    project = get_object_or_404(Project, name=project_name)
    base = os.path.abspath(os.path.join('D:/cicd/', project.name))
    file_path = os.path.abspath(os.path.join(base, path))
    if not file_path.startswith(base):
        raise Http404
    if not os.path.exists(file_path):
        raise Http404
    with open(file_path, 'rb') as fh:
        response = HttpResponse(fh.read(), content_type='application/octet-stream')
        response['Content-Disposition'] = f'attachment; filename={os.path.basename(file_path)}'
        return response


# ─────────────────────────────────────────────────────────────────────────────
#  Pipeline metrics API  (for charts)
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def pipeline_metrics_api(request):
    """Returns JSON metrics for all pipelines — used by the dashboard chart."""
    days = int(request.GET.get('days', 7))
    start = timezone.now() - timedelta(days=days)
    data = (
        PipelineRun.objects
        .filter(started_at__gte=start)
        .values('status')
        .annotate(count=Count('id'))
    )
    return JsonResponse({'metrics': list(data)})


# ─────────────────────────────────────────────────────────────────────────────
#  Build Artifacts
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def artifact_download(request, run_id, artifact_id):
    run      = get_object_or_404(PipelineRun, run_id=run_id)
    artifact = get_object_or_404(BuildArtifact, pk=artifact_id, pipeline_run=run)
    artifacts_dir = os.environ.get('CI_ARTIFACTS_DIR', 'D:/cicd/artifacts')
    full_path = os.path.join(artifacts_dir, artifact.file_path)
    full_path = os.path.abspath(full_path)
    if not full_path.startswith(os.path.abspath(artifacts_dir)):
        raise Http404
    if not os.path.exists(full_path):
        messages.error(request, 'Artifact file not found on disk.')
        return redirect('pipeline_run_detail', run_id=run_id)
    response = HttpResponse(open(full_path, 'rb').read(),
                            content_type=artifact.content_type)
    response['Content-Disposition'] = f'attachment; filename="{artifact.name}"'
    return response


# ─────────────────────────────────────────────────────────────────────────────
#  Deployment Targets
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def deployment_target_list(request):
    targets = DeploymentTarget.objects.select_related('environment', 'project', 'credential').all()
    return render(request, 'pipeline/deployment_target_list.html', {'targets': targets})


@login_required
def deployment_target_detail(request, pk):
    target = get_object_or_404(DeploymentTarget, pk=pk)
    return render(request, 'pipeline/deployment_target_detail.html', {'target': target})


@login_required
def deployment_target_create(request):
    if request.method == 'POST':
        form = DeploymentTargetForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Deployment target created.')
            return redirect('deployment_target_list')
    else:
        form = DeploymentTargetForm()
    return render(request, 'pipeline/deployment_target_form.html', {'form': form, 'action': 'Create'})


@login_required
def deployment_target_update(request, pk):
    target = get_object_or_404(DeploymentTarget, pk=pk)
    if request.method == 'POST':
        form = DeploymentTargetForm(request.POST, instance=target)
        if form.is_valid():
            form.save()
            messages.success(request, 'Deployment target updated.')
            return redirect('deployment_target_detail', pk=target.pk)
    else:
        form = DeploymentTargetForm(instance=target)
    return render(request, 'pipeline/deployment_target_form.html', {'form': form, 'target': target, 'action': 'Edit'})


@login_required
def deployment_target_delete(request, pk):
    target = get_object_or_404(DeploymentTarget, pk=pk)
    if request.method == 'POST':
        target.delete()
        messages.success(request, 'Deployment target deleted.')
        return redirect('deployment_target_list')
    return render(request, 'pipeline/deployment_target_confirm_delete.html', {'target': target})
