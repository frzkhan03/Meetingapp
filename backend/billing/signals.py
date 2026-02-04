from django.db.models.signals import post_save
from django.dispatch import receiver
from users.models import Organization


@receiver(post_save, sender=Organization)
def create_free_subscription(sender, instance, created, **kwargs):
    """Auto-create a free subscription when a new organization is created."""
    if created:
        from .models import Plan, Subscription
        try:
            free_plan = Plan.objects.get(tier='free')
            Subscription.objects.get_or_create(
                organization=instance,
                defaults={
                    'plan': free_plan,
                    'status': 'active',
                    'billing_cycle': 'monthly',
                }
            )
        except Plan.DoesNotExist:
            pass  # Plans not seeded yet
