import json

from django.template.response import TemplateResponse
from django.utils import timezone
from django.db.models import Avg, Sum, Count, Max, Min, F
from django.db.models.functions import TruncHour, TruncDate
from datetime import timedelta


def connection_analytics_view(request):
    """Admin dashboard for WebRTC connection quality analytics."""
    from .models import ConnectionLog
    from users.models import Organization

    now = timezone.now()
    seven_days_ago = now - timedelta(days=7)

    # Organization filter
    org_id = request.GET.get('org')
    qs = ConnectionLog.objects.filter(created_at__gte=seven_days_ago)
    if org_id:
        qs = qs.filter(organization_id=org_id)

    organizations = Organization.objects.all().order_by('name')

    # Summary metrics
    summary = qs.aggregate(
        total_connections=Count('id'),
        avg_bitrate=Avg('avg_bitrate_kbps'),
        avg_rtt=Avg('avg_rtt_ms'),
        avg_packet_loss=Avg('packet_loss_pct'),
        total_reconnections=Sum('reconnection_count'),
        avg_duration=Avg('duration_seconds'),
    )

    # Hourly quality trend (last 48 hours)
    forty_eight_hours_ago = now - timedelta(hours=48)
    hourly_trend = list(
        qs.filter(created_at__gte=forty_eight_hours_ago)
        .annotate(hour=TruncHour('created_at'))
        .values('hour')
        .annotate(
            avg_bitrate=Avg('avg_bitrate_kbps'),
            avg_rtt=Avg('avg_rtt_ms'),
            avg_loss=Avg('packet_loss_pct'),
            connections=Count('id'),
        )
        .order_by('hour')
    )

    # Problem rooms (high packet loss or reconnections)
    problem_rooms = list(
        qs.values('room_id')
        .annotate(
            connections=Count('id'),
            avg_loss=Avg('packet_loss_pct'),
            avg_rtt=Avg('avg_rtt_ms'),
            total_reconnects=Sum('reconnection_count'),
            avg_bitrate=Avg('avg_bitrate_kbps'),
        )
        .filter(avg_loss__gt=2)
        .order_by('-avg_loss')[:10]
    )

    # Browser breakdown
    browser_stats = list(
        qs.values('browser')
        .annotate(
            count=Count('id'),
            avg_bitrate=Avg('avg_bitrate_kbps'),
            avg_loss=Avg('packet_loss_pct'),
        )
        .order_by('-count')[:10]
    )

    # Device type breakdown
    device_stats = list(
        qs.values('device_type')
        .annotate(
            count=Count('id'),
            avg_bitrate=Avg('avg_bitrate_kbps'),
            avg_loss=Avg('packet_loss_pct'),
        )
        .order_by('-count')
    )

    # Recent connections
    recent = list(
        qs.order_by('-created_at')
        .values(
            'room_id', 'user_id', 'avg_bitrate_kbps', 'avg_rtt_ms',
            'packet_loss_pct', 'duration_seconds', 'reconnection_count',
            'browser', 'device_type', 'created_at',
        )[:20]
    )

    # Daily connection counts (for bar chart)
    daily_counts = list(
        qs.annotate(day=TruncDate('created_at'))
        .values('day')
        .annotate(count=Count('id'))
        .order_by('day')
    )

    context = {
        'title': 'Connection Analytics',
        'summary': summary,
        'organizations': organizations,
        'selected_org': org_id,
        'problem_rooms': problem_rooms,
        'browser_stats': browser_stats,
        'device_stats': device_stats,
        'recent': recent,
        'hourly_trend_json': json.dumps([
            {
                'hour': r['hour'].strftime('%b %d %H:%M'),
                'bitrate': round(r['avg_bitrate'] or 0, 1),
                'rtt': round(r['avg_rtt'] or 0, 1),
                'loss': round(r['avg_loss'] or 0, 2),
                'connections': r['connections'],
            }
            for r in hourly_trend
        ]),
        'daily_counts_json': json.dumps([
            {
                'day': r['day'].strftime('%b %d'),
                'count': r['count'],
            }
            for r in daily_counts
        ]),
    }

    return TemplateResponse(request, 'admin/connection_analytics.html', context)
