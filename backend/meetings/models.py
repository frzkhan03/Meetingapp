import uuid
import secrets
import random
import string
from django.db import models
from django.contrib.auth.models import User
from users.models import Organization


def generate_meeting_code():
    """Generate a Google Meet-style meeting code like 'abc-defg-hij'"""
    def random_letters(length):
        return ''.join(random.choices(string.ascii_lowercase, k=length))

    return f"{random_letters(3)}-{random_letters(4)}-{random_letters(3)}"


def get_unique_meeting_code():
    """Generate a unique meeting code that doesn't exist in the database"""
    from .models import Meeting, PersonalRoom

    max_attempts = 100
    for _ in range(max_attempts):
        code = generate_meeting_code()
        # Check both Meeting and PersonalRoom tables
        if not Meeting.objects.filter(room_id=code).exists() and \
           not PersonalRoom.objects.filter(room_id=code).exists():
            return code

    # Fallback to longer code if we can't find unique one
    return f"{generate_meeting_code()}-{random.randint(100, 999)}"


class PersonalRoom(models.Model):
    """Personal meeting room for each user in an organization"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='personal_rooms')
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='personal_rooms')
    room_id = models.CharField(max_length=20, unique=True, editable=False)
    moderator_token = models.CharField(max_length=64, unique=True, editable=False)
    attendee_token = models.CharField(max_length=64, unique=True, editable=False)
    room_name = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)
    is_locked = models.BooleanField(default=True, help_text='When locked, participants need approval to join')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['user', 'organization']
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if not self.room_id:
            self.room_id = get_unique_meeting_code()
        if not self.moderator_token:
            self.moderator_token = secrets.token_urlsafe(32)
        if not self.attendee_token:
            self.attendee_token = secrets.token_urlsafe(32)
        if not self.room_name:
            self.room_name = f"{self.user.username}'s Room"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user.username}'s Room - {self.organization.name}"

    def get_moderator_link(self):
        return f"/meeting/room/{self.room_id}/join/?token={self.moderator_token}"

    def get_attendee_link(self):
        return f"/meeting/room/{self.room_id}/join/?token={self.attendee_token}"


class Meeting(models.Model):
    """Meeting model with multi-tenant support"""
    RECURRENCE_CHOICES = [
        ('none', 'Does not repeat'),
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('biweekly', 'Every 2 weeks'),
        ('monthly', 'Monthly'),
    ]

    name = models.CharField(max_length=255)
    room_id = models.CharField(max_length=20, unique=True, editable=False)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name='meetings',
        null=True,
        blank=True
    )
    description = models.TextField(blank=True, default='')
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    is_all_day = models.BooleanField(default=False)
    recurrence = models.CharField(max_length=20, choices=RECURRENCE_CHOICES, default='none')
    location = models.CharField(max_length=255, blank=True, default='')
    author = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='created_meetings'
    )
    author_name = models.CharField(max_length=255)
    users = models.ManyToManyField(
        User,
        related_name='meetings',
        blank=True
    )
    attendees_emails = models.TextField(blank=True, default='', help_text='Comma-separated email addresses')
    is_private = models.BooleanField(default=False)
    require_approval = models.BooleanField(default=True)
    max_participants = models.IntegerField(default=100)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-start_time']

    def save(self, *args, **kwargs):
        if not self.room_id:
            self.room_id = get_unique_meeting_code()
        super().save(*args, **kwargs)

    def __str__(self):
        org_name = self.organization.name if self.organization else 'No Org'
        return f"{self.name} - {org_name}"


class UserMeetingPacket(models.Model):
    """Tracks user permissions for joining meetings"""
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='meeting_packets'
    )
    meeting = models.ForeignKey(
        Meeting,
        on_delete=models.CASCADE,
        related_name='packets',
        null=True,
        blank=True
    )
    author = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='authorized_packets'
    )
    room_id = models.CharField(max_length=20)
    meeting_name = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['user', 'room_id']

    def __str__(self):
        return f"{self.user.username} - {self.room_id}"


class MeetingRecording(models.Model):
    """Store meeting recordings metadata"""
    meeting = models.ForeignKey(
        Meeting,
        on_delete=models.CASCADE,
        related_name='recordings'
    )
    recorded_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='recordings'
    )
    file_path = models.CharField(max_length=500)
    file_size = models.BigIntegerField(default=0)
    duration = models.IntegerField(default=0)  # in seconds
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Recording - {self.meeting.name} - {self.created_at}"
