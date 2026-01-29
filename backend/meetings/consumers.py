import json
import logging
from channels.generic.websocket import AsyncWebsocketConsumer

logger = logging.getLogger(__name__)

# Maximum message size in bytes (64 KB)
MAX_MESSAGE_SIZE = 65536
# Maximum connections per room
MAX_ROOM_CONNECTIONS = 500


class RoomConsumer(AsyncWebsocketConsumer):
    # Redis-backed room user tracking via channel layer
    # Each instance only tracks its own state; distributed state uses channel layer groups

    async def connect(self):
        self.room_id = self.scope['url_route']['kwargs']['room_id']
        self.room_group_name = f'room_{self.room_id}'
        self.user_id = self.scope.get(
            'user_id',
            str(self.scope['user'].id) if self.scope['user'].is_authenticated else None
        )

        # Enforce per-room connection limit via Redis cache
        room_count_key = f'ws:room:count:{self.room_id}'
        try:
            from django.core.cache import cache
            try:
                count = cache.incr(room_count_key)
            except ValueError:
                cache.set(room_count_key, 1, 7200)  # 2h TTL
                count = 1

            if count > MAX_ROOM_CONNECTIONS:
                cache.decr(room_count_key)
                logger.warning(f"Room {self.room_id} at capacity ({MAX_ROOM_CONNECTIONS})")
                await self.close(code=4029)
                return
        except Exception:
            pass  # Fail open if Redis is down

        # Join room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        await self.accept()

    async def disconnect(self, close_code):
        # Decrement room connection count
        room_count_key = f'ws:room:count:{self.room_id}'
        try:
            from django.core.cache import cache
            new_val = cache.decr(room_count_key)
            if new_val <= 0:
                cache.delete(room_count_key)
        except (ValueError, Exception):
            pass

        if hasattr(self, 'user_id') and self.user_id:
            # Notify others of disconnect
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'user_disconnected',
                    'user_id': self.user_id
                }
            )

        # Leave room group
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )

    async def receive(self, text_data):
        # Validate message size
        if len(text_data) > MAX_MESSAGE_SIZE:
            logger.warning(f"Oversized message rejected ({len(text_data)} bytes) from {self.user_id}")
            return

        try:
            data = json.loads(text_data)
            event_type = data.get('type')
            payload = data.get('data', {})

            # Heartbeat: respond to ping immediately
            if event_type == 'ping':
                await self.send(text_data=json.dumps({'type': 'pong'}))
                return

            if event_type == 'join-room':
                await self.handle_join_room(payload)
            elif event_type == 'video-off':
                await self.handle_video_off(payload)
            elif event_type == 'on-the-video':
                await self.handle_video_on(payload)
            elif event_type == 'screen-share-off':
                await self.handle_screen_share_off(payload)
            elif event_type == 'new-chat':
                await self.handle_new_chat(payload)
            elif event_type == 'recording-started':
                await self.handle_recording_started(payload)
            elif event_type == 'recording-stopped':
                await self.handle_recording_stopped(payload)
            elif event_type == 'alert':
                await self.handle_alert(payload)
            elif event_type == 'alert-response':
                await self.handle_alert_response(payload)
            elif event_type == 'mute-all':
                await self.handle_mute_all(payload)
            elif event_type == 'kick-user':
                await self.handle_kick_user(payload)
            elif event_type == 'share-info':
                await self.handle_share_info(payload)
            elif event_type == 'request-info':
                await self.handle_request_info(payload)
            elif event_type == 'end-meeting':
                await self.handle_end_meeting(payload)

        except json.JSONDecodeError:
            logger.warning(f"Invalid JSON received from {self.user_id}")
        except Exception as e:
            logger.exception(f"Error handling message from {self.user_id}: {e}")

    # Event Handlers
    async def handle_join_room(self, payload):
        user_id = payload.get('user_id')
        username = payload.get('username', '')
        is_moderator = payload.get('is_moderator', False)
        self.user_id = user_id

        # Notify others that new user joined (include username)
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'new_user_joined',
                'user_id': user_id,
                'username': username,
                'is_moderator': is_moderator,
                'sender_channel': self.channel_name
            }
        )

    async def handle_video_off(self, payload):
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'video_off',
                'user_id': payload.get('user_id', self.user_id),
                'sender_channel': self.channel_name
            }
        )

    async def handle_video_on(self, payload):
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'video_on',
                'user_id': payload.get('user_id', self.user_id),
                'sender_channel': self.channel_name
            }
        )

    async def handle_screen_share_off(self, payload):
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'screen_share_off',
                'user_id': payload.get('user_id', self.user_id),
                'sender_channel': self.channel_name
            }
        )

    async def handle_new_chat(self, payload):
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'new_message',
                'message': payload.get('message'),
                'user_id': payload.get('user_id', self.user_id),
                'sender_channel': self.channel_name
            }
        )

    async def handle_recording_started(self, payload):
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'recording_started',
                'user_id': payload.get('user_id', self.user_id),
                'sender_channel': self.channel_name
            }
        )

    async def handle_recording_stopped(self, payload):
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'recording_stopped',
                'user_id': payload.get('user_id', self.user_id),
                'sender_channel': self.channel_name
            }
        )

    async def handle_alert(self, payload):
        """Host approval request from pending user"""
        author_id = payload.get('author_id')
        requesting_user_id = payload.get('user_id')
        requesting_username = payload.get('username')

        # Send alert to the author (host)
        await self.channel_layer.group_send(
            f'user_{author_id}',
            {
                'type': 'alert_request',
                'user_id': requesting_user_id,
                'username': requesting_username,
                'room_id': self.room_id
            }
        )

    async def handle_alert_response(self, payload):
        """Host's response to approval request"""
        approved = payload.get('approved')
        requesting_user_id = payload.get('requesting_user_id')

        logger.info(f"Alert response: approved={approved}, user_id={requesting_user_id}")

        if approved:
            # Create meeting packet asynchronously via Celery task
            from .tasks import create_meeting_packet
            create_meeting_packet.delay(requesting_user_id, self.room_id)

        # Send response to the requesting user
        await self.channel_layer.group_send(
            f'user_{requesting_user_id}',
            {
                'type': 'alert_response',
                'approved': approved,
                'room_id': self.room_id
            }
        )

    async def handle_mute_all(self, payload):
        """Moderator mutes all participants"""
        moderator_id = payload.get('moderatorId')

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'mute_all',
                'moderator_id': moderator_id,
                'sender_channel': self.channel_name
            }
        )

    async def handle_kick_user(self, payload):
        """Moderator kicks a user from the meeting"""
        moderator_id = payload.get('moderatorId')
        target_user_id = payload.get('targetUserId')

        # Send kick to the specific user via their user group
        await self.channel_layer.group_send(
            f'user_{target_user_id}',
            {
                'type': 'kicked',
                'moderator_id': moderator_id
            }
        )

        # Notify all users that someone was kicked
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'user_kicked',
                'target_user_id': target_user_id,
                'moderator_id': moderator_id,
                'sender_channel': self.channel_name
            }
        )

    async def handle_share_info(self, payload):
        """User shares their info (username, etc.)"""
        user_id = payload.get('user_id')
        username = payload.get('username')
        is_moderator = payload.get('is_moderator', False)

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'share_info',
                'user_id': user_id,
                'username': username,
                'is_moderator': is_moderator,
                'sender_channel': self.channel_name
            }
        )

    async def handle_request_info(self, payload):
        """Request info from all participants"""
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'request_info',
                'sender_channel': self.channel_name
            }
        )

    async def handle_end_meeting(self, payload):
        """Moderator ends the meeting for all participants"""
        moderator_id = payload.get('moderator_id')
        logger.info(f"Meeting {self.room_id} ended by moderator {moderator_id}")

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'meeting_ended',
                'moderator_id': moderator_id,
                'sender_channel': self.channel_name
            }
        )

    # Message senders (called by channel_layer.group_send)
    async def new_user_joined(self, event):
        if self.channel_name != event['sender_channel']:
            await self.send(text_data=json.dumps({
                'type': 'newuserjoined',
                'user_id': event['user_id'],
                'username': event.get('username', ''),
                'is_moderator': event.get('is_moderator', False)
            }))

    async def user_disconnected(self, event):
        await self.send(text_data=json.dumps({
            'type': 'user-disconnected',
            'user_id': event['user_id']
        }))

    async def video_off(self, event):
        if self.channel_name != event['sender_channel']:
            await self.send(text_data=json.dumps({
                'type': 'off-the-video',
                'user_id': event['user_id']
            }))

    async def video_on(self, event):
        if self.channel_name != event['sender_channel']:
            await self.send(text_data=json.dumps({
                'type': 'on-the-video',
                'user_id': event['user_id']
            }))

    async def screen_share_off(self, event):
        if self.channel_name != event['sender_channel']:
            await self.send(text_data=json.dumps({
                'type': 'screen-share-off',
                'user_id': event['user_id']
            }))

    async def new_message(self, event):
        if self.channel_name != event['sender_channel']:
            await self.send(text_data=json.dumps({
                'type': 'newmessage',
                'message': event['message']
            }))

    async def recording_started(self, event):
        if self.channel_name != event['sender_channel']:
            await self.send(text_data=json.dumps({
                'type': 'recording-started',
                'user_id': event['user_id']
            }))

    async def recording_stopped(self, event):
        if self.channel_name != event['sender_channel']:
            await self.send(text_data=json.dumps({
                'type': 'recording-stopped',
                'user_id': event['user_id']
            }))

    async def alert_request(self, event):
        await self.send(text_data=json.dumps({
            'type': 'alert',
            'user_id': event['user_id'],
            'username': event['username']
        }))

    async def alert_response(self, event):
        await self.send(text_data=json.dumps({
            'type': 'alert-response',
            'approved': event['approved'],
            'room_id': event['room_id']
        }))

    async def mute_all(self, event):
        if self.channel_name != event['sender_channel']:
            await self.send(text_data=json.dumps({
                'type': 'mute-all',
                'moderator_id': event['moderator_id']
            }))

    async def kicked(self, event):
        await self.send(text_data=json.dumps({
            'type': 'kicked',
            'moderator_id': event['moderator_id']
        }))

    async def user_kicked(self, event):
        await self.send(text_data=json.dumps({
            'type': 'user-kicked',
            'targetUserId': event['target_user_id'],
            'moderator_id': event['moderator_id']
        }))

    async def share_info(self, event):
        if self.channel_name != event['sender_channel']:
            await self.send(text_data=json.dumps({
                'type': 'share-info',
                'user_id': event['user_id'],
                'username': event['username'],
                'is_moderator': event.get('is_moderator', False)
            }))

    async def request_info(self, event):
        if self.channel_name != event['sender_channel']:
            await self.send(text_data=json.dumps({
                'type': 'request-info'
            }))

    async def meeting_ended(self, event):
        if self.channel_name != event['sender_channel']:
            await self.send(text_data=json.dumps({
                'type': 'meeting-ended',
                'moderator_id': event['moderator_id']
            }))


class UserConsumer(AsyncWebsocketConsumer):
    """Consumer for user-specific notifications (like host approval alerts)"""

    async def connect(self):
        if self.scope['user'].is_authenticated:
            self.user_id = str(self.scope['user'].id)
            self.user_group_name = f'user_{self.user_id}'

            await self.channel_layer.group_add(
                self.user_group_name,
                self.channel_name
            )
            await self.accept()
            logger.debug(f"UserConsumer: Authenticated user {self.user_id} connected")
        else:
            # Allow anonymous connections for guests
            await self.accept()
            self.user_id = None
            self.user_group_name = None
            logger.debug("UserConsumer: Anonymous user connected, waiting for registration")

    async def receive(self, text_data):
        """Handle messages from the client"""
        if len(text_data) > MAX_MESSAGE_SIZE:
            return

        try:
            data = json.loads(text_data)

            # Heartbeat: respond to ping immediately
            if data.get('type') == 'ping':
                await self.send(text_data=json.dumps({'type': 'pong'}))
                return

            # Allow guests to register their ID
            if data.get('type') == 'register':
                guest_id = data.get('user_id')
                if guest_id and guest_id.startswith('guest_'):
                    self.user_id = guest_id
                    self.user_group_name = f'user_{self.user_id}'
                    await self.channel_layer.group_add(
                        self.user_group_name,
                        self.channel_name
                    )
                    logger.debug(f"Guest {guest_id} registered for notifications")
                    await self.send(text_data=json.dumps({
                        'type': 'registered',
                        'user_id': guest_id
                    }))
        except json.JSONDecodeError:
            pass

    async def disconnect(self, close_code):
        if hasattr(self, 'user_group_name') and self.user_group_name:
            await self.channel_layer.group_discard(
                self.user_group_name,
                self.channel_name
            )

    async def alert_request(self, event):
        logger.debug(f"UserConsumer: Received alert_request for user {self.user_id}")
        await self.send(text_data=json.dumps({
            'type': 'alert',
            'user_id': event['user_id'],
            'username': event['username'],
            'room_id': event['room_id']
        }))

    async def alert_response(self, event):
        logger.debug(f"UserConsumer: Sending alert_response to user {self.user_id}: approved={event['approved']}")
        await self.send(text_data=json.dumps({
            'type': 'alert-response',
            'approved': event['approved'],
            'room_id': event['room_id']
        }))

    async def kicked(self, event):
        """Forward kick notification to the user's WebSocket"""
        await self.send(text_data=json.dumps({
            'type': 'kicked',
            'moderator_id': event['moderator_id']
        }))
