from .huawei_client import HuaweiClient
from .tenda_client import TendaClient

def get_router_client(router_config):
    """Factory function to get appropriate router client"""
    if router_config.router_type == 'huawei':
        return HuaweiClient(router_config)
    elif router_config.router_type == 'tenda':
        return TendaClient(router_config)
    else:
        raise ValueError(f"Unsupported router type: {router_config.router_type}")