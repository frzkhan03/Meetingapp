"""
Django settings for gmeet project.
Fortified with comprehensive security measures.
"""

import os
import secrets
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# ==================== SECURITY CONFIGURATION ====================

# Generate a secure secret key if not provided
def get_secret_key():
    """Generate or retrieve a secure secret key"""
    key = os.getenv('SECRET_KEY')
    if key and key != 'django-insecure-change-this-in-production-gmeet-clone-2024':
        return key
    # Generate a secure key for development
    return secrets.token_urlsafe(50)

SECRET_KEY = get_secret_key()

# Environment mode
DEBUG = os.getenv('DEBUG', 'True') == 'True'
PRODUCTION = os.getenv('PRODUCTION', 'False') == 'True'

# For custom subdomain support, add '.pytalk.veriright.com' to ALLOWED_HOSTS in env
# Example: ALLOWED_HOSTS=pytalk.veriright.com,.pytalk.veriright.com,localhost
ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')

# Base domain for subdomain redirects (e.g., pytalk.veriright.com)
BASE_DOMAIN = os.getenv('BASE_DOMAIN', 'pytalk.veriright.com')

# ==================== SSL/HTTPS SECURITY ====================
if PRODUCTION:
    # Force HTTPS in production
    SECURE_SSL_REDIRECT = True
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

    # HSTS (HTTP Strict Transport Security)
    SECURE_HSTS_SECONDS = 31536000  # 1 year
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
else:
    SECURE_SSL_REDIRECT = False

# ==================== COOKIE SECURITY ====================
SESSION_COOKIE_SECURE = PRODUCTION  # Only send cookies over HTTPS in production
SESSION_COOKIE_HTTPONLY = True  # Prevent JavaScript access to session cookie
SESSION_COOKIE_SAMESITE = 'Lax'  # CSRF protection
SESSION_COOKIE_AGE = 3600  # 1 hour session timeout
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_SAVE_EVERY_REQUEST = False  # Only save when modified (was True — caused DB write on every request)

# Cookie domain for subdomain support - set to .pytalk.veriright.com in production
# This allows cookies to be shared across subdomains (e.g., acme.pytalk.veriright.com)
SESSION_COOKIE_DOMAIN = os.getenv('SESSION_COOKIE_DOMAIN', None)  # None = default to current domain

CSRF_COOKIE_SECURE = PRODUCTION  # Only send CSRF cookie over HTTPS in production
CSRF_COOKIE_HTTPONLY = False  # Must be False for JavaScript AJAX to read the token
CSRF_COOKIE_SAMESITE = 'Lax'
CSRF_USE_SESSIONS = False  # Don't use sessions - use cookie for AJAX compatibility
CSRF_COOKIE_DOMAIN = os.getenv('CSRF_COOKIE_DOMAIN', None)  # Must match SESSION_COOKIE_DOMAIN
CSRF_TRUSTED_ORIGINS = os.getenv('CSRF_TRUSTED_ORIGINS', 'http://localhost:8000,http://127.0.0.1:8000').split(',')

# ==================== SECURITY HEADERS ====================
SECURE_CONTENT_TYPE_NOSNIFF = True  # Prevent MIME type sniffing
SECURE_BROWSER_XSS_FILTER = True  # Enable XSS filter
X_FRAME_OPTIONS = 'DENY'  # Prevent clickjacking
SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'

# Content Security Policy
CSP_DEFAULT_SRC = ("'self'",)
CSP_SCRIPT_SRC = ("'self'", "'unsafe-inline'", "'wasm-unsafe-eval'", "blob:", "https://unpkg.com", "https://cdn.jsdelivr.net")
CSP_STYLE_SRC = ("'self'", "'unsafe-inline'", "https://cdn.jsdelivr.net", "https://fonts.googleapis.com")
CSP_FONT_SRC = ("'self'", "https://fonts.gstatic.com", "https://cdn.jsdelivr.net")
CSP_IMG_SRC = ("'self'", "data:", "blob:", "https://*.s3.*.amazonaws.com")
CSP_CONNECT_SRC = ("'self'", "wss:", "ws:", "https://cdn.jsdelivr.net", "https://unpkg.com", "https://*.peerjs.com", "https://0.peerjs.com", "https://storage.googleapis.com")
CSP_MEDIA_SRC = ("'self'", "blob:")
CSP_FRAME_ANCESTORS = ("'none'",)
CSP_WORKER_SRC = ("'self'", "blob:")
CSP_CHILD_SRC = ("'self'", "blob:")

# Application definition
INSTALLED_APPS = [
    'daphne',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'channels',
    'users',
    'meetings',
    'billing',
]

MIDDLEWARE = [
    'meet.middleware.SecurityHeadersMiddleware',  # Custom security headers
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',  # Static files in production
    'meet.middleware.RateLimitMiddleware',  # Rate limiting
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'meet.middleware.SessionSecurityMiddleware',  # Session security
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'users.middleware.TenantMiddleware',
    'billing.middleware.SubscriptionMiddleware',  # Plan limits injection
    'meet.middleware.SecurityLoggingMiddleware',  # Security logging
]

ROOT_URLCONF = 'meet.urls'

_TEMPLATE_LOADERS = [
    'django.template.loaders.filesystem.Loader',
    'django.template.loaders.app_directories.Loader',
]

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
            'loaders': [
                ('django.template.loaders.cached.Loader', _TEMPLATE_LOADERS),
            ] if PRODUCTION else _TEMPLATE_LOADERS,
        },
    },
]

WSGI_APPLICATION = 'meet.wsgi.application'
ASGI_APPLICATION = 'meet.asgi.application'

# ==================== CACHING ====================
if PRODUCTION:
    # Redis cache for sessions, rate limiting, and application caching
    CACHES = {
        'default': {
            'BACKEND': 'django_redis.cache.RedisCache',
            'LOCATION': f"redis://{os.getenv('REDIS_HOST', 'localhost')}:{os.getenv('REDIS_PORT', 6379)}/1",
            'OPTIONS': {
                'CLIENT_CLASS': 'django_redis.client.DefaultClient',
                'SOCKET_CONNECT_TIMEOUT': 5,
                'SOCKET_TIMEOUT': 5,
                'RETRY_ON_TIMEOUT': True,
                'CONNECTION_POOL_KWARGS': {'max_connections': 200},
            },
            'KEY_PREFIX': 'pytalk',
        }
    }
    # Use Redis-backed sessions instead of database sessions
    SESSION_ENGINE = 'django.contrib.sessions.backends.cache'
    SESSION_CACHE_ALIAS = 'default'
else:
    # Local development: use in-memory cache and database sessions
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'pytalk-dev',
        }
    }
    SESSION_ENGINE = 'django.contrib.sessions.backends.db'

# Channel Layers - Redis for production, in-memory for development
if PRODUCTION:
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {
                "hosts": [(os.getenv('REDIS_HOST', 'localhost'), int(os.getenv('REDIS_PORT', 6379)))],
                "capacity": 1500,
                "expiry": 10,
            },
        },
    }
else:
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels.layers.InMemoryChannelLayer"
        }
    }

# Database - PostgreSQL
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.getenv('DB_NAME', 'PyTalk'),
        'USER': os.getenv('DB_USER', 'postgres'),
        'PASSWORD': os.getenv('DB_PASSWORD', 'admin'),
        'HOST': os.getenv('DB_HOST', 'localhost'),
        'PORT': os.getenv('DB_PORT', '5432'),
        'CONN_MAX_AGE': 600,  # Reuse connections for 10 minutes
        'OPTIONS': {
            'connect_timeout': 10,
        },
    }
}

# ==================== PASSWORD SECURITY ====================
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
        'OPTIONS': {
            'user_attributes': ('username', 'email', 'first_name', 'last_name'),
            'max_similarity': 0.7,
        }
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
        'OPTIONS': {
            'min_length': 10,  # Require at least 10 characters
        }
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Password hashing - Use Argon2 (most secure) with fallbacks
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.Argon2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher',
    'django.contrib.auth.hashers.BCryptSHA256PasswordHasher',
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'  # For collectstatic in production

# Use whitenoise for compressed and cached static files in production
if PRODUCTION:
    STORAGES = {
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
        },
    }

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Login settings
LOGIN_URL = '/user/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/'

# Email settings
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.gmail.com'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.getenv('MAIL_USER', '')
EMAIL_HOST_PASSWORD = os.getenv('MAIL_PASS', '')

# ==================== RATE LIMITING ====================
RATE_LIMIT_ENABLED = True
RATE_LIMIT_LOGIN_ATTEMPTS = 5  # Max login attempts
RATE_LIMIT_LOGIN_WINDOW = 300  # 5 minutes window
RATE_LIMIT_API_REQUESTS = 100  # Max API requests per window
RATE_LIMIT_API_WINDOW = 60  # 1 minute window

# ==================== ENCRYPTION ====================
# Encryption key for sensitive data (generate a new one for production)
ENCRYPTION_KEY = os.getenv('ENCRYPTION_KEY', secrets.token_urlsafe(32))

# ==================== SECURITY LOGGING ====================
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'security': {
            'format': '[{asctime}] {levelname} SECURITY {name}: {message}',
            'style': '{',
        },
        'verbose': {
            'format': '[{asctime}] {levelname} {name} {module}: {message}',
            'style': '{',
        },
    },
    'filters': {
        'require_debug_false': {
            '()': 'django.utils.log.RequireDebugFalse',
        },
    },
    'handlers': {
        'console': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
        'security_file': {
            'level': 'WARNING',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': BASE_DIR / 'logs' / 'security.log',
            'maxBytes': 10 * 1024 * 1024,  # 10 MB per file
            'backupCount': 5,  # Keep 5 rotated files
            'formatter': 'security',
        },
        'mail_admins': {
            'level': 'ERROR',
            'filters': ['require_debug_false'],
            'class': 'django.utils.log.AdminEmailHandler',
        },
    },
    'loggers': {
        'django.security': {
            'handlers': ['console', 'security_file'],
            'level': 'WARNING',
            'propagate': True,
        },
        'security': {
            'handlers': ['console', 'security_file'],
            'level': 'INFO',
            'propagate': False,
        },
        'django.request': {
            'handlers': ['console', 'mail_admins'],
            'level': 'ERROR',
            'propagate': False,
        },
    },
}

# Create logs directory if it doesn't exist
(BASE_DIR / 'logs').mkdir(exist_ok=True)

# ==================== ADMIN SECURITY ====================
ADMIN_URL = os.getenv('ADMIN_URL', 'secure-admin/')  # Custom admin URL

# ==================== FILE UPLOAD SECURITY ====================
FILE_UPLOAD_MAX_MEMORY_SIZE = 200 * 1024 * 1024  # 200 MB (for recording uploads)
DATA_UPLOAD_MAX_MEMORY_SIZE = 200 * 1024 * 1024  # 200 MB
DATA_UPLOAD_MAX_NUMBER_FIELDS = 100

# ==================== AWS S3 (Recording Storage) ====================
AWS_ACCESS_KEY_ID = os.getenv('AWS_ACCESS_KEY_ID', '')
AWS_SECRET_ACCESS_KEY = os.getenv('AWS_SECRET_ACCESS_KEY', '')
AWS_S3_BUCKET_NAME = os.getenv('AWS_S3_BUCKET_NAME', 'pytalk-recordings')
AWS_S3_REGION = os.getenv('AWS_S3_REGION', 'ap-south-1')

# ==================== CELERY TASK QUEUE ====================
if PRODUCTION:
    CELERY_BROKER_URL = f"redis://{os.getenv('REDIS_HOST', 'localhost')}:{os.getenv('REDIS_PORT', 6379)}/2"
    CELERY_RESULT_BACKEND = f"redis://{os.getenv('REDIS_HOST', 'localhost')}:{os.getenv('REDIS_PORT', 6379)}/3"
else:
    # In development without Redis, execute tasks synchronously in-process
    CELERY_TASK_ALWAYS_EAGER = True
    CELERY_TASK_EAGER_PROPAGATES = True

CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = 'UTC'
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 30  # Hard limit: 30 seconds per task
CELERY_TASK_SOFT_TIME_LIMIT = 25  # Soft limit: raise SoftTimeLimitExceeded

from celery.schedules import crontab  # noqa: E402
CELERY_BEAT_SCHEDULE = {
    'process-recurring-billing': {
        'task': 'billing.tasks.process_recurring_billing',
        'schedule': crontab(hour=6, minute=0),
    },
    'refresh-exchange-rates': {
        'task': 'billing.tasks.refresh_exchange_rates',
        'schedule': crontab(hour='*/6', minute=30),
    },
    'record-daily-usage': {
        'task': 'billing.tasks.record_daily_usage',
        'schedule': crontab(hour=1, minute=0),
    },
}

# ==================== PAYU BILLING ====================
PAYU_POS_ID = os.getenv('PAYU_POS_ID', '')
PAYU_CLIENT_SECRET = os.getenv('PAYU_CLIENT_SECRET', '')
PAYU_SECOND_KEY = os.getenv('PAYU_SECOND_KEY', '')
PAYU_SANDBOX = os.getenv('PAYU_SANDBOX', 'True').lower() == 'true'
PAYU_BASE_URL = 'https://secure.snd.payu.com' if PAYU_SANDBOX else 'https://secure.payu.com'
PAYU_CURRENCY = os.getenv('PAYU_CURRENCY', 'PLN')  # Must match POS currency config
PAYU_ENABLED = bool(PAYU_POS_ID)
SITE_URL = os.getenv('SITE_URL', 'http://localhost:8000')

# ==================== WEBSOCKET SECURITY ====================
WEBSOCKET_ALLOWED_ORIGINS = os.getenv(
    'WEBSOCKET_ALLOWED_ORIGINS',
    'http://localhost:8000,http://127.0.0.1:8000,ws://localhost:8000,ws://127.0.0.1:8000'
).split(',')
