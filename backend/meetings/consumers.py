import json
import time
import asyncio
import logging
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

logger = logging.getLogger(__name__)

# Maximum message size in bytes (64 KB)
MAX_MESSAGE_SIZE = 65536
# Fallback maximum connections per room (when plan lookup fails)
MAX_ROOM_CONNECTIONS_FALLBACK = 500


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
        self._duration_task = None

        # Validate room exists and user has access
        room_access = await self._check_room_access()
        if not room_access:
            logger.warning(f"WebSocket connection denied: room {self.room_id} not found or access denied")
            await self.close(code=4004)  # Not found / forbidden
            return

        # Enforce plan-based participant limit via Redis cache
        max_participants = await self._get_room_participant_limit()
        room_count_key = f'ws:room:count:{self.room_id}'
        try:
            from django.core.cache import cache
            try:
                count = cache.incr(room_count_key)
            except ValueError:
                cache.set(room_count_key, 1, 7200)  # 2h TTL
                count = 1

            if count > max_participants:
                cache.decr(room_count_key)
                logger.warning(f"Room {self.room_id} at plan capacity ({max_participants})")
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

        # Start duration limit enforcement if applicable
        duration_limit = await self._get_duration_limit()
        if duration_limit:
            try:
                from django.core.cache import cache
                start_key = f'ws:room:start:{self.room_id}'
                if not cache.get(start_key):
                    cache.set(start_key, time.time(), duration_limit + 300)
                self._duration_task = asyncio.ensure_future(
                    self._check_duration_limit(duration_limit)
                )
            except Exception:
                pass

    @database_sync_to_async
    def _check_room_access(self):
        """
        Validate that the room exists and the user has access.
        Returns True if access is granted, False otherwise.
        """
        from meetings.models import Meeting, PersonalRoom

        # Check if room exists (Meeting or PersonalRoom)
        room_exists = False
        try:
            Meeting.objects.get(room_id=self.room_id)
            room_exists = True
        except Meeting.DoesNotExist:
            try:
                PersonalRoom.objects.get(room_id=self.room_id)
                room_exists = True
            except PersonalRoom.DoesNotExist:
                pass

        if not room_exists:
            return False

        # For unauthenticated users (guests), allow access if room exists
        # (they came via a valid token link which rendered the room page)
        if not self.user_id:
            return True

        # For authenticated users, room exists check is sufficient
        # The HTTP view already validated their access before rendering room.html
        return True

    @database_sync_to_async
    def _get_room_participant_limit(self):
        """Look up the plan's max_participants for this room's org."""
        from meetings.models import Meeting, PersonalRoom
        try:
            from billing.plan_limits import get_plan_limits
        except ImportError:
            return MAX_ROOM_CONNECTIONS_FALLBACK

        org = None
        try:
            meeting = Meeting.objects.select_related('organization').get(room_id=self.room_id)
            org = meeting.organization
        except Meeting.DoesNotExist:
            try:
                room = PersonalRoom.objects.select_related('organization').get(room_id=self.room_id)
                org = room.organization
            except PersonalRoom.DoesNotExist:
                pass

        if org:
            limits = get_plan_limits(org)
            return limits.max_participants
        return MAX_ROOM_CONNECTIONS_FALLBACK

    @database_sync_to_async
    def _get_duration_limit(self):
        """Returns duration limit in seconds, or None for unlimited."""
        from meetings.models import Meeting, PersonalRoom
        try:
            from billing.plan_limits import get_plan_limits
        except ImportError:
            return None

        org = None
        try:
            meeting = Meeting.objects.select_related('organization').get(room_id=self.room_id)
            org = meeting.organization
        except Meeting.DoesNotExist:
            try:
                room = PersonalRoom.objects.select_related('organization').get(room_id=self.room_id)
                org = room.organization
            except PersonalRoom.DoesNotExist:
                pass

        if org:
            limits = get_plan_limits(org)
            return limits.get_duration_limit_seconds()
        return None

    async def _check_duration_limit(self, limit_seconds):
        """Periodically check if meeting has exceeded duration limit."""
        try:
            while True:
                await asyncio.sleep(60)
                from django.core.cache import cache
                start_key = f'ws:room:start:{self.room_id}'
                start_time = cache.get(start_key)
                if not start_time:
                    break

                elapsed = time.time() - start_time
                remaining = limit_seconds - elapsed

                if 240 < remaining <= 300:
                    await self.channel_layer.group_send(
                        self.room_group_name,
                        {
                            'type': 'duration_warning',
                            'minutes_remaining': int(remaining / 60),
                        }
                    )

                if elapsed >= limit_seconds:
                    await self.channel_layer.group_send(
                        self.room_group_name,
                        {
                            'type': 'meeting_duration_exceeded',
                            'message': 'Meeting duration limit reached for your plan.',
                        }
                    )
                    break
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.exception(f"Error in duration check for room {self.room_id}: {e}")

    async def disconnect(self, close_code):
        # Cancel duration check if running
        if hasattr(self, '_duration_task') and self._duration_task:
            self._duration_task.cancel()

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
            elif event_type == 'mute-status':
                await self.handle_mute_status(payload)
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
            # Breakout room events
            elif event_type == 'create-breakout':
                await self.handle_create_breakout(payload)
            elif event_type == 'assign-to-breakout':
                await self.handle_assign_to_breakout(payload)
            elif event_type == 'join-breakout':
                await self.handle_join_breakout(payload)
            elif event_type == 'return-to-main':
                await self.handle_return_to_main(payload)
            elif event_type == 'close-breakouts':
                await self.handle_close_breakouts(payload)
            elif event_type == 'broadcast-to-breakouts':
                await self.handle_broadcast_to_breakouts(payload)

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
        import html
        # Sanitize message to prevent XSS - escape HTML entities
        raw_message = payload.get('message', '')
        if raw_message:
            # Limit message length
            raw_message = raw_message[:2000]
            # Escape HTML to prevent XSS
            sanitized_message = html.escape(str(raw_message))
        else:
            sanitized_message = ''

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'new_message',
                'message': sanitized_message,
                'user_id': payload.get('user_id', self.user_id),
                'username': html.escape(str(payload.get('username', ''))[:50]),
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

        # Send alert to the author (host) via user-specific channel
        await self.channel_layer.group_send(
            f'user_{author_id}',
            {
                'type': 'alert_request',
                'user_id': requesting_user_id,
                'username': requesting_username,
                'room_id': self.room_id
            }
        )

        # Also broadcast to the room so moderators who aren't authenticated
        # (e.g. accessing via moderator token link) still receive the alert
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'join_request',
                'user_id': requesting_user_id,
                'username': requesting_username,
            }
        )

    async def handle_alert_response(self, payload):
        """Host's response to approval request"""
        approved = payload.get('approved')
        requesting_user_id = payload.get('requesting_user_id')

        logger.info(f"Alert response: approved={approved}, user_id={requesting_user_id}")

        if approved:
            # Create meeting packet asynchronously via Celery task
            # Wrapped in try/except so a Celery failure doesn't block the response
            try:
                from .tasks import create_meeting_packet
                create_meeting_packet.delay(requesting_user_id, self.room_id)
            except Exception as e:
                logger.exception(f"Failed to dispatch meeting packet task: {e}")

        # Always send response to the requesting user, regardless of task creation
        # Send via user-specific channel
        await self.channel_layer.group_send(
            f'user_{requesting_user_id}',
            {
                'type': 'alert_response',
                'approved': approved,
                'room_id': self.room_id
            }
        )

        # Also broadcast to room so pending user's room socket receives it
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'join_response',
                'user_id': requesting_user_id,
                'approved': approved,
            }
        )

    async def handle_mute_status(self, payload):
        """User broadcasts their mute/unmute state"""
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'user_mute_status',
                'user_id': payload.get('user_id', self.user_id),
                'is_muted': payload.get('is_muted', False),
                'sender_channel': self.channel_name
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

    # ========== Breakout Room Handlers ==========

    @database_sync_to_async
    def _is_moderator(self, user_id):
        """Check if the given user_id is a moderator for this room."""
        from meetings.models import Meeting, PersonalRoom

        if not user_id:
            return False

        try:
            # For PersonalRoom, the owner is the moderator
            room = PersonalRoom.objects.select_related('user').get(room_id=self.room_id)
            return str(room.user_id) == str(user_id)
        except PersonalRoom.DoesNotExist:
            pass

        try:
            # For Meeting, the author is the moderator
            meeting = Meeting.objects.get(room_id=self.room_id)
            return str(meeting.author_id) == str(user_id)
        except Meeting.DoesNotExist:
            pass

        return False

    @database_sync_to_async
    def _can_use_breakout_rooms(self):
        """Check if the organization's plan allows breakout rooms."""
        from meetings.models import Meeting, PersonalRoom
        try:
            from billing.plan_limits import get_plan_limits
        except ImportError:
            return False

        org = None
        try:
            meeting = Meeting.objects.select_related('organization').get(room_id=self.room_id)
            org = meeting.organization
        except Meeting.DoesNotExist:
            try:
                room = PersonalRoom.objects.select_related('organization').get(room_id=self.room_id)
                org = room.organization
            except PersonalRoom.DoesNotExist:
                pass

        if org:
            limits = get_plan_limits(org)
            return limits.can_use_breakout_rooms()
        return False

    @database_sync_to_async
    def _create_breakout_room_db(self, name):
        """Create breakout room in database and return its ID."""
        from meetings.models import BreakoutRoom, PersonalRoom, Meeting

        parent_room = None
        parent_meeting = None
        try:
            parent_room = PersonalRoom.objects.get(room_id=self.room_id)
        except PersonalRoom.DoesNotExist:
            try:
                parent_meeting = Meeting.objects.get(room_id=self.room_id)
            except Meeting.DoesNotExist:
                return None

        breakout = BreakoutRoom.objects.create(
            parent_room=parent_room,
            parent_meeting=parent_meeting,
            name=name,
        )
        return str(breakout.room_id)

    @database_sync_to_async
    def _close_breakout_rooms_db(self):
        """Close all active breakout rooms for the current meeting."""
        from meetings.models import BreakoutRoom, PersonalRoom, Meeting
        from django.utils import timezone

        try:
            parent_room = PersonalRoom.objects.get(room_id=self.room_id)
            BreakoutRoom.objects.filter(parent_room=parent_room, is_active=True).update(
                is_active=False, closed_at=timezone.now()
            )
        except PersonalRoom.DoesNotExist:
            try:
                parent_meeting = Meeting.objects.get(room_id=self.room_id)
                BreakoutRoom.objects.filter(parent_meeting=parent_meeting, is_active=True).update(
                    is_active=False, closed_at=timezone.now()
                )
            except Meeting.DoesNotExist:
                pass

    async def handle_create_breakout(self, payload):
        """Moderator creates breakout rooms."""
        moderator_id = payload.get('moderator_id')

        # Verify the sender is actually a moderator
        if not await self._is_moderator(moderator_id):
            await self.send(text_data=json.dumps({
                'type': 'breakout-error',
                'message': 'Only moderators can create breakout rooms.'
            }))
            return

        if not await self._can_use_breakout_rooms():
            await self.send(text_data=json.dumps({
                'type': 'breakout-error',
                'message': 'Breakout rooms require a Business plan.'
            }))
            return

        rooms = payload.get('rooms', [])  # List of room names like ["Room 1", "Room 2"]

        # Validate breakout room count (max 10)
        if not isinstance(rooms, list) or len(rooms) > 10:
            await self.send(text_data=json.dumps({
                'type': 'breakout-error',
                'message': 'Maximum of 10 breakout rooms allowed.'
            }))
            return

        created_rooms = []
        for room_name in rooms:
            breakout_room_id = await self._create_breakout_room_db(room_name)
            if breakout_room_id:
                created_rooms.append({
                    'name': room_name,
                    'breakout_id': breakout_room_id
                })
                # Store in Redis for quick lookup
                from django.core.cache import cache
                cache.set(f'breakout:rooms:{self.room_id}:{breakout_room_id}', room_name, 7200)

        logger.info(f"Created {len(created_rooms)} breakout rooms for {self.room_id}")

        # Broadcast to all participants that breakout rooms are available
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'breakout_rooms_created',
                'rooms': created_rooms,
                'moderator_id': moderator_id,
                'sender_channel': self.channel_name
            }
        )

    async def handle_assign_to_breakout(self, payload):
        """Moderator assigns a participant to a breakout room."""
        moderator_id = payload.get('moderator_id')

        # Verify the sender is actually a moderator
        if not await self._is_moderator(moderator_id):
            await self.send(text_data=json.dumps({
                'type': 'breakout-error',
                'message': 'Only moderators can assign participants to breakout rooms.'
            }))
            return

        target_user_id = payload.get('user_id')
        breakout_id = payload.get('breakout_id')
        breakout_name = payload.get('breakout_name', '')

        # Store assignment in Redis
        from django.core.cache import cache
        cache.set(f'breakout:assignment:{self.room_id}:{target_user_id}', breakout_id, 7200)

        logger.info(f"Assigned {target_user_id} to breakout {breakout_id} in room {self.room_id}")

        # Notify the assigned user
        await self.channel_layer.group_send(
            f'user_{target_user_id}',
            {
                'type': 'breakout_assigned',
                'breakout_id': breakout_id,
                'breakout_name': breakout_name,
                'main_room_id': self.room_id,
            }
        )

        # Also broadcast to main room so UI updates
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'user_assigned_breakout',
                'user_id': target_user_id,
                'breakout_id': breakout_id,
                'breakout_name': breakout_name,
                'sender_channel': self.channel_name
            }
        )

    async def handle_join_breakout(self, payload):
        """User joins their assigned breakout room."""
        # Verify plan allows breakout rooms
        if not await self._can_use_breakout_rooms():
            await self.send(text_data=json.dumps({
                'type': 'breakout-error',
                'message': 'Breakout rooms require a Business plan.'
            }))
            return

        breakout_id = payload.get('breakout_id')
        user_id = payload.get('user_id', self.user_id)
        username = payload.get('username', '')

        # Verify user was actually assigned to this breakout room
        from django.core.cache import cache
        assigned_breakout = cache.get(f'breakout:assignment:{self.room_id}:{user_id}')
        if assigned_breakout != breakout_id:
            await self.send(text_data=json.dumps({
                'type': 'breakout-error',
                'message': 'You are not assigned to this breakout room.'
            }))
            return

        # Join breakout group
        breakout_group = f'breakout_{breakout_id}'
        await self.channel_layer.group_add(breakout_group, self.channel_name)

        logger.info(f"User {user_id} joined breakout {breakout_id}")

        # Notify breakout room
        await self.channel_layer.group_send(
            breakout_group,
            {
                'type': 'breakout_user_joined',
                'user_id': user_id,
                'username': username,
                'breakout_id': breakout_id,
                'sender_channel': self.channel_name
            }
        )

        # Notify main room that user moved
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'user_moved_to_breakout',
                'user_id': user_id,
                'breakout_id': breakout_id,
                'sender_channel': self.channel_name
            }
        )

    async def handle_return_to_main(self, payload):
        """User returns from breakout room to main room."""
        breakout_id = payload.get('breakout_id')
        user_id = payload.get('user_id', self.user_id)
        username = payload.get('username', '')

        # Leave breakout group
        breakout_group = f'breakout_{breakout_id}'
        await self.channel_layer.group_discard(breakout_group, self.channel_name)

        # Clear assignment from Redis
        from django.core.cache import cache
        cache.delete(f'breakout:assignment:{self.room_id}:{user_id}')

        logger.info(f"User {user_id} returned to main room from breakout {breakout_id}")

        # Notify breakout room
        await self.channel_layer.group_send(
            breakout_group,
            {
                'type': 'breakout_user_left',
                'user_id': user_id,
                'breakout_id': breakout_id,
            }
        )

        # Notify main room that user returned
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'user_returned_from_breakout',
                'user_id': user_id,
                'username': username,
                'breakout_id': breakout_id,
                'sender_channel': self.channel_name
            }
        )

    async def handle_close_breakouts(self, payload):
        """Moderator closes all breakout rooms."""
        moderator_id = payload.get('moderator_id')

        # Verify the sender is actually a moderator
        if not await self._is_moderator(moderator_id):
            await self.send(text_data=json.dumps({
                'type': 'breakout-error',
                'message': 'Only moderators can close breakout rooms.'
            }))
            return

        await self._close_breakout_rooms_db()

        logger.info(f"Breakout rooms closed for {self.room_id} by {moderator_id}")

        # Broadcast to everyone to return to main
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'breakouts_closed',
                'moderator_id': moderator_id,
                'sender_channel': self.channel_name
            }
        )

    async def handle_broadcast_to_breakouts(self, payload):
        """Moderator broadcasts a message to all breakout rooms."""
        moderator_id = payload.get('moderator_id')

        # Verify the sender is actually a moderator
        if not await self._is_moderator(moderator_id):
            await self.send(text_data=json.dumps({
                'type': 'breakout-error',
                'message': 'Only moderators can broadcast to breakout rooms.'
            }))
            return

        message = payload.get('message', '')

        # Broadcast to main room (this will include breakout participants still connected)
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'breakout_broadcast',
                'message': message,
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
                'message': event['message'],
                'user_id': event.get('user_id', ''),
                'username': event.get('username', '')
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

    async def join_request(self, event):
        """Forward join request to room members (for moderators not on user socket)"""
        await self.send(text_data=json.dumps({
            'type': 'join-request',
            'user_id': event['user_id'],
            'username': event['username'],
        }))

    async def join_response(self, event):
        """Forward join response to room members (for pending user's room socket)"""
        await self.send(text_data=json.dumps({
            'type': 'join-response',
            'user_id': event['user_id'],
            'approved': event['approved'],
        }))

    async def user_mute_status(self, event):
        await self.send(text_data=json.dumps({
            'type': 'user-mute-status',
            'user_id': event['user_id'],
            'is_muted': event['is_muted']
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

    async def duration_warning(self, event):
        await self.send(text_data=json.dumps({
            'type': 'duration-warning',
            'minutes_remaining': event['minutes_remaining']
        }))

    async def meeting_duration_exceeded(self, event):
        await self.send(text_data=json.dumps({
            'type': 'meeting-duration-exceeded',
            'message': event['message']
        }))

    # Breakout room message senders
    async def breakout_rooms_created(self, event):
        await self.send(text_data=json.dumps({
            'type': 'breakout-rooms-created',
            'rooms': event['rooms'],
            'moderator_id': event['moderator_id']
        }))

    async def breakout_assigned(self, event):
        await self.send(text_data=json.dumps({
            'type': 'breakout-assigned',
            'breakout_id': event['breakout_id'],
            'breakout_name': event['breakout_name'],
            'main_room_id': event['main_room_id']
        }))

    async def user_assigned_breakout(self, event):
        await self.send(text_data=json.dumps({
            'type': 'user-assigned-breakout',
            'user_id': event['user_id'],
            'breakout_id': event['breakout_id'],
            'breakout_name': event['breakout_name']
        }))

    async def breakout_user_joined(self, event):
        if self.channel_name != event.get('sender_channel'):
            await self.send(text_data=json.dumps({
                'type': 'breakout-user-joined',
                'user_id': event['user_id'],
                'username': event['username'],
                'breakout_id': event['breakout_id']
            }))

    async def user_moved_to_breakout(self, event):
        await self.send(text_data=json.dumps({
            'type': 'user-moved-to-breakout',
            'user_id': event['user_id'],
            'breakout_id': event['breakout_id']
        }))

    async def breakout_user_left(self, event):
        await self.send(text_data=json.dumps({
            'type': 'breakout-user-left',
            'user_id': event['user_id'],
            'breakout_id': event['breakout_id']
        }))

    async def user_returned_from_breakout(self, event):
        await self.send(text_data=json.dumps({
            'type': 'user-returned-from-breakout',
            'user_id': event['user_id'],
            'username': event['username'],
            'breakout_id': event['breakout_id']
        }))

    async def breakouts_closed(self, event):
        await self.send(text_data=json.dumps({
            'type': 'breakouts-closed',
            'moderator_id': event['moderator_id']
        }))

    async def breakout_broadcast(self, event):
        await self.send(text_data=json.dumps({
            'type': 'breakout-broadcast',
            'message': event['message'],
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

    async def breakout_assigned(self, event):
        """Forward breakout room assignment to the user"""
        await self.send(text_data=json.dumps({
            'type': 'breakout-assigned',
            'breakout_id': event['breakout_id'],
            'breakout_name': event['breakout_name'],
            'main_room_id': event['main_room_id']
        }))
