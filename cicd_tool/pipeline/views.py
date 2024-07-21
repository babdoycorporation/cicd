from audioop import reverse
import os
import subprocess
import git
from django.shortcuts import render, get_object_or_404, redirect
from django.http import Http404, HttpResponseNotFound, HttpResponse
import requests
from .models import Project, Build
from .forms import ProjectForm, ProjectConfigurationForm

BASE_REPO_DIR = 'D:/cicd/'  # Set this to your repository base directory

# views.py

from django.shortcuts import render
from django.views import View
from .models import Project, Application, Pipeline, PipelineRun, Agent
from gitmgmt.models import Repository

class DashboardView(View):
    def get(self, request):
        total_projects = Project.objects.count()
        total_applications = Application.objects.count()
        total_pipelines = Pipeline.objects.count()
        total_pipeline_runs = PipelineRun.objects.count()
        total_agents = Agent.objects.count()
        successful_runs = PipelineRun.objects.filter(status='success').count()
        failed_runs = PipelineRun.objects.filter(status='failed').count()
        total_repos = Repository.objects.count()

        # Fetch latest pipeline runs with related pipeline information
        latest_pipeline_runs = PipelineRun.objects.select_related('pipeline').order_by('-started_at')[:5]

        context = {
            'total_projects': total_projects,
            'total_applications': total_applications,
            'total_pipelines': total_pipelines,
            'total_pipeline_runs': total_pipeline_runs,
            'total_agents': total_agents,
            'successful_runs': successful_runs,
            'failed_runs': failed_runs,
            'latest_pipeline_runs': latest_pipeline_runs,
            'total_repos': total_repos
        }

        return render(request, 'pipeline/dashboard.html', context)



def project_list(request):
    projects = Project.objects.all()
    return render(request, 'pipeline/project_list.html', {'projects': projects})

def project_detail(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    builds = Build.objects.filter(project=project)
    return render(request, 'pipeline/project_detail.html', {'project': project, 'builds': builds})

def project_create(request):
    if request.method == 'POST':
        form = ProjectForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('project_list')
    else:
        form = ProjectForm()
    return render(request, 'pipeline/project_form.html', {'form': form})

from django.shortcuts import render, get_object_or_404, redirect
from .models import Project, Build
from django.core.management import call_command

def trigger_build(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    build = Build.objects.create(project=project, status='pending', log='Build started...')
    
    # Run the build command
    call_command('run_build')

    return redirect('project_detail', project_id=project.id)


def configure_project(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    if request.method == 'POST':
        form = ProjectConfigurationForm(request.POST, instance=project)
        if form.is_valid():
            form.save()
            return redirect('project_detail', project_id=project_id)
    else:
        form = ProjectConfigurationForm(instance=project)
    return render(request, 'pipeline/configure_project.html', {'form': form, 'project': project})

from django.views.decorators.csrf import csrf_exempt
from django.http import HttpResponseNotFound, JsonResponse
import json

@csrf_exempt
def github_webhook(request):
    if request.method == 'POST':
        payload = json.loads(request.body.decode('utf-8'))
        # Trigger a build
        project_name = payload['repository']['name']
        project = Project.objects.get(name=project_name)
        Build.objects.create(project=project, status='pending')
        return JsonResponse({'status': 'success'})
    return JsonResponse({'status': 'failed'}, status=400)

def project_file_download(request, project_id, path):
    project = get_object_or_404(Project, pk=project_id)
    file_path = os.path.join('D:/cicd/', project.name, path)
    if os.path.exists(file_path):
        with open(file_path, 'rb') as f:
            response = HttpResponse(f.read(), content_type="application/octet-stream")
            response['Content-Disposition'] = f'attachment; filename={os.path.basename(file_path)}'
            return response
    raise Http404

def project_edit(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    if request.method == 'POST':
        form = ProjectForm(request.POST, instance=project)
        if form.is_valid():
            form.save()
            return redirect('project_list')
    else:
        form = ProjectForm(instance=project)
    return render(request, 'pipeline/project_form.html', {'form': form})

def project_delete(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    if request.method == 'POST':
        project.delete()
        return redirect('project_list')
    return render(request, 'pipeline/project_confirm_delete.html', {'project': project})

def download_log(request, build_id):
    build = get_object_or_404(Build, pk=build_id)
    response = HttpResponse(build.log, content_type='text/plain')
    response['Content-Disposition'] = f'attachment; filename=build_{build_id}_log.txt'
    return response

import json
from datetime import timedelta
from django.db.models import Count
from django.db.models.functions import TruncDate
from django.shortcuts import render
from django.utils import timezone
from .models import Build

# views.py
from django.shortcuts import get_object_or_404
from .models import Project, Build

from django.shortcuts import render, get_object_or_404
from django.utils import timezone
from django.db.models import Count
from django.db.models.functions import TruncDate
from datetime import timedelta
import json
from .models import Project, PipelineRun

def build_history(request, project_id):
    # Retrieve the project associated with the project_id
    project = get_object_or_404(Project, pk=project_id)

    # Calculate the date range for the past week with timezone-aware datetimes
    end_date = timezone.now()
    start_date = end_date - timedelta(days=7)
    
    # Query the database to count successful and failed PipelineRuns per day for the specific project
    build_history_data = PipelineRun.objects.filter(pipeline__project=project, started_at__gte=start_date, started_at__lte=end_date) \
                                            .annotate(date=TruncDate('started_at')) \
                                            .values('date', 'status') \
                                            .annotate(count=Count('id')) \
                                            .order_by('date', 'status')

    # Organize the data into a format suitable for rendering in the template
    dates = []
    successful_builds = []
    failed_builds = []
    
    # Initialize counters for each day within the date range
    date_range = [(start_date + timedelta(days=i)).date() for i in range(8)]
    build_stats = {date: {'success': 0, 'failed': 0} for date in date_range}

    for entry in build_history_data:
        date = entry['date']
        if entry['status'] == 'success':
            build_stats[date]['success'] = entry['count']
        elif entry['status'] == 'failed':
            build_stats[date]['failed'] = entry['count']
    
    for date in date_range:
        dates.append(date.isoformat())
        successful_builds.append(build_stats[date]['success'])
        failed_builds.append(build_stats[date]['failed'])

    build_history_data = {
        'dates': dates,
        'successful_builds': successful_builds,
        'failed_builds': failed_builds
    }

    return render(request, 'pipeline/build_history.html', {'build_history_data': json.dumps(build_history_data), 'project': project})

# views.py

from django.shortcuts import render, get_object_or_404, redirect
from .models import Project, Pipeline

def pipeline_list(request, project_id):
    project = get_object_or_404(Project, id=project_id)
    pipelines = Pipeline.objects.filter(project=project)
    return render(request, 'pipeline/pipeline_list.html', {'project': project, 'pipelines': pipelines})

from django.shortcuts import render, get_object_or_404, redirect
from .models import Project, Pipeline, Application

def pipeline_create(request, project_id, pipeline_id=None):
    project = get_object_or_404(Project, id=project_id)
    applications = project.applications.all()
    pipeline = None
    pipeline_application_ids = []

    if pipeline_id:
        pipeline = get_object_or_404(Pipeline, id=pipeline_id, project=project)
        pipeline_application_ids = list(pipeline.applications.values_list('id', flat=True))
    
    if request.method == 'POST':
        name = request.POST.get('name')
        description = request.POST.get('description', '')
        application_id = request.POST.get('application')
        application = get_object_or_404(Application, id=application_id)
        
        if pipeline:
            pipeline.name = name
            pipeline.description = description
            pipeline.save()
        else:
            pipeline = Pipeline.objects.create(project=project, name=name, description=description)
        
        application.pipelines.add(pipeline)
        application.save()

        return redirect('pipeline_list', project_id=project.id)
    
    return render(request, 'pipeline/pipeline_form.html', {
        'project': project,
        'applications': applications,
        'pipeline': pipeline,
        'pipeline_application_ids': pipeline_application_ids
    })

def pipeline_update(request, project_id, pipeline_id):
    project = get_object_or_404(Project, id=project_id)
    pipeline = get_object_or_404(Pipeline, id=pipeline_id)
    if request.method == 'POST':
        pipeline.name = request.POST.get('name')
        pipeline.description = request.POST.get('description', '')
        pipeline.save()
        return redirect('pipeline_list', project_id=project.id)
    return render(request, 'pipeline/pipeline_form.html', {'project': project, 'pipeline': pipeline})

def pipeline_delete(request, project_id, pipeline_id):
    project = get_object_or_404(Project, id=project_id)
    pipeline = get_object_or_404(Pipeline, id=pipeline_id)
    if request.method == 'POST':
        pipeline.delete()
        return redirect('pipeline_list', project_id=project.id)
    return render(request, 'pipeline/pipeline_confirm_delete.html', {'project': project, 'pipeline': pipeline})
# views.py

# views.py

from .models import Project, Pipeline, PipelineStep

def pipeline_step_list(request, pipeline_id):
    pipeline = get_object_or_404(Pipeline, id=pipeline_id)
    steps = PipelineStep.objects.filter(pipeline=pipeline)
    return render(request, 'pipeline/pipeline_step_list.html', {'pipeline': pipeline, 'steps': steps})

from django.shortcuts import redirect, render, get_object_or_404
from .models import Pipeline, PipelineStep

def pipeline_step_create(request, pipeline_id):
    pipeline = get_object_or_404(Pipeline, id=pipeline_id)
    
    if request.method == 'POST':
        name = request.POST.get('name')
        description = request.POST.get('description', '')
        condition = request.POST.get('condition', '')
        command = request.POST.get('command', '')

        # Check if any of the required fields are empty
        if not name or not command:
            error_message = "Name and command fields are required."
            return render(request, 'pipeline/pipeline_step_form.html', {'pipeline': pipeline, 'error_message': error_message})
        
        try:
            PipelineStep.objects.create(pipeline=pipeline, name=name, description=description, condition=condition, command=command)
            return redirect('pipeline_step_list', pipeline_id=pipeline.id)
        except Exception as e:
            error_message = f"An error occurred while creating the pipeline step: {str(e)}"
            return render(request, 'pipeline/pipeline_step_form.html', {'pipeline': pipeline, 'error_message': error_message})

    return render(request, 'pipeline/pipeline_step_form.html', {'pipeline': pipeline})

def pipeline_step_update(request, pipeline_id, step_id):
    pipeline = get_object_or_404(Pipeline, id=pipeline_id)
    step = get_object_or_404(PipelineStep, id=step_id)
    if request.method == 'POST':
        step.name = request.POST.get('name')
        step.description = request.POST.get('description', '')
        step.condition = request.POST.get('condition', '')
        step.command = request.POST.get('command', '')
        step.save()
        return redirect('pipeline_step_list', pipeline_id=pipeline.id)
    return render(request, 'pipeline/pipeline_step_form.html', {'pipeline': pipeline, 'step': step})

def pipeline_step_delete(request, pipeline_id, step_id):
    pipeline = get_object_or_404(Pipeline, id=pipeline_id)
    step = get_object_or_404(PipelineStep, id=step_id)
    if request.method == 'POST':
        step.delete()
        return redirect('pipeline_step_list', pipeline_id=pipeline.id)
    return render(request, 'pipeline/pipeline_step_confirm_delete.html', {'pipeline': pipeline, 'step': step})

from django.shortcuts import render, redirect
from .models import Pipeline

from django.core.management import call_command
from django.shortcuts import redirect, get_object_or_404, render
from .models import Pipeline, PipelineStep

# pipeline/views.py

from django.shortcuts import get_object_or_404, render
from .models import Pipeline, PipelineStep, PipelineRun

def pipeline_detail(request, pipeline_id):
    pipeline = get_object_or_404(Pipeline, id=pipeline_id)
    context = {
        'pipeline': pipeline,
    }
    return render(request, 'pipeline/pipeline_detail.html', context)


import logging
from django.shortcuts import get_object_or_404
from django.http import StreamingHttpResponse
from django.urls import reverse
from .models import Pipeline, PipelineRun, Agent
from .utils import execute_step, get_available_agent, prepare_credentials
import json
from django.utils import timezone

logger = logging.getLogger(__name__)

def run_pipeline(request, pipeline_id):
    pipeline = get_object_or_404(Pipeline, id=pipeline_id)
    project = pipeline.project

    logger.info(f"Starting pipeline run for pipeline {pipeline_id}")

    try:
        agent = get_available_agent()
    except ValueError as e:
        logger.error(f"No available agent: {str(e)}")
        return StreamingHttpResponse(f"data: {json.dumps({'error': str(e)})}\n\n", content_type='text/event-stream')

    agent.live = False  # Mark agent as busy
    agent.save()

    steps = pipeline.pipelinestep_set.all().order_by('id')
    logger.info(f"Retrieved {steps.count()} steps for pipeline {pipeline_id}")

    overall_status = 'success'  # Assume success initially

    pipeline_run = PipelineRun.objects.create(pipeline=pipeline, agent=agent, status='running')
    logger.info(f"Created pipeline run with ID {pipeline_run.id}")

    credentials = prepare_credentials(project)

    def event_stream():
        nonlocal overall_status
        logger.debug("Starting event stream")
        yield f"data: {json.dumps({'event': 'start', 'pipeline_id': pipeline.id, 'run_id': str(pipeline_run.run_id)})}\n\n"
        
        for step in steps:
            logger.debug(f"Starting step: {step.name}")
            yield f"data: {json.dumps({'event': 'step_start', 'step': step.name})}\n\n"
            try:
                result = execute_step(step, pipeline_run.run_id, credentials)
                logger.debug(f"Step {step.name} completed with exit code: {result.returncode}")
                for line in result.stdout.splitlines():
                    logger.debug(f"Step {step.name} output: {line}")
                    yield f"data: {json.dumps({'event': 'log', 'step': step.name, 'message': line})}\n\n"
                
                status = 'success' if result.returncode == 0 else 'failed'
                yield f"data: {json.dumps({'event': 'step_end', 'step': step.name, 'status': status})}\n\n"
                
                if result.returncode != 0:
                    overall_status = 'failed'
                    break
            except Exception as e:
                logger.error(f"Error in step {step.name}: {str(e)}")
                overall_status = 'failed'
                yield f"data: {json.dumps({'event': 'error', 'step': step.name, 'message': str(e)})}\n\n"
                break

        logger.debug(f"Pipeline run completed with status: {overall_status}")
        pipeline_run.status = overall_status
        pipeline_run.finished_at = timezone.now()
        pipeline_run.save()
        agent.live = True  # Mark agent as idle
        agent.last_heartbeat = timezone.now()
        agent.save()

        redirect_url = reverse('pipeline_run_detail', args=[str(pipeline_run.run_id)])
        yield f"data: {json.dumps({'event': 'end', 'overall_status': overall_status, 'redirect_url': redirect_url})}\n\n"

    return StreamingHttpResponse(event_stream(), content_type='text/event-stream')


import json
from django.shortcuts import render, get_object_or_404
from .models import PipelineRun

def pipeline_run_detail(request, run_id):
    pipeline_run = get_object_or_404(PipelineRun, run_id=run_id)
    
    # Process the log data
    try:
        log_data = json.loads(pipeline_run.log) if pipeline_run.log else {}
    except json.JSONDecodeError:
        log_data = {"Error": "Unable to parse log data"}

    # If log_data is a string, wrap it in a dict
    if isinstance(log_data, str):
        log_data = {"Log": log_data}

    # Ensure log_data is a dict
    if not isinstance(log_data, dict):
        log_data = {"Error": "Log data is in an unexpected format"}

    context = {
        'pipeline_run': pipeline_run,
    }

    # Add the processed log data to the pipeline_run object
    pipeline_run.log = log_data

    return render(request, 'pipeline/pipeline_run_detail.html', context)
# views.py
from django.shortcuts import render
from django.http import JsonResponse
from .models import Agent, Command, Heartbeat
import uuid

import json
import uuid
import subprocess
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from .models import Agent, Command

import json
import logging
from django.http import JsonResponse, HttpResponse
from .models import Agent

logger = logging.getLogger(__name__)

@csrf_exempt
def register_agent(request):
    if request.method == 'POST':
        data = json.loads(request.body.decode('utf-8'))
        hostname = data.get('hostname')
        ip_address = data.get('ip_address')
        hash_key = data.get('hash_key')
        operating_system = data.get('operating_system')

        logger.info(f'Received registration request for agent with hash key: {hash_key}')

        try:
            agent, created = Agent.objects.update_or_create(
                hash_key=hash_key,
                defaults={
                    'hostname': hostname,
                    'ip_address': ip_address,
                    'operating_system': operating_system,
                    'last_heartbeat': timezone.now()
                }
            )
            if created:
                logger.info('Agent registered successfully.')
                return JsonResponse({'status': 'Agent registered successfully.'}, status=200)
            else:
                logger.info('Agent updated successfully.')
                return JsonResponse({'status': 'Agent updated successfully.'}, status=200)
        except Exception as e:
            logger.error(f'Error registering agent: {e}')
            return JsonResponse({'error': f'Error registering agent: {e}'}, status=500)

    logger.error('Invalid request method for agent registration.')
    return HttpResponse(status=400)


def add_agent(request):
    hash_key = uuid.uuid4().hex  # Generate a unique hash key
    command_windows = f"powershell -Command \"Invoke-WebRequest -Uri 'http://localhost:8000/path/to/windows_agent.py' -OutFile 'agent_install.py'; python agent_install.py --hash-key {hash_key}\""
    command_linux = f"curl -O http://localhost:8000/path/to/linux_agent.py && python3 linux_agent.py --hash-key {hash_key}"
    return render(request, 'pipeline/add_agent.html', {
        'hash_key': hash_key,
        'command_windows': command_windows,
        'command_linux': command_linux
    })


@csrf_exempt
def receive_command(request):
    if request.method == 'POST':
        data = json.loads(request.body.decode('utf-8'))
        command = data.get('command')
        # Implement logic to queue the command for the agent
        return JsonResponse({'status': 'Command received.'})
    return HttpResponse(status=400)

from django.utils import timezone
from datetime import timedelta

from django.utils import timezone

@csrf_exempt
def receive_heartbeat(request):
    if request.method == 'POST':
        data = json.loads(request.body.decode('utf-8'))
        hash_key = data.get('hash_key')
        
        # Get the current timestamp
        timestamp = timezone.now()

        try:
            agent = Agent.objects.get(hash_key=hash_key)
            agent.last_heartbeat = timestamp  # Update the heartbeat timestamp
            agent.save()

            return JsonResponse({'status': 'Heartbeat received.'}, status=200)
        except Agent.DoesNotExist:
            return JsonResponse({'error': 'Agent not found.'}, status=404)
    return JsonResponse({'error': 'Invalid request method.'}, status=405)

from django.shortcuts import render
from .models import Agent
from datetime import timedelta
from django.utils import timezone
from django.db import transaction
import logging

logger = logging.getLogger(__name__)

def check_agent_status():
    threshold = timedelta(minutes=1)  # Define the threshold for considering an agent inactive
    agents = Agent.objects.all()
    for agent in agents:
        if timezone.now() - agent.last_heartbeat > threshold:
            agent.live = False  # Mark the agent as offline
            agent.save(update_fields=['live'])  # Save only the 'live' field to improve performance
            logger.info(f"Agent {agent.hostname} marked as offline.")
        else:
            agent.live = True  # Mark the agent as online
            agent.save(update_fields=['live'])  # Save only the 'live' field to improve performance
            logger.info(f"Agent {agent.hostname} marked as online.")

def agent_list(request):
    check_agent_status()  # Check the status of each agent
    agents = Agent.objects.all()
    return render(request, 'pipeline/agent_list.html', {'agents': agents})


def send_command(request):
    if request.method == 'POST':
        data = request.POST
        hostname = data.get('hostname')
        command = data.get('command')

        agent = Agent.objects.get(hostname=hostname)
        Command.objects.create(agent=agent, command=command)

        return JsonResponse({'status': 'success', 'message': 'Command sent successfully.'})
    return JsonResponse({'status': 'error', 'message': 'Invalid request method.'})

def agent_instructions(request):
    return render(request, 'pipeline/agent_instructions.html')


from django.shortcuts import render, redirect, get_object_or_404
from .models import GlobalCredential
from .forms import GlobalCredentialForm

def global_credential_list(request):
    credentials = GlobalCredential.objects.all()
    return render(request, 'pipeline/global_credential_list.html', {'credentials': credentials})

def global_credential_detail(request, pk):
    credential = get_object_or_404(GlobalCredential, pk=pk)
    return render(request, 'pipeline/global_credential_detail.html', {'credential': credential})

def global_credential_create(request):
    if request.method == 'POST':
        form = GlobalCredentialForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('global_credential_list')
    else:
        form = GlobalCredentialForm()
    return render(request, 'pipeline/global_credential_form.html', {'form': form})

def global_credential_update(request, pk):
    credential = get_object_or_404(GlobalCredential, pk=pk)
    if request.method == 'POST':
        form = GlobalCredentialForm(request.POST, instance=credential)
        if form.is_valid():
            form.save()
            return redirect('global_credential_list')
    else:
        form = GlobalCredentialForm(instance=credential)
    return render(request, 'pipeline/global_credential_form.html', {'form': form})

def global_credential_delete(request, pk):
    credential = get_object_or_404(GlobalCredential, pk=pk)
    if request.method == 'POST':
        credential.delete()
        return redirect('global_credential_list')
    return render(request, 'pipeline/global_credential_confirm_delete.html', {'credential': credential})

from django.shortcuts import render, redirect, get_object_or_404
from .models import LocalCredential
from .forms import LocalCredentialForm

def local_credential_list(request, project_id):
    credentials = LocalCredential.objects.filter(project_id=project_id)
    return render(request, 'pipeline/local_credential_list.html', {'credentials': credentials, 'project_id': project_id})

def local_credential_detail(request, pk):
    credential = get_object_or_404(LocalCredential, pk=pk)
    return render(request, 'pipeline/local_credential_detail.html', {'credential': credential})

def local_credential_create(request, project_id):
    if request.method == 'POST':
        form = LocalCredentialForm(request.POST)
        if form.is_valid():
            credential = form.save(commit=False)
            credential.project_id = project_id
            credential.save()
            return redirect('local_credential_list', project_id=project_id)
    else:
        form = LocalCredentialForm()
    return render(request, 'pipeline/local_credential_form.html', {'form': form})

def local_credential_update(request, pk):
    credential = get_object_or_404(LocalCredential, pk=pk)
    if request.method == 'POST':
        form = LocalCredentialForm(request.POST, instance=credential)
        if form.is_valid():
            form.save()
            return redirect('local_credential_list', project_id=credential.project_id)
    else:
        form = LocalCredentialForm(instance=credential)
    return render(request, 'pipeline/local_credential_form.html', {'form': form})

def local_credential_delete(request, pk):
    credential = get_object_or_404(LocalCredential, pk=pk)
    project_id = credential.project_id
    if request.method == 'POST':
        credential.delete()
        return redirect('local_credential_list', project_id=project_id)
    return render(request, 'pipeline/local_credential_confirm_delete.html', {'credential': credential})

from .models import Project, Application
from .forms import ApplicationForm

def create_application(request, project_id):
    project = get_object_or_404(Project, id=project_id)
    if request.method == 'POST':
        form = ApplicationForm(request.POST)
        if form.is_valid():
            application = form.save(commit=False)
            application.project = project
            application.save()
            return redirect('project_detail', project_id=project.id)
    else:
        form = ApplicationForm()
    return render(request, 'pipeline/create_application.html', {'form': form, 'project': project})

def application_list(request):
    applications = Application.objects.all()
    return render(request, 'pipeline/application_list.html', {'applications':applications})

def application_detail(request, application_id):
    application = get_object_or_404(Application, id=application_id)
    pipelines = application.pipelines.all()
    return render(request, 'pipeline/application_detail.html', {'application': application, 'pipelines': pipelines})


import yaml
from django.http import JsonResponse
from django.shortcuts import render
from .models import Project, GlobalCredential, LocalCredential, Agent, Pipeline, PipelineStep

def create_yaml_pipeline(request):
    if request.method == 'POST':
        yaml_data = request.POST.get('yaml_data')

        if not yaml_data:
            return JsonResponse({'error': 'YAML data is empty'}, status=400)

        try:
            yaml_parsed = yaml.safe_load(yaml_data)
        except yaml.YAMLError as e:
            return JsonResponse({'error': 'Invalid YAML format'}, status=400)

        # Validate project name
        project_name = yaml_parsed.get('project_name')
        project = Project.objects.filter(name=project_name).first()
        if not project:
            return JsonResponse({'error': 'Project not found'}, status=404)

        # Validate agent name
        agent_name = yaml_parsed.get('agent')
        agent = Agent.objects.filter(hostname=agent_name).first()
        if not agent:
            return JsonResponse({'error': 'Agent not found'}, status=404)

        # Create or update the pipeline
        pipeline_name = yaml_parsed.get('pipeline_name')
        pipeline_description = yaml_parsed.get('description', '')

        # Check if a pipeline with the same name already exists for the project
        pipeline, created = Pipeline.objects.get_or_create(project=project, name=pipeline_name, defaults={'description': pipeline_description})

        # Update pipeline description if it's not created
        if not created:
            pipeline.description = pipeline_description
            pipeline.save()

        # Create or update pipeline steps
        steps_data = yaml_parsed.get('steps', [])
        for step_data in steps_data:
            name = step_data.get('name')
            condition = step_data.get('condition', '')
            command = step_data.get('command')
            PipelineStep.objects.update_or_create(pipeline=pipeline, name=name, defaults={'condition': condition, 'command': command})

        return JsonResponse({'success': 'Pipeline created/updated successfully'}, status=201)

    else:
        projects = Project.objects.all()
        return render(request, 'pipeline/create_yaml_pipeline.html', {'projects': projects})
