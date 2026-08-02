"""
cicd_tool/settings/dev.py — Development Settings
"""

from .base import *

DEBUG = True

ALLOWED_HOSTS = ['*']

# ── Database (Local SQLite for Dev) ──────────────────────────────────────────
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# ── Email Backend (Console delivery for development testing) ─────────────────
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
DEFAULT_FROM_EMAIL = 'CogFocus One Dev <noreply@cogfocus.local>'
