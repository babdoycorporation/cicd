"""
pipeline/worker.py  —  Background thread that auto-executes pending PipelineRuns.

Started by PipelineConfig.ready() (unless RUN_PIPELINE_WORKER=false) or by a
standalone systemd worker process. Uses atomic compare-and-set updates so
multiple Gunicorn workers cannot claim the same pending run or agent.
"""

import logging
import threading
import time

logger = logging.getLogger(__name__)

_started = False
_running = True
_stop_event = threading.Event()
_lock = threading.Lock()


def start_pipeline_worker(poll_interval: int = 5):
    global _started, _running
    with _lock:
        if _started:
            return
        _started = True
        _running = True
        _stop_event.clear()
    logger.info(f"Pipeline background worker started (poll_interval={poll_interval}s).")
    _poll_loop(poll_interval=poll_interval)


def stop_pipeline_worker():
    global _running
    _running = False
    _stop_event.set()
    logger.info("Pipeline background worker stop requested.")


def _poll_loop(poll_interval: int = 5):
    from .utils import ensure_local_runner_agent

    while _running and not _stop_event.is_set():
        try:
            ensure_local_runner_agent()
        except Exception as e:
            logger.debug(f"Local runner heartbeat skipped: {e}")

        try:
            _dispatch_pending()
            _dispatch_project_runs()
        except Exception as e:
            logger.error(f"Worker poll error: {e}")
        _stop_event.wait(timeout=max(1, int(poll_interval)))


def _dispatch_pending():
    from django.db import transaction
    from .models import Agent, PipelineRun
    from .utils import get_available_agent

    pending_ids = list(
        PipelineRun.objects.filter(status='pending').order_by('started_at').values_list('pk', flat=True)
    )
    if not pending_ids:
        return

    for run_pk in pending_ids:
        with transaction.atomic():
            try:
                agent = get_available_agent()
            except ValueError:
                logger.debug("No agent available; will retry next cycle.")
                break

            # Atomically claim both the agent and the pending run
            agent_claimed = Agent.objects.filter(pk=agent.pk, live=True).update(live=False)
            if not agent_claimed:
                continue

            run_claimed = PipelineRun.objects.filter(pk=run_pk, status='pending').update(
                status='running', agent=agent
            )
            if not run_claimed:
                # Already claimed by another worker — release the agent
                Agent.objects.filter(pk=agent.pk).update(live=True)
                continue

        t = threading.Thread(target=_execute_run, args=(run_pk, agent.pk), daemon=True)
        t.start()
        logger.info(f"Dispatched run pk={run_pk} to agent {agent.hostname}")


def _should_run_step(condition: str, overall_status: str) -> bool:
    cond = (condition or '').strip().lower()
    if cond == 'always':
        return True
    if cond == 'on_failure':
        return overall_status == 'failed'
    # Default ('', 'on_success'): run only while pipeline has not failed
    return overall_status == 'success'


def _execute_run(run_pk, agent_pk):
    """Runs in a dedicated thread per PipelineRun."""
    import os
    from django.utils import timezone
    from .models import Agent, PipelineRun
    from .utils import (BASE_RUNS_DIR, checkout_repository, execute_deploy,
                        execute_step, is_artifact_command, is_deploy_command,
                        prepare_credentials, store_artifact,
                        sync_pipeline_from_repo_workdir)

    run = PipelineRun.objects.select_related('pipeline__application__project').get(pk=run_pk)
    agent = Agent.objects.get(pk=agent_pk)

    overall_status = 'success'
    log_lines = run.log.splitlines() if run.log else []

    try:
        project = run.pipeline.application.project if run.pipeline.application else None
        credentials = prepare_credentials(project)

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

        # Sync latest YAML definition if present in checked-out repo
        synced_count = sync_pipeline_from_repo_workdir(run.pipeline, workdir)
        if synced_count > 0:
            log_lines.append(f"[YAML] Synced {synced_count} step(s) from repository configuration.")

        run.log = '\n'.join(log_lines)
        run.save(update_fields=['log'])

        steps = list(run.pipeline.pipelinestep_set.all().order_by('id'))

        if not steps:
            log_lines.append("[INFO] No steps defined for this pipeline.")
            overall_status = 'success'
        else:
            for step in steps:
                if not _should_run_step(step.condition, overall_status):
                    log_lines.append(f"[SKIP] {step.name} (condition: {step.condition or 'on_success'})")
                    continue

                log_lines.append(f"[STEP] {step.name}")
                run.log = '\n'.join(log_lines)
                run.save(update_fields=['log'])
                try:
                    if is_artifact_command(step.command):
                        stored = store_artifact(step.command, run, workdir)
                        names = ', '.join(a.name for a in stored) or 'no files matched'
                        log_lines.append(f"[ARTIFACT] Stored: {names}")
                        result_rc = 0
                    elif is_deploy_command(step.command):
                        result = execute_deploy(step.command, run.run_id, workdir=workdir)
                        log_lines.extend(result.stdout.splitlines())
                        result_rc = result.returncode
                    else:
                        result = execute_step(step, run.run_id, credentials, workdir=workdir)
                        log_lines.extend(result.stdout.splitlines())
                        result_rc = result.returncode

                    if result_rc != 0:
                        log_lines.append(f"[FAILED] {step.name} exited {result_rc}")
                        overall_status = 'failed'
                    else:
                        log_lines.append(f"[OK] {step.name}")
                except Exception as e:
                    log_lines.append(f"[ERROR] {step.name}: {e}")
                    overall_status = 'failed'
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

        # ── Email notification ────────────────────────────────────────────────
        try:
            from .notifications import send_notification
            from django.contrib.auth.models import User
            event = 'pipeline_success' if overall_status == 'success' else 'pipeline_failure'
            emoji = '✅' if overall_status == 'success' else '❌'
            pipeline_obj = run.pipeline
            app = pipeline_obj.application
            notify_users = []
            if app and app.project:
                notify_users = list(User.objects.filter(
                    project_memberships__project=app.project
                ).exclude(email=''))
            send_notification(
                event_type=event,
                subject=f"{emoji} {pipeline_obj.name} — {overall_status.upper()}",
                body=(
                    f"Pipeline:  {pipeline_obj.name}\n"
                    f"Status:    {overall_status.upper()}\n"
                    f"Run ID:    {run.run_id}\n"
                    f"Branch:    {pipeline_obj.monitored_branch}\n"
                    f"Agent:     {agent.hostname}"
                ),
                users=notify_users,
            )
        except Exception as notify_err:
            logger.warning(f"Notification send error: {notify_err}")


def _dispatch_project_runs():
    from .models import ProjectPipelineRun

    pending_ids = list(
        ProjectPipelineRun.objects.filter(status='pending').values_list('pk', flat=True)
    )
    if not pending_ids:
        return
    for run_pk in pending_ids:
        claimed = ProjectPipelineRun.objects.filter(pk=run_pk, status='pending').update(status='running')
        if not claimed:
            continue
        t = threading.Thread(target=_execute_project_run, args=(run_pk,), daemon=True)
        t.start()
        logger.info(f"Dispatched orchestrator run pk={run_pk}")


def _execute_project_run(run_pk):
    import time
    from django.utils import timezone
    from .models import ProjectPipelineRun, PipelineRun

    run = ProjectPipelineRun.objects.get(pk=run_pk)
    overall_status = 'success'
    log_lines = []

    try:
        steps = list(run.project_pipeline.steps.all().order_by('order'))
        if not steps:
            log_lines.append("[INFO] No steps defined for this orchestrator.")
        else:
            for step in steps:
                target_pipeline = step.target_pipeline
                log_lines.append(f"\n[STAGE] Triggering {target_pipeline.name} (Step Order {step.order})")
                run.log = '\n'.join(log_lines)
                run.save(update_fields=['log'])

                app_run = PipelineRun.objects.create(pipeline=target_pipeline, status='pending')
                log_lines.append(f"[INFO] Created PipelineRun #{app_run.run_id}")

                waited = 0
                max_wait_sec = 3600
                while waited < max_wait_sec:
                    time.sleep(5)
                    waited += 5
                    app_run.refresh_from_db()
                    if app_run.status.lower() in ('success', 'failed'):
                        break

                if app_run.status.lower() == 'success':
                    log_lines.append(f"[OK] {target_pipeline.name} finished successfully.")
                else:
                    log_lines.append(f"[FAILED] {target_pipeline.name} failed (status={app_run.status}).")
                    overall_status = 'failed'
                    break
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
        logger.info(f"Orchestrator Run {run.run_id} finished: {overall_status}")
