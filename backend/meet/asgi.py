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
    Enforces per-IP and per-user connection limits.
    Works correctly across multiple server instances.
    """

    MAX_CONNECTIONS_PER_IP = 50    # Corporate NAT support
    MAX_CONNECTIONS_PER_USER = 10  # Per authenticated user (room + user sockets, multiple tabs)

    def __init__(self, inner):
        self.inner = inner

    def _get_user_id(self, scope):
        """Extract user ID from scope if authenticated."""
        user = scope.get('user')
        if user and hasattr(user, 'is_authenticated') and user.is_authenticated:
            return str(user.id)
        return None

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'websocket':
            client = scope.get('client', ['unknown', 0])
            ip = client[0]
            ip_key = f'ws:conn:ip:{ip}'
            user_id = self._get_user_id(scope)
            user_key = f'ws:conn:user:{user_id}' if user_id else None

            try:
                from django.core.cache import cache

                # Check per-IP limit
                ip_count = cache.get(ip_key, 0)
                if ip_count >= self.MAX_CONNECTIONS_PER_IP:
                    security_logger.warning(
                        f'WebSocket rate limit exceeded for IP: {ip}'
                    )
                    await send({
                        'type': 'websocket.close',
                        'code': 4029  # Too many requests
                    })
                    return

                # Check per-user limit
                if user_key:
                    user_count = cache.get(user_key, 0)
                    if user_count >= self.MAX_CONNECTIONS_PER_USER:
                        security_logger.warning(
                            f'WebSocket per-user limit exceeded for user: {user_id}'
                        )
                        await send({
                            'type': 'websocket.close',
                            'code': 4029
                        })
                        return

                # Increment counters with TTL (auto-cleanup after 1 hour)
                for key in (ip_key, user_key):
                    if key:
                        try:
                            cache.incr(key)
                        except ValueError:
                            cache.set(key, 1, 3600)

                try:
                    return await self.inner(scope, receive, send)
                finally:
                    # Decrement on disconnect
                    for key in (ip_key, user_key):
                        if key:
                            try:
                                new_val = cache.decr(key)
                                if new_val <= 0:
                                    cache.delete(key)
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
