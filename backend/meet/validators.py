"""
Input Validation and Sanitization utilities for PyTalk
Provides XSS protection, input validation, and data sanitization.
"""

import re
import html
import bleach
from django.core.exceptions import ValidationError
from django.core.validators import validate_email as django_validate_email


# Allowed HTML tags and attributes for rich text (if needed)
ALLOWED_TAGS = ['p', 'br', 'b', 'i', 'u', 'strong', 'em', 'a', 'ul', 'ol', 'li']
ALLOWED_ATTRIBUTES = {
    'a': ['href', 'title'],
}


def sanitize_html(text, allow_tags=None):
    """
    Sanitize HTML content to prevent XSS attacks.

    Args:
        text: Input text that may contain HTML
        allow_tags: List of allowed HTML tags (default: strip all)

    Returns:
        Sanitized text
    """
    if not text:
        return ''

    if allow_tags is None:
        # Strip all HTML by default
        return bleach.clean(text, tags=[], strip=True)

    return bleach.clean(
        text,
        tags=allow_tags,
        attributes=ALLOWED_ATTRIBUTES,
        strip=True
    )


def escape_html(text):
    """
    Escape HTML special characters.
    Use this for displaying user input in templates.
    """
    if not text:
        return ''
    return html.escape(str(text))


def sanitize_input(text, max_length=None, strip=True):
    """
    General input sanitization.
    Removes HTML, trims whitespace, and validates length.

    Args:
        text: Input text
        max_length: Maximum allowed length
        strip: Whether to strip whitespace

    Returns:
        Sanitized text
    """
    if not text:
        return ''

    # Convert to string
    text = str(text)

    # Strip whitespace
    if strip:
        text = text.strip()

    # Remove HTML
    text = sanitize_html(text)

    # Enforce max length
    if max_length and len(text) > max_length:
        text = text[:max_length]

    return text


def validate_username(username):
    """
    Validate username format.

    Rules:
    - 3-30 characters
    - Alphanumeric, underscores, hyphens, and dots allowed
    - Must start with alphanumeric
    - No consecutive special characters
    """
    if not username:
        raise ValidationError('Username is required')

    username = str(username).strip()

    if len(username) < 3:
        raise ValidationError('Username must be at least 3 characters')

    if len(username) > 30:
        raise ValidationError('Username cannot exceed 30 characters')

    if not re.match(r'^[a-zA-Z0-9]', username):
        raise ValidationError('Username must start with a letter or number')

    if not re.match(r'^[a-zA-Z0-9][a-zA-Z0-9._-]*[a-zA-Z0-9]$|^[a-zA-Z0-9]$', username):
        raise ValidationError('Username can only contain letters, numbers, dots, underscores, and hyphens')

    if re.search(r'[._-]{2,}', username):
        raise ValidationError('Username cannot have consecutive special characters')

    # Check for reserved/blacklisted usernames
    blacklisted = ['admin', 'root', 'system', 'moderator', 'administrator', 'null', 'undefined']
    if username.lower() in blacklisted:
        raise ValidationError('This username is not available')

    return username


def validate_email(email):
    """
    Validate email format using Django's validator plus additional checks.
    """
    if not email:
        raise ValidationError('Email is required')

    email = str(email).strip().lower()

    # Use Django's built-in validator
    try:
        django_validate_email(email)
    except ValidationError:
        raise ValidationError('Invalid email address')

    # Additional checks
    if len(email) > 254:
        raise ValidationError('Email address is too long')

    # Check for suspicious patterns
    suspicious_patterns = [
        r'\.{2,}',  # Multiple dots
        r'@.*@',    # Multiple @ signs
    ]

    for pattern in suspicious_patterns:
        if re.search(pattern, email):
            raise ValidationError('Invalid email address')

    return email


def validate_password_strength(password):
    """
    Validate password strength beyond Django's default validators.

    Requirements:
    - At least 10 characters
    - At least one uppercase letter
    - At least one lowercase letter
    - At least one digit
    - At least one special character
    """
    if not password:
        raise ValidationError('Password is required')

    errors = []

    if len(password) < 10:
        errors.append('Password must be at least 10 characters long')

    if not re.search(r'[A-Z]', password):
        errors.append('Password must contain at least one uppercase letter')

    if not re.search(r'[a-z]', password):
        errors.append('Password must contain at least one lowercase letter')

    if not re.search(r'\d', password):
        errors.append('Password must contain at least one digit')

    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        errors.append('Password must contain at least one special character')

    # Check for common patterns
    common_patterns = [
        r'123456',
        r'password',
        r'qwerty',
        r'abc123',
    ]

    for pattern in common_patterns:
        if re.search(pattern, password.lower()):
            errors.append('Password contains a common pattern')
            break

    if errors:
        raise ValidationError(errors)

    return password


def validate_organization_name(name):
    """Validate organization name"""
    if not name:
        raise ValidationError('Organization name is required')

    name = sanitize_input(name, max_length=255)

    if len(name) < 2:
        raise ValidationError('Organization name must be at least 2 characters')

    if len(name) > 255:
        raise ValidationError('Organization name is too long')

    return name


def validate_meeting_name(name):
    """Validate meeting name"""
    if not name:
        raise ValidationError('Meeting name is required')

    name = sanitize_input(name, max_length=255)

    if len(name) < 3:
        raise ValidationError('Meeting name must be at least 3 characters')

    return name


def validate_chat_message(message):
    """
    Validate and sanitize chat messages.
    Prevents XSS while allowing basic formatting.
    """
    if not message:
        return ''

    # Sanitize but keep basic formatting
    message = sanitize_html(message, allow_tags=['b', 'i', 'u'])

    # Limit length
    if len(message) > 2000:
        message = message[:2000]

    return message


def is_safe_url(url, allowed_hosts=None):
    """
    Check if a URL is safe for redirects.
    Prevents open redirect vulnerabilities.
    """
    if not url:
        return False

    # Parse URL
    from urllib.parse import urlparse

    try:
        parsed = urlparse(url)
    except Exception:
        return False

    # Allow relative URLs
    if not parsed.netloc:
        # Must start with /
        return url.startswith('/')

    # Check against allowed hosts
    if allowed_hosts is None:
        from django.conf import settings
        allowed_hosts = settings.ALLOWED_HOSTS

    return parsed.netloc in allowed_hosts


def validate_file_upload(file, allowed_extensions=None, max_size_mb=5):
    """
    Validate file uploads for security.

    Args:
        file: Uploaded file object
        allowed_extensions: List of allowed extensions (e.g., ['.jpg', '.png'])
        max_size_mb: Maximum file size in megabytes
    """
    if not file:
        raise ValidationError('No file provided')

    # Check file size
    max_size_bytes = max_size_mb * 1024 * 1024
    if file.size > max_size_bytes:
        raise ValidationError(f'File size cannot exceed {max_size_mb}MB')

    # Check extension
    if allowed_extensions:
        import os
        ext = os.path.splitext(file.name)[1].lower()
        if ext not in allowed_extensions:
            raise ValidationError(f'File type not allowed. Allowed: {", ".join(allowed_extensions)}')

    # Check content type vs extension mismatch
    import mimetypes
    guessed_type = mimetypes.guess_type(file.name)[0]
    if guessed_type and file.content_type != guessed_type:
        raise ValidationError('File type mismatch detected')

    return True
