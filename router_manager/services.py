from .models import RouterConfig, PortForwardingRule
from .router_clients import get_router_client
import threading

class PortManagementService:
    def __init__(self):
        self.port_range_start = 10000
        self.port_range_end = 20000
    
    def assign_customer_port(self, customer, router):
        """Assign a unique external port for customer"""
        # Get used ports
        used_ports = PortForwardingRule.objects.filter(
            router=router,
            is_active=True
        ).values_list('external_port', flat=True)
        
        # Find available port
        for port in range(self.port_range_start, self.port_range_end + 1):
            if port not in used_ports:
                return port
        
        raise Exception("No available ports in range")
    
    def setup_customer_port_forwarding(self, customer, router):
        """Set up port forwarding for a customer"""
        try:
            # Assign external port
            external_port = self.assign_customer_port(customer, router)
            
            # Get customer's device IP (this would come from device registration)
            customer_ip = self.get_customer_ip(customer)
            
            if not customer_ip:
                raise Exception("Could not determine customer IP address")
            
            # Create port forwarding rule
            client = get_router_client(router)
            
            success = client.add_port_forwarding(
                external_port=external_port,
                internal_ip=customer_ip,
                internal_port=80,  # Default web port
                protocol='tcp',
                description=f"Customer_{customer.username}_Web"
            )
            
            if success:
                # Save rule to database
                PortForwardingRule.objects.create(
                    router=router,
                    customer=customer,
                    external_port=external_port,
                    internal_ip=customer_ip,
                    internal_port=80,
                    protocol='tcp',
                    description=f"Web access for {customer.username}"
                )
                
                return external_port
            else:
                raise Exception("Failed to configure port forwarding on router")
                
        except Exception as e:
            print(f"Port forwarding setup error: {e}")
            raise
    
    def remove_customer_port_forwarding(self, customer, router):
        """Remove port forwarding for a customer"""
        try:
            rules = PortForwardingRule.objects.filter(
                customer=customer,
                router=router,
                is_active=True
            )
            
            client = get_router_client(router)
            
            for rule in rules:
                success = client.remove_port_forwarding(
                    external_port=rule.external_port,
                    protocol=rule.protocol
                )
                
                if success:
                    rule.is_active = False
                    rule.save()
                else:
                    print(f"Failed to remove rule for port {rule.external_port}")
                    
        except Exception as e:
            print(f"Port forwarding removal error: {e}")
    
    def get_customer_ip(self, customer):
        """Get customer's IP address (simplified - implement based on your setup)"""
        # This could come from:
        # 1. DHCP lease table
        # 2. Device MAC address mapping
        # 3. Customer self-configuration
        # 4. Network discovery
        
        # For now, return a placeholder
        # In production, implement proper IP discovery
        return "192.168.1.100"  # Example

# Singleton instance
port_service = PortManagementService()