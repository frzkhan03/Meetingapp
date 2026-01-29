import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth.models import User
from .models import UserMeetingPacket, Meeting


class RoomConsumer(AsyncWebsocketConsumer):
    # Track active users per room
    room_users = {}  # {room_id: {user_id: channel_name}}

    async def connect(self):
        self.room_id = self.scope['url_route']['kwargs']['room_id']
        self.room_group_name = f'room_{self.room_id}'
        self.user_id = self.scope.get('user_id', str(self.scope['user'].id) if self.scope['user'].is_authenticated else None)

        # Join room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        # Initialize room users dict if needed
        if self.room_id not in RoomConsumer.room_users:
            RoomConsumer.room_users[self.room_id] = {}

        await self.accept()

    async def disconnect(self, close_code):
        # Remove user from tracking
        if self.room_id in RoomConsumer.room_users and hasattr(self, 'user_id') and self.user_id:
            if self.user_id in RoomConsumer.room_users[self.room_id]:
                del RoomConsumer.room_users[self.room_id][self.user_id]

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
        try:
            data = json.loads(text_data)
            event_type = data.get('type')
            payload = data.get('data', {})

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
            elif event_type == 'whiteboardshared':
                await self.handle_whiteboard_shared(payload)
            elif event_type == 'whiteboardclosed':
                await self.handle_whiteboard_closed(payload)
            elif event_type == 'mouseup':
                await self.handle_mouse_event('mouseup', payload)
            elif event_type == 'mousedown':
                await self.handle_mouse_event('mousedown', payload)
            elif event_type == 'mousemove':
                await self.handle_mouse_event('mousemove', payload)
            elif event_type == 'colorchange':
                await self.handle_color_change(payload)
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
            print(f"Invalid JSON received: {text_data}")
        except Exception as e:
            print(f"Error handling message: {e}")

    # Event Handlers
    async def handle_join_room(self, payload):
        user_id = payload.get('user_id')
        username = payload.get('username', '')
        is_moderator = payload.get('is_moderator', False)
        self.user_id = user_id

        # Track user in room
        RoomConsumer.room_users[self.room_id][user_id] = self.channel_name

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

    async def handle_whiteboard_shared(self, payload):
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'whiteboard_shared',
                'sender_channel': self.channel_name
            }
        )

    async def handle_whiteboard_closed(self, payload):
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'whiteboard_closed',
                'sender_channel': self.channel_name
            }
        )

    async def handle_mouse_event(self, event_type, payload):
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'mouse_event',
                'event_type': event_type,
                'event_data': payload,
                'sender_channel': self.channel_name
            }
        )

    async def handle_color_change(self, payload):
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'color_change',
                'color': payload.get('color'),
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

        print(f"Alert response: approved={approved}, user_id={requesting_user_id}")

        if approved:
            # Create meeting packet to allow user access
            await self.create_meeting_packet(requesting_user_id)

        # Send response to the requesting user
        print(f"Sending alert-response to user_{requesting_user_id}")
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

        # Broadcast mute-all to all participants
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

        # Get the target user's channel
        if self.room_id in RoomConsumer.room_users:
            target_channel = RoomConsumer.room_users[self.room_id].get(target_user_id)

            if target_channel:
                # Send kick notification to the target user
                await self.channel_layer.send(
                    target_channel,
                    {
                        'type': 'kicked',
                        'moderator_id': moderator_id
                    }
                )

                # Remove user from room tracking
                del RoomConsumer.room_users[self.room_id][target_user_id]

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
        print(f"Meeting ended by moderator {moderator_id}")

        # Broadcast meeting-ended to all participants
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'meeting_ended',
                'moderator_id': moderator_id,
                'sender_channel': self.channel_name
            }
        )

    @database_sync_to_async
    def create_meeting_packet(self, user_id):
        try:
            # Check if it's a guest user (id starts with "guest_")
            if str(user_id).startswith('guest_'):
                # For guests, we don't create a packet - just allow them to join
                # The approval is handled in real-time via WebSocket
                return True

            user = User.objects.get(id=user_id)

            # Try to get meeting first, if not found, try personal room
            try:
                meeting = Meeting.objects.get(room_id=self.room_id)
                UserMeetingPacket.objects.get_or_create(
                    user=user,
                    room_id=self.room_id,
                    defaults={
                        'author': meeting.author,
                        'meeting': meeting,
                        'meeting_name': meeting.name
                    }
                )
            except Meeting.DoesNotExist:
                # It might be a personal room
                from .models import PersonalRoom
                personal_room = PersonalRoom.objects.get(room_id=self.room_id)
                UserMeetingPacket.objects.get_or_create(
                    user=user,
                    room_id=self.room_id,
                    defaults={
                        'author': personal_room.user,
                        'meeting': None,
                        'meeting_name': personal_room.room_name
                    }
                )
        except Exception as e:
            print(f"Error creating meeting packet: {e}")

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

    async def whiteboard_shared(self, event):
        if self.channel_name != event['sender_channel']:
            await self.send(text_data=json.dumps({
                'type': 'whiteboardshared'
            }))

    async def whiteboard_closed(self, event):
        if self.channel_name != event['sender_channel']:
            await self.send(text_data=json.dumps({
                'type': 'whiteboardclosed'
            }))

    async def mouse_event(self, event):
        if self.channel_name != event['sender_channel']:
            await self.send(text_data=json.dumps({
                'type': event['event_type'],
                'data': event['event_data']
            }))

    async def color_change(self, event):
        if self.channel_name != event['sender_channel']:
            await self.send(text_data=json.dumps({
                'type': 'colorchange',
                'color': event['color']
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
        """Notify all participants that moderator muted everyone"""
        if self.channel_name != event['sender_channel']:
            await self.send(text_data=json.dumps({
                'type': 'mute-all',
                'moderator_id': event['moderator_id']
            }))

    async def kicked(self, event):
        """Notify user that they have been kicked"""
        await self.send(text_data=json.dumps({
            'type': 'kicked',
            'moderator_id': event['moderator_id']
        }))

    async def user_kicked(self, event):
        """Notify all users that someone was kicked"""
        await self.send(text_data=json.dumps({
            'type': 'user-kicked',
            'targetUserId': event['target_user_id'],
            'moderator_id': event['moderator_id']
        }))

    async def share_info(self, event):
        """Share participant info"""
        if self.channel_name != event['sender_channel']:
            await self.send(text_data=json.dumps({
                'type': 'share-info',
                'user_id': event['user_id'],
                'username': event['username'],
                'is_moderator': event.get('is_moderator', False)
            }))

    async def request_info(self, event):
        """Request participants to share their info"""
        if self.channel_name != event['sender_channel']:
            await self.send(text_data=json.dumps({
                'type': 'request-info'
            }))

    async def meeting_ended(self, event):
        """Notify all participants that meeting has ended"""
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
            print(f"UserConsumer: Authenticated user {self.user_id} connected")
        else:
            # Allow anonymous connections for guests
            # They will provide their guest ID via message
            await self.accept()
            self.user_id = None
            self.user_group_name = None
            print("UserConsumer: Anonymous user connected, waiting for registration")

    async def receive(self, text_data):
        """Handle messages from the client"""
        try:
            data = json.loads(text_data)
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
                    print(f"Guest {guest_id} registered for notifications")
                    # Send confirmation
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
        print(f"UserConsumer: Received alert_request for user {self.user_id}")
        await self.send(text_data=json.dumps({
            'type': 'alert',
            'user_id': event['user_id'],
            'username': event['username'],
            'room_id': event['room_id']
        }))

    async def alert_response(self, event):
        print(f"UserConsumer: Sending alert_response to user {self.user_id}: approved={event['approved']}")
        await self.send(text_data=json.dumps({
            'type': 'alert-response',
            'approved': event['approved'],
            'room_id': event['room_id']
        }))
