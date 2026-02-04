from django import template

register = template.Library()


@register.filter
def duration_format(seconds):
    """Format seconds into mm:ss"""
    try:
        seconds = int(seconds)
        mins = seconds // 60
        secs = seconds % 60
        return f"{mins}:{secs:02d}"
    except (ValueError, TypeError):
        return "--"


@register.filter
def filesizeformat_mb(bytes_val):
    """Format bytes to MB with 1 decimal"""
    try:
        mb = int(bytes_val) / (1024 * 1024)
        if mb < 0.1:
            return f"{mb:.2f} MB"
        return f"{mb:.1f} MB"
    except (ValueError, TypeError):
        return "--"
