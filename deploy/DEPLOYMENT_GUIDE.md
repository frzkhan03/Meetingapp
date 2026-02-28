# PyTalk Production Deployment Guide

## Overview

Deploy PyTalk to an AWS EC2 instance running Ubuntu 24.04 LTS.

## Architecture

### Single Worker (default)

```
                    Client
                      │
                    Nginx (80/443)
                      │
                    Daphne (8001)
                      │
         ┌────────────┼────────────┐
      Redis       PostgreSQL     Celery
```

### Multi-Worker (recommended for 2GB+ RAM)

```
                    Client
                      │
                    Nginx (80/443)
                      │
          ┌───────┬───┴───┬───────┐
        Daphne  Daphne  Daphne  Daphne
        :8001   :8002   :8003   :8004
          └───────┴───┬───┴───────┘
                      │
         ┌────────────┼────────────┐
      Redis       PostgreSQL     Celery
```

---

## Quick Start

### 1. Connect to EC2

```bash
ssh -i your-key.pem ubuntu@your-ec2-ip
```

### 2. Run Base Setup

```bash
sudo bash /tmp/setup-ec2.sh
```

### 3. Upload Code

```bash
# From local machine
scp -i your-key.pem -r backend/ ubuntu@your-ec2-ip:/opt/pytalk/
scp -i your-key.pem -r deploy/ ubuntu@your-ec2-ip:/opt/pytalk/
```

### 4. Configure Environment

```bash
sudo cp /opt/pytalk/deploy/production.env /opt/pytalk/backend/.env
sudo nano /opt/pytalk/backend/.env
```

### 5. Finalize Setup

```bash
# Single worker (default)
sudo bash /opt/pytalk/deploy/finalize-setup.sh

# Multi-worker (4 Daphne instances)
sudo bash /opt/pytalk/deploy/finalize-setup.sh multi
```

### 6. Set Up SSL

```bash
sudo certbot --nginx -d pytalk.veriright.com
```

---

## Switching from Single to Multi-Worker

If you're already running single-worker and want to upgrade:

```bash
# 1. Stop single-worker service
sudo systemctl stop pytalk
sudo systemctl disable pytalk

# 2. Install template service
sudo cp /opt/pytalk/deploy/pytalk@.service /etc/systemd/system/
sudo systemctl daemon-reload

# 3. Start 4 workers
sudo systemctl start pytalk@8001 pytalk@8002 pytalk@8003 pytalk@8004
sudo systemctl enable pytalk@8001 pytalk@8002 pytalk@8003 pytalk@8004

# 4. Update nginx to multi-worker config
sudo cp /opt/pytalk/deploy/nginx-multiworker.conf /etc/nginx/sites-available/pytalk
sudo nginx -t && sudo systemctl reload nginx

# 5. Verify
sudo systemctl status pytalk@8001 pytalk@8002 pytalk@8003 pytalk@8004
curl -I https://pytalk.veriright.com
```

---

## Deploy Config Files

| File | Purpose |
|------|---------|
| `pytalk.service` | Single Daphne worker on port 8001 |
| `pytalk@.service` | Template unit for multi-worker (ports via %i) |
| `pytalk-celery.service` | Celery task worker (2 concurrency) |
| `pytalk-celery-beat.service` | Celery beat scheduler |
| `nginx.conf` | Nginx config — single worker + SSL |
| `nginx-multiworker.conf` | Nginx config — 4 workers + SSL |
| `nginx-ip-only.conf` | Nginx config — IP only, no SSL |
| `setup-ec2.sh` | Base Ubuntu setup (packages, DB, Redis) |
| `finalize-setup.sh` | App setup (deps, migrate, services) |
| `setup-swap.sh` | Add 1GB swap space |
| `ssl-setup.sh` | Let's Encrypt SSL setup |
| `health-check.py` | Health check script |
| `quick-commands.sh` | Shell aliases for common ops |

---

## Common Commands

```bash
# Status
sudo systemctl status pytalk pytalk-celery pytalk-celery-beat

# Restart all
sudo systemctl restart pytalk pytalk-celery pytalk-celery-beat

# Logs
journalctl -u pytalk -f
journalctl -u pytalk-celery -f

# Multi-worker logs
journalctl -u pytalk@8001 -f

# Update code
cd /opt/pytalk && git pull
cd backend
/opt/pytalk/venv/bin/pip install -r requirements.txt
/opt/pytalk/venv/bin/python manage.py migrate
/opt/pytalk/venv/bin/python manage.py collectstatic --noinput
sudo systemctl restart pytalk pytalk-celery pytalk-celery-beat

# Backup database
sudo -u postgres pg_dump pytalk > /tmp/pytalk_backup_$(date +%Y%m%d).sql
```

---

## Troubleshooting

### 502 Bad Gateway
```bash
sudo systemctl status pytalk
journalctl -u pytalk -n 50
```

### Disk full
```bash
df -h /
sudo du -sh /var/log/pytalk/*   # Check log sizes
sudo truncate -s 0 /var/log/pytalk/*.log
sudo apt-get clean
sudo journalctl --vacuum-size=50M
```

### Static files not loading
```bash
cd /opt/pytalk/backend
/opt/pytalk/venv/bin/python manage.py collectstatic --noinput
sudo systemctl restart nginx
```

### Database connection failed
```bash
# Test PostgreSQL connection
sudo -u postgres psql -c "\l"

# Check if pytalk database exists
sudo -u postgres psql -c "SELECT datname FROM pg_database WHERE datname='pytalk';"
```

### Redis connection failed
```bash
redis-cli ping
# Should return: PONG
```

### WebSocket connection fails
1. Check Nginx WebSocket configuration
2. Verify `WEBSOCKET_ALLOWED_ORIGINS` in `.env`
3. Check browser console for specific errors

### Out of memory
```bash
free -m
ps aux --sort=-%mem | head -10
# Add swap if needed
sudo bash /opt/pytalk/deploy/setup-swap.sh
```

---

## Security Recommendations

1. **Keep system updated**: `sudo apt-get update && sudo apt-get upgrade -y`
2. **Use fail2ban**: Protect against brute force SSH/login attempts
3. **Enable AWS CloudWatch**: Monitor CPU, memory, and disk resources
4. **Regular backups**: Automate database backups to S3
5. **Review security logs**: `/opt/pytalk/backend/logs/security.log`
6. **Rotate secrets**: Periodically update SECRET_KEY and ENCRYPTION_KEY

---

## Scaling Beyond Current Instance

When you need more capacity:

1. **Vertical Scaling**: Upgrade to t3.medium (4GB) or t3.large (8GB)
2. **Multi-Worker**: Use `pytalk@.service` template for 4+ Daphne workers
3. **Database**: Move to AWS RDS PostgreSQL (offloads DB from EC2)
4. **Cache**: Move to AWS ElastiCache Redis (offloads Redis from EC2)
5. **Load Balancing**: Add Application Load Balancer for multiple instances
6. **Auto Scaling**: Use Auto Scaling Groups for horizontal scaling
