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
    Rate limiting for WebSocket connections.
    Prevents DoS attacks via excessive connections.
    """

    # Track connections per IP
    _connections = {}
    MAX_CONNECTIONS_PER_IP = 10

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'websocket':
            client = scope.get('client', ['unknown', 0])
            ip = client[0]

            # Count current connections from this IP
            current_count = self._connections.get(ip, 0)

            if current_count >= self.MAX_CONNECTIONS_PER_IP:
                security_logger.warning(
                    f'WebSocket rate limit exceeded for IP: {ip}'
                )
                await send({
                    'type': 'websocket.close',
                    'code': 4029  # Too many requests
                })
                return

            # Increment connection count
            self._connections[ip] = current_count + 1

            try:
                return await self.inner(scope, receive, send)
            finally:
                # Decrement on disconnect
                self._connections[ip] = max(0, self._connections.get(ip, 1) - 1)

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
