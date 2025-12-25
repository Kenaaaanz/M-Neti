# router_manager/management/commands/manage_routers.py
from django.core.management.base import BaseCommand
from router_manager.services import router_monitor, router_manager, port_service, health_check
import time
import json

class Command(BaseCommand):
    help = 'Manage router monitoring and services'
    
    def add_arguments(self, parser):
        parser.add_argument(
            'action',
            choices=['start', 'stop', 'status', 'sync-all', 'health', 'discover'],
            help='Action to perform'
        )
        parser.add_argument(
            '--network',
            type=str,
            help='Network range for discovery (e.g., 192.168.1.0/24)'
        )
        parser.add_argument(
            '--router-id',
            type=int,
            help='Router ID for specific actions'
        )
    
    def handle(self, *args, **options):
        action = options['action']
        
        if action == 'start':
            self.start_monitor()
        elif action == 'stop':
            self.stop_monitor()
        elif action == 'status':
            self.show_status()
        elif action == 'sync-all':
            self.sync_all_routers()
        elif action == 'health':
            self.show_health()
        elif action == 'discover':
            self.discover_routers(options.get('network'))
    
    def start_monitor(self):
        """Start the router monitor"""
        if router_monitor.running:
            self.stdout.write(self.style.WARNING('Router monitor is already running'))
        else:
            router_monitor.start()
            self.stdout.write(self.style.SUCCESS('Router monitor started'))
    
    def stop_monitor(self):
        """Stop the router monitor"""
        if not router_monitor.running:
            self.stdout.write(self.style.WARNING('Router monitor is not running'))
        else:
            router_monitor.stop()
            self.stdout.write(self.style.SUCCESS('Router monitor stopped'))
    
    def show_status(self):
        """Show router monitor status"""
        status = {
            'monitor_running': router_monitor.running,
            'sync_interval': router_monitor.sync_interval,
        }
        
        self.stdout.write(json.dumps(status, indent=2))
    
    def sync_all_routers(self):
        """Manually sync all routers"""
        from router_manager.models import RouterConfig
        
        router_configs = RouterConfig.objects.all()
        total = router_configs.count()
        success = 0
        
        self.stdout.write(f'Syncing {total} routers...')
        
        for config in router_configs:
            try:
                if router_monitor.sync_router(config.id):
                    self.stdout.write(self.style.SUCCESS(f'✓ {config.name}: Synced'))
                    success += 1
                else:
                    self.stdout.write(self.style.ERROR(f'✗ {config.name}: Failed'))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'✗ {config.name}: {str(e)}'))
        
        self.stdout.write(f'\nCompleted: {success}/{total} routers synced successfully')
    
    def show_health(self):
        """Show system health"""
        health = health_check()
        self.stdout.write(json.dumps(health, indent=2))
    
    def discover_routers(self, network_range=None):
        """Discover routers in network"""
        from router_manager.services import discover_routers_in_network
        
        if not network_range:
            network_range = '192.168.1.0/24'
        
        self.stdout.write(f'Discovering routers in {network_range}...')
        
        routers = discover_routers_in_network(network_range)
        
        if routers:
            self.stdout.write(f'Found {len(routers)} potential routers:')
            for router in routers:
                self.stdout.write(f"  • {router['ip_address']}:{router['port']}")
        else:
            self.stdout.write(self.style.WARNING('No routers found'))