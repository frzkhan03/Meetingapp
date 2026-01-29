import logging
from celery import shared_task
from django.contrib.auth.models import User
from .models import Meeting, UserMeetingPacket, PersonalRoom

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=5)
def create_meeting_packet(self, user_id, room_id):
    """
    Create a meeting packet granting a user access to a room.
    Runs as a Celery task to keep DB operations off the WebSocket event loop.
    """
    try:
        if str(user_id).startswith('guest_'):
            return True

        user = User.objects.get(id=user_id)

        try:
            meeting = Meeting.objects.get(room_id=room_id)
            UserMeetingPacket.objects.get_or_create(
                user=user,
                room_id=room_id,
                defaults={
                    'author': meeting.author,
                    'meeting': meeting,
                    'meeting_name': meeting.name
                }
            )
        except Meeting.DoesNotExist:
            personal_room = PersonalRoom.objects.get(room_id=room_id)
            UserMeetingPacket.objects.get_or_create(
                user=user,
                room_id=room_id,
                defaults={
                    'author': personal_room.user,
                    'meeting': None,
                    'meeting_name': personal_room.room_name
                }
            )

        return True

    except User.DoesNotExist:
        logger.warning(f"User {user_id} not found when creating meeting packet")
        return False
    except Exception as e:
        logger.exception(f"Error creating meeting packet for user {user_id} in room {room_id}: {e}")
        raise self.retry(exc=e)
