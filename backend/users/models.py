from django.db import models
from django.contrib.auth.models import User
import uuid


class Organization(models.Model):
    """Tenant/Organization model for multi-tenancy"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=100, unique=True)
    domain = models.CharField(max_length=255, blank=True, null=True, unique=True)
    logo = models.URLField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class OrganizationMembership(models.Model):
    """Membership linking users to organizations with roles"""
    ROLE_CHOICES = [
        ('owner', 'Owner'),
        ('admin', 'Admin'),
        ('member', 'Member'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='memberships')
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='memberships')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='member')
    is_active = models.BooleanField(default=True)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['user', 'organization']
        ordering = ['-joined_at']

    def __str__(self):
        return f"{self.user.username} - {self.organization.name} ({self.role})"


class Profile(models.Model):
    """User profile with current organization context"""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    current_organization = models.ForeignKey(
        Organization,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='current_users'
    )
    avatar = models.URLField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username}'s profile"

    def get_organizations(self):
        """Get all organizations the user belongs to"""
        return Organization.objects.filter(
            memberships__user=self.user,
            memberships__is_active=True
        )

    def is_member_of(self, organization):
        """Check if user is a member of the given organization"""
        return OrganizationMembership.objects.filter(
            user=self.user,
            organization=organization,
            is_active=True
        ).exists()

    def get_role_in(self, organization):
        """Get user's role in the given organization"""
        membership = OrganizationMembership.objects.filter(
            user=self.user,
            organization=organization,
            is_active=True
        ).first()
        return membership.role if membership else None
