import logging
from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=5)
def setup_user_in_org(self, user_id, org_id):
    """
    Post-registration/post-add background setup:
    - Create a PersonalRoom for the user in the organization
    - Set the user's profile current_organization
    Runs as a background task to keep the HTTP response fast.
    """
    try:
        from django.contrib.auth.models import User
        from .models import Profile, Organization
        from meetings.models import PersonalRoom

        user = User.objects.get(id=user_id)
        org = Organization.objects.get(id=org_id)

        # Create personal room (idempotent)
        PersonalRoom.objects.get_or_create(user=user, organization=org)

        # Update profile's current organization
        try:
            profile = user.profile
            if not profile.current_organization_id:
                profile.current_organization = org
                profile.save(update_fields=['current_organization', 'updated_at'])
        except Profile.DoesNotExist:
            pass

        logger.info(f"Background setup complete for user {user_id} in org {org_id}")
        return True

    except (User.DoesNotExist, Organization.DoesNotExist) as e:
        logger.warning(f"setup_user_in_org: {e}")
        return False
    except Exception as e:
        logger.exception(f"setup_user_in_org failed for user {user_id}, org {org_id}: {e}")
        raise self.retry(exc=e)
