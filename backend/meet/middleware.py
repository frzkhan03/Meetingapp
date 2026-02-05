"""
Security Middleware for PyTalk
Comprehensive security measures including rate limiting, security headers,
session protection, and security logging.
"""

import hashlib
import logging
import time
from django.conf import settings
from django.http import HttpResponseForbidden, JsonResponse
from django.core.cache import cache
from django.utils.deprecation import MiddlewareMixin

security_logger = logging.getLogger('security')


class SecurityHeadersMiddleware(MiddlewareMixin):
    """
    Adds comprehensive security headers to all responses.
    Implements CSP, HSTS, X-Frame-Options, and other security headers.
    """

    def process_response(self, request, response):
        # Content Security Policy
        default_self = ("'self'",)
        default_none = ("'none'",)

        csp_directives = [
            "default-src " + ' '.join(getattr(settings, 'CSP_DEFAULT_SRC', default_self)),
            "script-src " + ' '.join(getattr(settings, 'CSP_SCRIPT_SRC', default_self)),
            "style-src " + ' '.join(getattr(settings, 'CSP_STYLE_SRC', default_self)),
            "font-src " + ' '.join(getattr(settings, 'CSP_FONT_SRC', default_self)),
            "img-src " + ' '.join(getattr(settings, 'CSP_IMG_SRC', default_self)),
            "connect-src " + ' '.join(getattr(settings, 'CSP_CONNECT_SRC', default_self)),
            "media-src " + ' '.join(getattr(settings, 'CSP_MEDIA_SRC', default_self)),
            "frame-ancestors " + ' '.join(getattr(settings, 'CSP_FRAME_ANCESTORS', default_none)),
            "worker-src " + ' '.join(getattr(settings, 'CSP_WORKER_SRC', default_self)),
            "child-src " + ' '.join(getattr(settings, 'CSP_CHILD_SRC', default_self)),
        ]
        response['Content-Security-Policy'] = '; '.join(csp_directives)

        # Additional security headers
        response['X-Content-Type-Options'] = 'nosniff'
        response['X-XSS-Protection'] = '1; mode=block'
        response['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response['Permissions-Policy'] = 'geolocation=(), microphone=(self), camera=(self)'

        # Prevent caching of sensitive pages
        if request.path.startswith('/user/') or request.path.startswith('/secure-admin/'):
            response['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
            response['Pragma'] = 'no-cache'
            response['Expires'] = '0'

        return response


class RateLimitMiddleware(MiddlewareMixin):
    """
    Rate limiting middleware using Redis for distributed rate limiting.
    Works correctly across multiple server instances.
    """

    def get_client_ip(self, request):
        """Get client IP address, considering proxies"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip

    def get_rate_limit_key(self, request, key_type='general'):
        """Generate a unique key for rate limiting"""
        ip = self.get_client_ip(request)
        if key_type == 'login':
            return f'ratelimit:login:{ip}'
        elif key_type == 'api':
            return f'ratelimit:api:{ip}'
        return f'ratelimit:general:{ip}'

    def is_rate_limited(self, key, max_requests, window_seconds):
        """Check rate limit using atomic Redis INCR + EXPIRE (distributed-safe)"""
        try:
            try:
                new_count = cache.incr(key)
            except ValueError:
                # Key doesn't exist yet — set it with TTL
                cache.set(key, 1, window_seconds)
                return False
            # Set expiry on first increment (new_count == 1 handled above via ValueError)
            if new_count == 1:
                cache.expire(key, window_seconds)
            return new_count > max_requests
        except Exception:
            # If Redis is down, allow the request (fail open)
            return False

    def process_request(self, request):
        if not getattr(settings, 'RATE_LIMIT_ENABLED', True):
            return None

        # Login endpoint rate limiting
        if request.path == '/user/login/' and request.method == 'POST':
            key = self.get_rate_limit_key(request, 'login')
            max_attempts = getattr(settings, 'RATE_LIMIT_LOGIN_ATTEMPTS', 5)
            window = getattr(settings, 'RATE_LIMIT_LOGIN_WINDOW', 300)

            if self.is_rate_limited(key, max_attempts, window):
                security_logger.warning(
                    f'Rate limit exceeded for login from {self.get_client_ip(request)}'
                )
                return JsonResponse({
                    'error': 'Too many login attempts. Please try again later.',
                    'retry_after': window
                }, status=429)

        # API rate limiting
        if request.path.startswith('/api/'):
            key = self.get_rate_limit_key(request, 'api')
            max_requests = getattr(settings, 'RATE_LIMIT_API_REQUESTS', 100)
            window = getattr(settings, 'RATE_LIMIT_API_WINDOW', 60)

            if self.is_rate_limited(key, max_requests, window):
                security_logger.warning(
                    f'API rate limit exceeded from {self.get_client_ip(request)}'
                )
                return JsonResponse({
                    'error': 'Rate limit exceeded. Please slow down.',
                    'retry_after': window
                }, status=429)

        return None


class SessionSecurityMiddleware(MiddlewareMixin):
    """
    Enhanced session security middleware.
    Implements session fixation protection, IP binding, and session rotation.
    """

    def get_client_ip(self, request):
        """Get client IP address"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip

    def get_session_fingerprint(self, request):
        """Generate a fingerprint for the session based on client info"""
        ip = self.get_client_ip(request)
        user_agent = request.META.get('HTTP_USER_AGENT', '')
        # Create a hash of IP and User-Agent
        fingerprint = hashlib.sha256(f'{ip}:{user_agent}'.encode()).hexdigest()[:32]
        return fingerprint

    def process_request(self, request):
        if not request.session.session_key:
            return None

        # Check session fingerprint
        stored_fingerprint = request.session.get('_security_fingerprint')
        current_fingerprint = self.get_session_fingerprint(request)

        if stored_fingerprint and stored_fingerprint != current_fingerprint:
            # Potential session hijacking - invalidate session
            security_logger.warning(
                f'Session fingerprint mismatch for user {request.user}. '
                f'Possible session hijacking attempt from {self.get_client_ip(request)}'
            )
            request.session.flush()
            return None

        # Store fingerprint if not present
        if not stored_fingerprint:
            request.session['_security_fingerprint'] = current_fingerprint

        # Check session age and rotate if needed
        session_created = request.session.get('_session_created')
        if session_created:
            session_age = time.time() - session_created
            # Rotate session every 60 minutes for logged-in users
            if request.user.is_authenticated and session_age > 3600:
                request.session.cycle_key()
                request.session['_session_created'] = time.time()
        else:
            request.session['_session_created'] = time.time()

        return None

    def process_response(self, request, response):
        # Ensure secure session cookie flags
        if hasattr(request, 'session') and request.session.modified:
            response.set_cookie(
                settings.SESSION_COOKIE_NAME,
                request.session.session_key,
                max_age=settings.SESSION_COOKIE_AGE,
                secure=settings.SESSION_COOKIE_SECURE,
                httponly=settings.SESSION_COOKIE_HTTPONLY,
                samesite=settings.SESSION_COOKIE_SAMESITE,
            )
        return response


class SecurityLoggingMiddleware(MiddlewareMixin):
    """
    Logs security-relevant events for monitoring and auditing.
    """

    SENSITIVE_PATHS = ['/user/login/', '/user/register/', '/secure-admin/']

    def get_client_ip(self, request):
        """Get client IP address"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip

    def process_request(self, request):
        # Store request start time for response time logging
        request._security_start_time = time.time()
        return None

    def process_response(self, request, response):
        # Log security-relevant requests
        if any(request.path.startswith(p) for p in self.SENSITIVE_PATHS):
            duration = time.time() - getattr(request, '_security_start_time', time.time())
            user = request.user.username if request.user.is_authenticated else 'anonymous'

            log_data = {
                'path': request.path,
                'method': request.method,
                'user': user,
                'ip': self.get_client_ip(request),
                'status': response.status_code,
                'duration': f'{duration:.3f}s',
                'user_agent': request.META.get('HTTP_USER_AGENT', '')[:100],
            }

            if response.status_code >= 400:
                security_logger.warning(f'Security event: {log_data}')
            else:
                security_logger.info(f'Security event: {log_data}')

        # Log failed authentication attempts
        if request.path == '/user/login/' and request.method == 'POST':
            if response.status_code != 302:  # Not a successful redirect
                security_logger.warning(
                    f'Failed login attempt from {self.get_client_ip(request)}'
                )

        return response


class WebSocketSecurityMiddleware:
    """
    Security middleware for WebSocket connections.
    Validates origins and authenticates connections.
    """

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'websocket':
            # Validate origin for WebSocket connections
            headers = dict(scope.get('headers', []))
            origin = headers.get(b'origin', b'').decode()

            allowed_origins = getattr(settings, 'WEBSOCKET_ALLOWED_ORIGINS', [])

            # Check if origin matches any allowed origin
            origin_allowed = False
            if not origin:
                origin_allowed = True  # Allow connections without origin header
            else:
                for allowed in allowed_origins:
                    if origin == allowed or origin.startswith(allowed.rstrip('/')):
                        origin_allowed = True
                        break

            if not origin_allowed:
                security_logger.warning(f'WebSocket connection rejected from origin: {origin}')
                await send({'type': 'websocket.close', 'code': 4003})
                return

        return await self.inner(scope, receive, send)
