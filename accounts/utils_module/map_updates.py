# accounts/utils/map_updates.py
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
import json

def send_map_update(tenant_id, update_type, data=None):
    """
    Send WebSocket update to refresh map
    """
    try:
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f'map_updates_{tenant_id}',
            {
                'type': 'map_update',
                'message': {
                    'update_type': update_type,
                    'data': data,
                    'timestamp': timezone.now().isoformat()
                }
            }
        )
        return True
    except Exception as e:
        print(f"Error sending map update: {e}")
        return False