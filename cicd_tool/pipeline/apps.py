import os
import threading

from django.apps import AppConfig


class PipelineConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'pipeline'

    def ready(self):
        """Start the background pipeline worker when Django boots.

        Guard against double-start in multi-process / autoreload scenarios.
        RUN_MAIN is set by Django's autoreloader child process — only start
        the worker in the child (or when autoreloader is disabled).
        """
        run_main = os.environ.get('RUN_MAIN', 'false')
        if run_main == 'true' or not os.environ.get('DJANGO_SETTINGS_MODULE'):
            # Executed via manage.py runserver (child process) or gunicorn worker
            return

        # Always start in the main process / gunicorn worker
        from .worker import start_pipeline_worker
        t = threading.Thread(target=start_pipeline_worker, daemon=True, name='pipeline-worker')
        t.start()
