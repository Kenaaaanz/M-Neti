# Create accounts/consumers.py for WebSocket
from channels.generic.websocket import AsyncWebsocketConsumer
import json

class MapConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.user = self.scope['user']
        if self.user.is_authenticated and self.user.role in ['isp_admin', 'isp_staff']:
            await self.accept()
            
            # Join room for this tenant
            self.room_group_name = f'map_updates_{self.user.tenant.id}'
            await self.channel_layer.group_add(
                self.room_group_name,
                self.channel_name
            )
        else:
            await self.close()

    async def disconnect(self, close_code):
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_discard(
                self.room_group_name,
                self.channel_name
            )

    # Receive message from WebSocket
    async def receive(self, text_data):
        text_data_json = json.loads(text_data)
        message = text_data_json['message']

        # Send message to room group
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'map_update',
                'message': message
            }
        )

    # Receive message from room group
    async def map_update(self, event):
        message = event['message']

        # Send message to WebSocket
        await self.send(text_data=json.dumps({
            'message': message,
            'type': 'refresh'
        }))