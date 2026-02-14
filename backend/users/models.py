from django.db import models
from django.contrib.auth.models import User
from django.core.cache import cache
import uuid


class Organization(models.Model):
    """Tenant/Organization model for multi-tenancy"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=100, unique=True)
    domain = models.CharField(max_length=255, blank=True, null=True, unique=True)
    logo = models.URLField(blank=True, null=True)
    # Branding colors (hex format, e.g., #7C3AED)
    primary_color = models.CharField(max_length=7, blank=True, default='')
    secondary_color = models.CharField(max_length=7, blank=True, default='')
    # Subdomain for custom URLs (e.g., 'acme' for acme.pytalk.veriright.com)
    subdomain = models.CharField(max_length=63, blank=True, unique=True, null=True, db_index=True)
    is_active = models.BooleanField(default=True)
    recording_to_s3 = models.BooleanField(default=False, help_text='Save recordings to cloud storage instead of local download')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        indexes = [
            models.Index(fields=['is_active']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        # Normalize empty subdomain to None (for unique constraint with nullable field)
        if not self.subdomain:
            self.subdomain = None
        super().save(*args, **kwargs)


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
        indexes = [
            models.Index(fields=['organization', 'is_active']),
            models.Index(fields=['user', 'organization', 'is_active']),
            models.Index(fields=['organization', 'role']),
        ]

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

    class Meta:
        indexes = [
            models.Index(fields=['current_organization']),
        ]

    def __str__(self):
        return f"{self.user.username}'s profile"

    def get_organizations(self):
        """Get all organizations the user belongs to (cached 5 min)"""
        cache_key = f'user:{self.user_id}:orgs'
        org_ids = cache.get(cache_key)
        if org_ids is None:
            org_ids = list(
                OrganizationMembership.objects.filter(
                    user=self.user,
                    is_active=True
                ).values_list('organization_id', flat=True)
            )
            cache.set(cache_key, org_ids, 300)
        return Organization.objects.filter(id__in=org_ids)

    def is_member_of(self, organization):
        """Check if user is a member of the given organization (cached 5 min)"""
        cache_key = f'user:{self.user_id}:org:{organization.pk}:member'
        result = cache.get(cache_key)
        if result is None:
            result = OrganizationMembership.objects.filter(
                user=self.user,
                organization=organization,
                is_active=True
            ).exists()
            cache.set(cache_key, result, 300)
        return result

    def get_role_in(self, organization):
        """Get user's role in the given organization (cached 5 min)"""
        cache_key = f'user:{self.user_id}:org:{organization.pk}:role'
        role = cache.get(cache_key)
        if role is None:
            membership = OrganizationMembership.objects.filter(
                user=self.user,
                organization=organization,
                is_active=True
            ).only('role').first()
            role = membership.role if membership else ''
            cache.set(cache_key, role, 300)
        return role or None

    @staticmethod
    def invalidate_org_cache(user_id, organization_id=None):
        """Invalidate cached organization data for a user"""
        cache.delete(f'user:{user_id}:orgs')
        if organization_id:
            cache.delete(f'user:{user_id}:org:{organization_id}:member')
            cache.delete(f'user:{user_id}:org:{organization_id}:role')
