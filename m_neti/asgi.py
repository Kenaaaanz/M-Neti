"""
ASGI config for m_neti project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/asgi/
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'm_neti.settings')

application = get_asgi_application()

try:
    from router_manager.services import router_monitor
    
    # Start router monitor in background thread
    router_monitor.start()
    
    print("Router Manager initialized in ASGI")
except Exception as e:
    print(f"Failed to initialize Router Manager in ASGI: {e}")
