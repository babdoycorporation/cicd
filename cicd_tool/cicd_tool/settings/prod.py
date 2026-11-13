"""
cicd_tool/settings/prod.py — Production Settings for CogFocus One™ Enterprise
"""

import os
import logging
from .base import *

logger = logging.getLogger(__name__)

DEBUG = os.environ.get('DJANGO_DEBUG', 'False').lower() in ('true', '1')

ALLOWED_HOSTS = [
    h.strip() for h in os.environ.get('DJANGO_ALLOWED_HOSTS', '*').split(',')
    if h.strip()
]

# ── Database (Production Environment Override: PostgreSQL / MySQL / SQLite) ──
DATABASE_URL = os.environ.get('DATABASE_URL')

if DATABASE_URL:
    try:
        import urllib.parse as urlparse
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
        logger.error(f"Failed to parse DATABASE_URL: {db_err}. Falling back to default DB.")
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

# ── Production Security Hardening ─────────────────────────────────────────────
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'

# Enable HTTPS/SSL headers when reverse proxy handles TLS
if os.environ.get('SECURE_SSL_REDIRECT', 'False').lower() in ('true', '1'):
    SECURE_SSL_REDIRECT = True
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

# ── Email Backend (SMTP Integration) ─────────────────────────────────────────
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = os.environ.get('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', 587))
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
EMAIL_USE_TLS = os.environ.get('EMAIL_USE_TLS', 'True').lower() == 'true'
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'CogFocus One Enterprise <noreply@cogfocus.com>')
