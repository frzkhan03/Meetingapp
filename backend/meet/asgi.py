"""
ASGI config for gmeet project.
Includes WebSocket security middleware.
"""

import os
import logging
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'meet.settings')

# Initialize Django ASGI application early to ensure the AppRegistry
# is populated before importing code that may import ORM models.
django_asgi_app = get_asgi_application()

from meetings.routing import websocket_urlpatterns
from meet.middleware import WebSocketSecurityMiddleware

security_logger = logging.getLogger('security')


class WebSocketRateLimiter:
    """
    Rate limiting for WebSocket connections using Redis cache.
    Works correctly across multiple server instances.
    """

    MAX_CONNECTIONS_PER_IP = 50  # Increased from 10 for corporate NAT support

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'websocket':
            client = scope.get('client', ['unknown', 0])
            ip = client[0]
            cache_key = f'ws:conn:{ip}'

            try:
                from django.core.cache import cache
                current_count = cache.get(cache_key, 0)

                if current_count >= self.MAX_CONNECTIONS_PER_IP:
                    security_logger.warning(
                        f'WebSocket rate limit exceeded for IP: {ip}'
                    )
                    await send({
                        'type': 'websocket.close',
                        'code': 4029  # Too many requests
                    })
                    return

                # Increment with TTL (auto-cleanup after 1 hour)
                try:
                    cache.incr(cache_key)
                except ValueError:
                    cache.set(cache_key, 1, 3600)

                try:
                    return await self.inner(scope, receive, send)
                finally:
                    # Decrement on disconnect
                    try:
                        new_val = cache.decr(cache_key)
                        if new_val <= 0:
                            cache.delete(cache_key)
                    except (ValueError, Exception):
                        pass

            except Exception:
                # If Redis is down, allow the connection (fail open)
                return await self.inner(scope, receive, send)

        return await self.inner(scope, receive, send)


application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": WebSocketSecurityMiddleware(
        WebSocketRateLimiter(
            AuthMiddlewareStack(
                URLRouter(
                    websocket_urlpatterns
                )
            )
        )
    ),
})
