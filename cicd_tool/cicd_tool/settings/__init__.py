"""
cicd_tool/settings/__init__.py — Environment Selector

Usage:
    export DJANGO_ENV=prod  (or set DJANGO_ENV=prod in environment)
"""

import os

env = os.environ.get('DJANGO_ENV', 'dev').lower().strip()

if env == 'prod' or env == 'production':
    from .prod import *
else:
    from .dev import *
