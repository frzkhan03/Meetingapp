"""
WSGI config for gmeet project.
"""

import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'meet.settings')

application = get_wsgi_application()
