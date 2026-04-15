"""
LiveKit Integration Service
Handles token generation, room management, and recording for video meetings.
"""

from livekit import api
from django.conf import settings
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
    
    def generate_token(self, room_id, user_id, username, is_moderator=False):
        """
        Generate access token for joining a LiveKit room
        
        Args:
            room_id (str): Meeting room identifier
            user_id (str): Unique user identifier
            username (str): Display name for the participant
            is_moderator (bool): Whether user has moderator privileges
            
        Returns:
            str: JWT token for LiveKit connection
        """
        try:
            token = api.AccessToken(self.api_key, self.api_secret)
            
            # Set participant identity and name
            token.with_identity(str(user_id))
            token.with_name(username)
            
            # Define permissions based on role
            grants = api.VideoGrants(
                room_join=True,
                room=room_id,
                can_publish=True,
                can_subscribe=True,
                can_publish_data=True,  # For chat messages
            )
            
            # Moderators get additional permissions
            if is_moderator:
                grants.room_admin = True
                grants.can_update_own_metadata = True
            
            token.with_grants(grants)
            
            # Token valid for 24 hours
            token.with_ttl(timedelta(hours=24))
            
            jwt_token = token.to_jwt()
            
            logger.info(f"Generated LiveKit token for user {user_id} in room {room_id}")
            return jwt_token
            
        except Exception as e:
            logger.error(f"Failed to generate LiveKit token: {str(e)}")
            raise
    
    def create_room(self, room_id, empty_timeout=300, max_participants=100):
        """
        Create a LiveKit room with specific settings
        
        Args:
            room_id (str): Unique room identifier
            empty_timeout (int): Seconds before empty room is closed (default: 5 min)
            max_participants (int): Maximum allowed participants
            
        Returns:
            Room object
        """
        try:
            room_service = api.RoomService()
            
            room = room_service.create_room(
                api.CreateRoomRequest(
                    name=room_id,
                    empty_timeout=empty_timeout,
                    max_participants=max_participants,
                )
            )
            
            logger.info(f"Created LiveKit room: {room_id}")
            return room
            
        except Exception as e:
            logger.error(f"Failed to create room {room_id}: {str(e)}")
            raise
    
    def list_participants(self, room_id):
        """
        Get list of current participants in a room
        
        Args:
            room_id (str): Room identifier
            
        Returns:
            list: List of participant objects
        """
        try:
            room_service = api.RoomService()
            participants = room_service.list_participants(
                api.ListParticipantsRequest(room=room_id)
            )
            
            return participants.participants
            
        except Exception as e:
            logger.error(f"Failed to list participants for room {room_id}: {str(e)}")
            return []
    
    def remove_participant(self, room_id, participant_identity):
        """
        Remove a participant from a room (moderator action)
        
        Args:
            room_id (str): Room identifier
            participant_identity (str): User ID to remove
        """
        try:
            room_service = api.RoomService()
            room_service.remove_participant(
                api.RoomParticipantIdentity(
                    room=room_id,
                    identity=participant_identity
                )
            )
            
            logger.info(f"Removed participant {participant_identity} from room {room_id}")
            
        except Exception as e:
            logger.error(f"Failed to remove participant: {str(e)}")
            raise
    
    def mute_participant(self, room_id, participant_identity, track_type='audio'):
        """
        Mute a participant's audio or video (moderator action)
        
        Args:
            room_id (str): Room identifier
            participant_identity (str): User ID to mute
            track_type (str): 'audio' or 'video'
        """
        try:
            room_service = api.RoomService()
            room_service.mute_published_track(
                api.MuteRoomTrackRequest(
                    room=room_id,
                    identity=participant_identity,
                    track_sid='',  # Empty means mute all tracks of this type
                    muted=True
                )
            )
            
            logger.info(f"Muted {track_type} for {participant_identity} in room {room_id}")
            
        except Exception as e:
            logger.error(f"Failed to mute participant: {str(e)}")
            raise
    
    def start_recording(self, room_id, output_filename=None):
        """
        Start recording a room directly to S3
        
        Args:
            room_id (str): Room identifier
            output_filename (str): Custom filename (optional)
            
        Returns:
            EgressInfo object with recording details
        """
        try:
            egress_service = api.EgressService()
            
            # Use room_id as filename if not provided
            timestamp = int(time.time())
            filename = output_filename or f"recordings/{room_id}_{timestamp}.mp4"
            
            # Get AWS credentials from Django settings
            aws_access_key = settings.AWS_ACCESS_KEY_ID
            aws_secret_key = settings.AWS_SECRET_ACCESS_KEY
            aws_bucket = settings.AWS_S3_BUCKET_NAME
            aws_region = settings.AWS_S3_REGION
            
            # Configure S3 output with direct credentials
            egress = egress_service.start_room_composite_egress(
                api.RoomCompositeEgressRequest(
                    room_name=room_id,
                    layout="grid",  # Grid layout for all participants
                    audio_only=False,
                    video_only=False,
                    file_outputs=[
                        api.EncodedFileOutput(
                            file_type=api.EncodedFileType.MP4,
                            filepath=filename,
                            # Direct S3 upload configuration
                            s3=api.S3Upload(
                                access_key=aws_access_key,
                                secret=aws_secret_key,
                                region=aws_region,
                                bucket=aws_bucket,
                            )
                        )
                    ]
                )
            )
            
            logger.info(f"Started recording for room {room_id}, egress_id: {egress.egress_id}, S3: s3://{aws_bucket}/{filename}")
            return egress
            
        except Exception as e:
            logger.error(f"Failed to start recording for room {room_id}: {str(e)}")
            raise
    
    def stop_recording(self, egress_id):
        """
        Stop an ongoing recording
        
        Args:
            egress_id (str): Egress/recording identifier
        """
        try:
            egress_service = api.EgressService()
            egress_service.stop_egress(egress_id)
            
            logger.info(f"Stopped recording: {egress_id}")
            
        except Exception as e:
            logger.error(f"Failed to stop recording {egress_id}: {str(e)}")
            raise
    
    def get_recording_info(self, egress_id):
        """
        Get status and details of a recording
        
        Args:
            egress_id (str): Egress/recording identifier
            
        Returns:
            EgressInfo object
        """
        try:
            egress_service = api.EgressService()
            egress = egress_service.list_egress(
                api.ListEgressRequest(room_name='', egress_id=egress_id)
            )
            
            return egress
            
        except Exception as e:
            logger.error(f"Failed to get recording info for {egress_id}: {str(e)}")
            raise
    
    def delete_room(self, room_id):
        """
        Delete a room and disconnect all participants
        
        Args:
            room_id (str): Room identifier
        """
        try:
            room_service = api.RoomService()
            room_service.delete_room(api.DeleteRoomRequest(room=room_id))
            
            logger.info(f"Deleted LiveKit room: {room_id}")
            
        except Exception as e:
            logger.error(f"Failed to delete room {room_id}: {str(e)}")
            raise
    
    def send_data_message(self, room_id, data, destination_identities=None):
        """
        Send data message to room (for chat, signaling, etc.)
        
        Args:
            room_id (str): Room identifier
            data (bytes): Message data to send
            destination_identities (list): Specific participants to send to (None = broadcast)
        """
        try:
            room_service = api.RoomService()
            room_service.send_data(
                api.SendDataRequest(
                    room=room_id,
                    data=data,
                    destination_identities=destination_identities or []
                )
            )
            
        except Exception as e:
            logger.error(f"Failed to send data message: {str(e)}")
            raise


# Singleton instance
_livekit_service = None

def get_livekit_service():
    """Get singleton LiveKit service instance"""
    global _livekit_service
    if _livekit_service is None:
        _livekit_service = LiveKitService()
    return _livekit_service