"""
WSGI config for m_neti project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'm_neti.settings')

application = get_wsgi_application()

# Import and start router manager after app is ready
try:
    from router_manager.services import router_monitor
    
    # Start router monitor in background thread
    # Note: In production, use a proper process manager like systemd
    router_monitor.start()
    
    print("Router Manager initialized in WSGI")
except Exception as e:
    print(f"Failed to initialize Router Manager in WSGI: {e}")

app = application
