"""
pipeline/worker.py  —  Background thread that auto-executes pending PipelineRuns.

Started by PipelineConfig.ready() so it runs inside the Django process.
Every 10 seconds it picks up all 'pending' runs and dispatches each to its own
thread so multiple pipelines run concurrently.
"""

import logging
import threading
import time

logger = logging.getLogger(__name__)

_started = False
_lock = threading.Lock()


def start_pipeline_worker():
    global _started
    with _lock:
        if _started:
            return
        _started = True
    logger.info("Pipeline background worker started.")
    _poll_loop()


def _poll_loop():
    while True:
        try:
            _dispatch_pending()
            _dispatch_project_runs()
        except Exception as e:
            logger.error(f"Worker poll error: {e}")
        time.sleep(10)


def _dispatch_pending():
    from .models import PipelineRun
    from .utils import get_available_agent

    pending = list(PipelineRun.objects.filter(status='pending').select_related('pipeline'))
    if not pending:
        return

    for run in pending:
        try:
            agent = get_available_agent()
        except ValueError:
            logger.debug("No agent available; will retry next cycle.")
            break  # No point trying more runs if no agents
        agent.live = False
        agent.save(update_fields=['live'])
        run.status = 'running'
        run.agent = agent
        run.save(update_fields=['status', 'agent'])
        t = threading.Thread(target=_execute_run, args=(run.pk, agent.pk), daemon=True)
        t.start()
        logger.info(f"Dispatched run {run.run_id} to agent {agent.hostname}")


def _execute_run(run_pk, agent_pk):
    """Runs in a dedicated thread per PipelineRun."""
    import os
    from django.utils import timezone
    from .models import Agent, PipelineRun
    from .utils import (BASE_RUNS_DIR, checkout_repository, execute_step,
                        prepare_credentials)

    run = PipelineRun.objects.select_related('pipeline__application__project').get(pk=run_pk)
    agent = Agent.objects.get(pk=agent_pk)

    overall_status = 'success'
    log_lines = []

    try:
        project = run.pipeline.application.project if run.pipeline.application else None
        credentials = prepare_credentials(project) if project else {}

        # Standard CI environment variables (available in every step)
        credentials.update({
            'CI': 'true',
            'CI_PIPELINE': run.pipeline.name,
            'CI_BRANCH': run.pipeline.monitored_branch or '',
            'CI_PROJECT': project.name if project else '',
            'CI_RUN_ID': str(run.run_id),
            'CI_AGENT': agent.hostname,
        })

        # Check out the linked repository into the run workspace
        run_dir = os.path.join(BASE_RUNS_DIR, str(run.run_id))
        os.makedirs(run_dir, exist_ok=True)
        workdir, checkout_log = checkout_repository(run, run_dir)
        log_lines.extend(checkout_log)
        run.log = '\n'.join(log_lines)
        run.save(update_fields=['log'])

        steps = list(run.pipeline.pipelinestep_set.all().order_by('id'))

        if not steps:
            log_lines.append("[INFO] No steps defined for this pipeline.")
            overall_status = 'success'
        else:
            for step in steps:
                log_lines.append(f"[STEP] {step.name}")
                run.log = '\n'.join(log_lines)
                run.save(update_fields=['log'])
                try:
                    result = execute_step(step, run.run_id, credentials, workdir=workdir)
                    log_lines.extend(result.stdout.splitlines())
                    if result.returncode != 0:
                        log_lines.append(f"[FAILED] {step.name} exited {result.returncode}")
                        overall_status = 'failed'
                        break
                    log_lines.append(f"[OK] {step.name}")
                except Exception as e:
                    log_lines.append(f"[ERROR] {step.name}: {e}")
                    overall_status = 'failed'
                    break
                finally:
                    run.log = '\n'.join(log_lines)
                    run.save(update_fields=['log'])

    except Exception as e:
        log_lines.append(f"[FATAL] {e}")
        overall_status = 'failed'
    finally:
        run.status = overall_status
        run.finished_at = timezone.now()
        run.log = '\n'.join(log_lines)
        run.save()
        agent.live = True
        agent.last_heartbeat = timezone.now()
        agent.save(update_fields=['live', 'last_heartbeat'])
        logger.info(f"Run {run.run_id} finished: {overall_status}")

def _dispatch_project_runs():
    from .models import ProjectPipelineRun
    pending = list(ProjectPipelineRun.objects.filter(status='pending'))
    if not pending:
        return
    for run in pending:
        run.status = 'running'
        run.save(update_fields=['status'])
        t = threading.Thread(target=_execute_project_run, args=(run.pk,), daemon=True)
        t.start()
        logger.info(f"Dispatched orchestrator run {run.run_id}")

def _execute_project_run(run_pk):
    import time
    from django.utils import timezone
    from .models import ProjectPipelineRun, PipelineRun

    run = ProjectPipelineRun.objects.get(pk=run_pk)
    overall_status = 'SUCCESS'
    log_lines = []

    try:
        steps = list(run.project_pipeline.steps.all().order_by('order'))
        if not steps:
            log_lines.append("[INFO] No steps defined for this orchestrator.")
        else:
            for step in steps:
                target_pipeline = step.target_pipeline
                log_lines.append(f"\\n[STAGE] Triggering {target_pipeline.name} (Step Order {step.order})")
                run.log = '\\n'.join(log_lines)
                run.save(update_fields=['log'])

                # Queue the application pipeline
                app_run = PipelineRun.objects.create(pipeline=target_pipeline, status='pending')
                log_lines.append(f"[INFO] Created PipelineRun #{app_run.run_id}")
                
                # Wait for it to finish
                while True:
                    time.sleep(5)
                    app_run.refresh_from_db()
                    if app_run.status in ('SUCCESS', 'FAILED'):
                        break
                
                if app_run.status == 'SUCCESS':
                    log_lines.append(f"[OK] {target_pipeline.name} finished successfully.")
                else:
                    log_lines.append(f"[FAILED] {target_pipeline.name} failed.")
                    overall_status = 'FAILED'
                    break
                run.log = '\\n'.join(log_lines)
                run.save(update_fields=['log'])

    except Exception as e:
        log_lines.append(f"[FATAL] {e}")
        overall_status = 'FAILED'
    finally:
        run.status = overall_status
        run.finished_at = timezone.now()
        run.log = '\\n'.join(log_lines)
        run.save()
        logger.info(f"Orchestrator Run {run.run_id} finished: {overall_status}")

