# router_manager/apps.py
from django.apps import AppConfig


class RouterManagerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'router_manager'
    
    def ready(self):
        # Import here to avoid circular imports
        import logging
        
        # Check if we're in a management command (like makemigrations)
        import sys
        if 'makemigrations' in sys.argv or 'migrate' in sys.argv:
            # Skip initialization during migrations
            return
        
        try:
            from .services import router_manager, port_service
            
            # Optional: You could start some monitoring here if needed
            logger = logging.getLogger(__name__)
            logger.info("RouterManager services initialized")
            
        except ImportError as e:
            # Log but don't crash if services can't be imported
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Could not initialize router services: {e}")