from django import template

register = template.Library()


@register.simple_tag(takes_context=True)
def plan_tier(context):
    """Returns the current org's plan tier string."""
    request = context.get('request')
    if request:
        return getattr(request, 'plan_tier', 'free')
    return 'free'


@register.simple_tag(takes_context=True)
def can_record(context):
    """Returns True if org's plan allows recording."""
    request = context.get('request')
    if request:
        limits = getattr(request, 'plan_limits', None)
        if limits:
            return limits.can_record()
    return False


@register.simple_tag(takes_context=True)
def can_create_room(context):
    """Returns True if org can create another room."""
    request = context.get('request')
    if request:
        limits = getattr(request, 'plan_limits', None)
        if limits:
            return limits.can_create_room()
    return False


@register.filter
def format_price(cents):
    """Format cents to dollar string: 899 -> '$8.99'"""
    try:
        return f"${int(cents) / 100:.2f}"
    except (ValueError, TypeError):
        return "$0.00"
