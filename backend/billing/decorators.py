from functools import wraps
from django.contrib import messages
from django.shortcuts import redirect


def require_plan(min_tier):
    """
    Decorator requiring the org to be on at least the given plan tier.
    Tier ordering: free < pro < business
    """
    tier_order = {'free': 0, 'pro': 1, 'business': 2}

    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            plan_limits = getattr(request, 'plan_limits', None)
            current_tier = plan_limits.tier if plan_limits else 'free'

            if tier_order.get(current_tier, 0) < tier_order.get(min_tier, 0):
                messages.warning(
                    request,
                    f'This feature requires a {min_tier.title()} plan or higher. '
                    f'Please upgrade your subscription.'
                )
                return redirect('pricing')
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator


def require_recording_access(view_func):
    """Decorator that checks if the org's plan allows recording."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        plan_limits = getattr(request, 'plan_limits', None)
        if plan_limits and not plan_limits.can_record():
            messages.warning(
                request,
                'Recording requires a Pro plan or higher. Please upgrade.'
            )
            return redirect('pricing')
        return view_func(request, *args, **kwargs)
    return wrapper


def require_room_creation(view_func):
    """Decorator that checks if the org can create another room."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        plan_limits = getattr(request, 'plan_limits', None)
        if plan_limits and not plan_limits.can_create_room():
            messages.warning(
                request,
                f'Your plan allows a maximum of {plan_limits.max_rooms} room(s). '
                f'Please upgrade to create more rooms.'
            )
            return redirect('pricing')
        return view_func(request, *args, **kwargs)
    return wrapper
