"""
pipeline/management/commands/run_pipeline_worker.py

Dedicated foreground CI/CD pipeline worker process designed for systemd management.
Listens for SIGTERM / SIGINT for graceful shutdown.
"""

import logging
import signal
import sys

from django.core.management.base import BaseCommand
from pipeline.worker import start_pipeline_worker, stop_pipeline_worker

logger = logging.getLogger('pipeline.worker')


class Command(BaseCommand):
    help = "Run the dedicated foreground CI/CD pipeline worker service"

    def add_arguments(self, parser):
        parser.add_argument(
            '--poll-interval',
            type=int,
            default=5,
            help='Polling interval in seconds between queue checks (default: 5)',
        )

    def handle(self, *args, **options):
        poll_interval = options.get('poll_interval') or 5
        self.stdout.write(self.style.SUCCESS(
            f"Starting CogFocus One™ CI/CD Pipeline Worker (poll interval: {poll_interval}s)..."
        ))

        def _handle_exit_signal(signum, frame):
            sig_name = signal.Signals(signum).name
            self.stdout.write(self.style.WARNING(f"\nReceived {sig_name}; shutting down pipeline worker gracefully..."))
            stop_pipeline_worker()

        try:
            signal.signal(signal.SIGINT, _handle_exit_signal)
            signal.signal(signal.SIGTERM, _handle_exit_signal)
        except Exception as e:
            logger.debug(f"Signal handling registration note: {e}")

        try:
            start_pipeline_worker(poll_interval=poll_interval)
            self.stdout.write(self.style.SUCCESS("Pipeline worker stopped cleanly."))
        except Exception as exc:
            self.stderr.write(self.style.ERROR(f"Worker encountered fatal error: {exc}"))
            sys.exit(1)
