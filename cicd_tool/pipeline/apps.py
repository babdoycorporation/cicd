import os
import threading

from django.apps import AppConfig


class PipelineConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'pipeline'

    def ready(self):
        """Start the background pipeline worker when Django boots.

        Guard against double-start in autoreload scenarios and allow
        disabling inside web workers via RUN_PIPELINE_WORKER=false when
        running a dedicated systemd worker service.
        """
        if os.environ.get('RUN_PIPELINE_WORKER', 'true').lower() in ('false', '0', 'no'):
            return

        # Skip management commands like migrate / collectstatic / check when detected
        import sys
        if len(sys.argv) > 1 and sys.argv[1] in ('migrate', 'makemigrations', 'collectstatic', 'check', 'shell', 'test', 'run_pipeline_worker'):
            return

        run_main = os.environ.get('RUN_MAIN', 'false')
        if run_main == 'true' or not os.environ.get('DJANGO_SETTINGS_MODULE'):
            # Executed via manage.py runserver (child process) or gunicorn worker
            return

        from .worker import start_pipeline_worker
        t = threading.Thread(target=start_pipeline_worker, daemon=True, name='pipeline-worker')
        t.start()
