# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

PyTalk is a multi-tenant video conferencing application (like Google Meet) built with Django, Django Channels (WebSockets), and native WebRTC. The frontend is server-rendered Django templates with vanilla JavaScript — there is no separate frontend framework or build step.

## Development Commands

All commands run from `backend/`:

```bash
# Activate virtual environment
# Windows: venv\Scripts\activate
# Linux/Mac: source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run migrations
python manage.py migrate

# Start dev server (uses Daphne via ASGI for WebSocket support)
python manage.py runserver 3000

# Create superuser for admin access
python manage.py createsuperuser

# Collect static files (production)
python manage.py collectstatic --noinput
```

There are no tests configured in this project currently.

## Architecture

### Django Project Structure

- **`meet/`** — Django project package (settings, root URLs, ASGI/WSGI, Celery config, custom middleware)
- **`users/`** — Authentication, organizations, memberships, tenant middleware
- **`meetings/`** — Meeting CRUD, WebSocket consumers, recordings, transcripts, breakout rooms
- **`billing/`** — Subscription plans, PayU payments, invoices, usage tracking, currency conversion
- **`compliance/`** — SOC 2 audit trail, data retention, GDPR deletion requests, privacy policy

### Multi-Tenant Model

Tenant isolation uses a shared PostgreSQL database with organization-scoped queries. `users.middleware.TenantMiddleware` injects the current organization into requests. Users can belong to multiple organizations with roles (Owner, Admin, Member).

### Real-Time Communication

- **WebSocket consumers** in `meetings/consumers.py`: `RoomConsumer` (video room signaling, chat, whiteboard) and `UserConsumer` (user-level notifications like join approvals)
- **WebSocket routing** in `meetings/routing.py` — room IDs follow pattern `xxx-xxxx-xxx` with optional breakout suffix
- **ASGI stack** in `meet/asgi.py`: `ProtocolTypeRouter` → `WebSocketSecurityMiddleware` → `WebSocketRateLimiter` → `AuthMiddlewareStack` → URL router
- Video uses native WebRTC (not PeerJS) with TURN server support configured via env vars

### Middleware Chain (order matters)

SecurityHeaders → Django Security → WhiteNoise → RateLimit → Session → Common → CSRF → Auth → SessionSecurity → Messages → Clickjacking → TenantMiddleware → SubscriptionMiddleware → SecurityLogging → AuditTrail

### Background Tasks

Celery handles async tasks (billing, compliance, usage recording). In development, `CELERY_TASK_ALWAYS_EAGER = True` runs tasks synchronously. Production uses Redis as broker. Beat schedule defined in `meet/settings.py`.

### Key Environment Variables

Database: `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`
Mode: `DEBUG`, `PRODUCTION`, `SECRET_KEY`
WebRTC: `TURN_SERVER_URL`, `TURN_SERVER_USERNAME`, `TURN_SERVER_CREDENTIAL`
Payments: `PAYU_POS_ID`, `PAYU_CLIENT_SECRET`, `PAYU_SECOND_KEY`, `PAYU_SANDBOX`
Storage: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_S3_BUCKET_NAME`
Redis: `REDIS_HOST`, `REDIS_PORT`

### Frontend

All UI is in `backend/templates/` (Django templates) and `backend/static/` (CSS/JS). The main meeting room logic is in `static/js/script.js`. Design system specs live in `design-system/pytalk/MASTER.md` — dark theme with colors `#0F0F23` primary, `#E11D48` accent, Plus Jakarta Sans font.

### Deployment

- Production runs on AWS EC2 with Daphne (ASGI server), Nginx reverse proxy, PostgreSQL, Redis
- CI/CD via GitHub Actions (`.github/workflows/deploy.yml`) — pushes to `main` auto-deploy via SSH
- Multi-worker support: `deploy/pytalk@.service` template runs multiple Daphne instances on ports 8001-8004
- Admin URL is configurable via `ADMIN_URL` env var (default: `secure-admin/`)
