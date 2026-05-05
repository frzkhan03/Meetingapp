"""
LiveKit Integration Service
Handles token generation, room management, and recording for video meetings.

Uses livekit-api 1.x async client wrapped with async_to_sync so sync Django
views can call into it without managing aiohttp sessions themselves.
"""

from livekit import api
from django.conf import settings
from asgiref.sync import async_to_sync
import logging
import time
from datetime import timedelta

logger = logging.getLogger(__name__)


class LiveKitService:
    """Service class for LiveKit video infrastructure"""

    def __init__(self):
        self.api_key = settings.LIVEKIT_API_KEY
        self.api_secret = settings.LIVEKIT_API_SECRET
        self.url = settings.LIVEKIT_URL

        if not all([self.api_key, self.api_secret, self.url]):
            raise ValueError("LiveKit credentials not configured in settings")

    def _client(self):
        """Build a fresh LiveKitAPI async client. Caller must use it as an async context manager."""
        return api.LiveKitAPI(self.url, self.api_key, self.api_secret)

    # ---- Token (sync, no HTTP) -------------------------------------------------

    def generate_token(self, room_id, user_id, username, is_moderator=False):
        try:
            token = api.AccessToken(self.api_key, self.api_secret)
            token.with_identity(str(user_id))
            token.with_name(username)

            grants = api.VideoGrants(
                room_join=True,
                room=room_id,
                can_publish=True,
                can_subscribe=True,
                can_publish_data=True,
            )
            if is_moderator:
                grants.room_admin = True
                grants.can_update_own_metadata = True

            token.with_grants(grants)
            token.with_ttl(timedelta(hours=24))

            jwt_token = token.to_jwt()
            logger.info(f"Generated LiveKit token for user {user_id} in room {room_id}")
            return jwt_token
        except Exception as e:
            logger.error(f"Failed to generate LiveKit token: {str(e)}")
            raise

    # ---- Room management (async via async_to_sync) -----------------------------

    async def _create_room_async(self, room_id, empty_timeout, max_participants):
        async with self._client() as lkapi:
            return await lkapi.room.create_room(
                api.CreateRoomRequest(
                    name=room_id,
                    empty_timeout=empty_timeout,
                    max_participants=max_participants,
                )
            )

    def create_room(self, room_id, empty_timeout=300, max_participants=100):
        try:
            room = async_to_sync(self._create_room_async)(room_id, empty_timeout, max_participants)
            logger.info(f"Created LiveKit room: {room_id}")
            return room
        except Exception as e:
            logger.error(f"Failed to create room {room_id}: {str(e)}")
            raise

    async def _list_participants_async(self, room_id):
        async with self._client() as lkapi:
            resp = await lkapi.room.list_participants(
                api.ListParticipantsRequest(room=room_id)
            )
            return list(resp.participants)

    def list_participants(self, room_id):
        try:
            return async_to_sync(self._list_participants_async)(room_id)
        except Exception as e:
            logger.error(f"Failed to list participants for room {room_id}: {str(e)}")
            return []

    async def _remove_participant_async(self, room_id, participant_identity):
        async with self._client() as lkapi:
            return await lkapi.room.remove_participant(
                api.RoomParticipantIdentity(room=room_id, identity=participant_identity)
            )

    def remove_participant(self, room_id, participant_identity):
        try:
            async_to_sync(self._remove_participant_async)(room_id, participant_identity)
            logger.info(f"Removed participant {participant_identity} from room {room_id}")
        except Exception as e:
            logger.error(f"Failed to remove participant: {str(e)}")
            raise

    async def _mute_participant_async(self, room_id, participant_identity):
        async with self._client() as lkapi:
            return await lkapi.room.mute_published_track(
                api.MuteRoomTrackRequest(
                    room=room_id,
                    identity=participant_identity,
                    track_sid='',
                    muted=True,
                )
            )

    def mute_participant(self, room_id, participant_identity, track_type='audio'):
        try:
            async_to_sync(self._mute_participant_async)(room_id, participant_identity)
            logger.info(f"Muted {track_type} for {participant_identity} in room {room_id}")
        except Exception as e:
            logger.error(f"Failed to mute participant: {str(e)}")
            raise

    async def _delete_room_async(self, room_id):
        async with self._client() as lkapi:
            return await lkapi.room.delete_room(api.DeleteRoomRequest(room=room_id))

    def delete_room(self, room_id):
        try:
            async_to_sync(self._delete_room_async)(room_id)
            logger.info(f"Deleted LiveKit room: {room_id}")
        except Exception as e:
            logger.error(f"Failed to delete room {room_id}: {str(e)}")
            raise

    async def _send_data_async(self, room_id, data, destination_identities):
        async with self._client() as lkapi:
            return await lkapi.room.send_data(
                api.SendDataRequest(
                    room=room_id,
                    data=data,
                    destination_identities=destination_identities or [],
                )
            )

    def send_data_message(self, room_id, data, destination_identities=None):
        try:
            async_to_sync(self._send_data_async)(room_id, data, destination_identities)
        except Exception as e:
            logger.error(f"Failed to send data message: {str(e)}")
            raise

    # ---- Egress / recording ----------------------------------------------------

    async def _start_recording_async(self, room_id, filename):
        aws_access_key = settings.AWS_ACCESS_KEY_ID
        aws_secret_key = settings.AWS_SECRET_ACCESS_KEY
        aws_bucket = settings.AWS_S3_BUCKET_NAME
        aws_region = settings.AWS_S3_REGION

        async with self._client() as lkapi:
            return await lkapi.egress.start_room_composite_egress(
                api.RoomCompositeEgressRequest(
                    room_name=room_id,
                    layout="grid",
                    audio_only=False,
                    video_only=False,
                    file_outputs=[
                        api.EncodedFileOutput(
                            file_type=api.EncodedFileType.MP4,
                            filepath=filename,
                            s3=api.S3Upload(
                                access_key=aws_access_key,
                                secret=aws_secret_key,
                                region=aws_region,
                                bucket=aws_bucket,
                            ),
                        )
                    ],
                )
            )

    def start_recording(self, room_id, output_filename=None):
        try:
            timestamp = int(time.time())
            filename = output_filename or f"recordings/{room_id}_{timestamp}.mp4"
            egress = async_to_sync(self._start_recording_async)(room_id, filename)
            logger.info(
                f"Started recording for room {room_id}, egress_id: {egress.egress_id}, "
                f"S3: s3://{settings.AWS_S3_BUCKET_NAME}/{filename}"
            )
            return egress
        except Exception as e:
            logger.error(f"Failed to start recording for room {room_id}: {str(e)}")
            raise

    async def _stop_recording_async(self, egress_id):
        async with self._client() as lkapi:
            return await lkapi.egress.stop_egress(api.StopEgressRequest(egress_id=egress_id))

    def stop_recording(self, egress_id):
        try:
            async_to_sync(self._stop_recording_async)(egress_id)
            logger.info(f"Stopped recording: {egress_id}")
        except Exception as e:
            logger.error(f"Failed to stop recording {egress_id}: {str(e)}")
            raise

    async def _get_recording_info_async(self, egress_id):
        async with self._client() as lkapi:
            return await lkapi.egress.list_egress(
                api.ListEgressRequest(room_name='', egress_id=egress_id)
            )

    def get_recording_info(self, egress_id):
        try:
            return async_to_sync(self._get_recording_info_async)(egress_id)
        except Exception as e:
            logger.error(f"Failed to get recording info for {egress_id}: {str(e)}")
            raise


# Singleton instance
_livekit_service = None


def get_livekit_service():
    """Get singleton LiveKit service instance"""
    global _livekit_service
    if _livekit_service is None:
        _livekit_service = LiveKitService()
    return _livekit_service
