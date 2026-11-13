"""
cicd_tool/settings/dev.py — Development Settings
"""

import os
import urllib.parse as urlparse
from .base import *

DEBUG = True

ALLOWED_HOSTS = ['*']

# ── Database (Local SQLite for Dev or PostgreSQL via DATABASE_URL) ───────────
DATABASE_URL = os.environ.get('DATABASE_URL')
if DATABASE_URL:
    try:
        url = urlparse.urlparse(DATABASE_URL)
        engine = 'django.db.backends.postgresql' if 'postgres' in url.scheme else 'django.db.backends.mysql'
        DATABASES = {
            'default': {
                'ENGINE': engine,
                'NAME': url.path[1:],
                'USER': url.username,
                'PASSWORD': url.password,
                'HOST': url.hostname,
                'PORT': url.port or ('5432' if 'postgres' in url.scheme else '3306'),
                'CONN_MAX_AGE': 600,
            }
        }
    except Exception as db_err:
        DATABASES = {
            'default': {
                'ENGINE': 'django.db.backends.sqlite3',
                'NAME': BASE_DIR / 'db.sqlite3',
            }
        }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

# ── Email Backend (Console delivery for development testing) ─────────────────
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
DEFAULT_FROM_EMAIL = 'CogFocus One Dev <noreply@cogfocus.local>'
