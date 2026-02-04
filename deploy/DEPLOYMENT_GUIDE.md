# PyTalk Production Deployment Guide

## Overview

This guide covers deploying PyTalk to an AWS EC2 t3.micro instance running Amazon Linux 2023.

## Architecture

```
                    ┌─────────────┐
                    │   Client    │
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │   Nginx     │ (Port 80/443)
                    │  (Reverse   │
                    │   Proxy)    │
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │   Daphne    │ (Port 8001)
                    │   (ASGI)    │
                    └──────┬──────┘
                           │
         ┌─────────────────┼─────────────────┐
         │                 │                 │
    ┌────▼────┐      ┌─────▼─────┐     ┌─────▼─────┐
    │  Redis  │      │PostgreSQL │     │  Celery   │
    │ (Cache) │      │   (DB)    │     │ (Tasks)   │
    └─────────┘      └───────────┘     └───────────┘
```

## Memory Allocation (t3.micro - 1GB RAM)

| Component    | Memory  | Notes                          |
|-------------|---------|--------------------------------|
| OS/System   | ~200MB  | Amazon Linux overhead          |
| PostgreSQL  | ~200MB  | Can use RDS instead            |
| Redis       | ~100MB  | Can use ElastiCache instead    |
| Daphne      | ~400MB  | Django + WebSockets            |
| Celery      | ~150MB  | 2 workers                      |
| **Total**   | ~1050MB | Slightly over 1GB!             |

**Recommendation**: For reliable production use, either:
1. Use AWS RDS (PostgreSQL) and ElastiCache (Redis) - saves ~300MB
2. Upgrade to t3.small (2GB RAM)

---

## Pre-Deployment Checklist

### AWS Setup
- [ ] EC2 t3.micro instance created with Amazon Linux 2023
- [ ] Key pair (.pem file) downloaded
- [ ] Security Group configured:
  - SSH (22) - Your IP only
  - HTTP (80) - 0.0.0.0/0
  - HTTPS (443) - 0.0.0.0/0
- [ ] Elastic IP attached (optional but recommended)
- [ ] Domain DNS configured (if using custom domain)

### Local Preparation
- [ ] Code tested locally
- [ ] `.env.example` values reviewed
- [ ] All migrations created

---

## Step-by-Step Deployment

### Step 1: Connect to EC2

```bash
# Make key readable only by you
chmod 400 your-key.pem

# Connect to EC2
ssh -i your-key.pem ec2-user@your-ec2-public-ip
```

### Step 2: Run Base Setup Script

```bash
# Download or create the setup script
sudo curl -o /tmp/setup-ec2.sh https://raw.githubusercontent.com/your-repo/deploy/setup-ec2.sh

# Or copy from local machine:
# scp -i your-key.pem deploy/setup-ec2.sh ec2-user@your-ec2-ip:/tmp/

# Run the script
sudo bash /tmp/setup-ec2.sh
```

This installs:
- Python 3.11
- PostgreSQL 15
- Redis 6
- Nginx
- Required system libraries

### Step 3: Upload Your Code

**Option A: Using SCP**
```bash
# From your local machine (Windows/Linux/Mac)
scp -i your-key.pem -r backend/ ec2-user@your-ec2-ip:/tmp/
scp -i your-key.pem -r deploy/ ec2-user@your-ec2-ip:/tmp/

# On EC2
sudo mv /tmp/backend /opt/pytalk/
sudo mv /tmp/deploy /opt/pytalk/
sudo chown -R pytalk:pytalk /opt/pytalk
```

**Option B: Using Git**
```bash
# On EC2
cd /opt/pytalk
sudo -u pytalk git clone https://github.com/your-username/pytalk.git .
```

### Step 4: Configure Environment

```bash
# Copy and edit the environment file
sudo cp /opt/pytalk/deploy/production.env /opt/pytalk/backend/.env
sudo nano /opt/pytalk/backend/.env
```

**Critical settings to change:**
```env
SECRET_KEY=<generate with: python -c "import secrets; print(secrets.token_urlsafe(50))">
ALLOWED_HOSTS=your-domain.com,your-ec2-public-ip
DB_PASSWORD=<your secure password>
ENCRYPTION_KEY=<generate with: python -c "import secrets; print(secrets.token_urlsafe(32))">
CSRF_TRUSTED_ORIGINS=https://your-domain.com
WEBSOCKET_ALLOWED_ORIGINS=https://your-domain.com,wss://your-domain.com
```

### Step 5: Update Database Password

```bash
# Set the same password you used in .env
sudo -u postgres psql -c "ALTER USER pytalk PASSWORD 'your-secure-password';"
```

### Step 6: Finalize Setup

```bash
sudo bash /opt/pytalk/deploy/finalize-setup.sh
```

This will:
- Install Python dependencies
- Run database migrations
- Collect static files
- Install and start systemd services
- Configure Nginx

### Step 7: Configure Nginx

```bash
sudo nano /etc/nginx/conf.d/pytalk.conf
```

Replace all instances of `your-domain.com` with your actual domain or EC2 public IP.

For **IP-only access** (no domain), use a simpler config:
```nginx
server {
    listen 80;
    server_name _;

    location /static/ {
        alias /opt/pytalk/backend/staticfiles/;
    }

    location /ws/ {
        proxy_pass http://127.0.0.1:8001;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 86400;
    }

    location / {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Reload Nginx:
```bash
sudo nginx -t && sudo systemctl reload nginx
```

### Step 8: Set Up SSL (If Using Domain)

```bash
sudo bash /opt/pytalk/deploy/ssl-setup.sh your-domain.com your-email@example.com
```

---

## Verification

### Check Service Status
```bash
sudo systemctl status pytalk
sudo systemctl status pytalk-celery
sudo systemctl status redis6
sudo systemctl status postgresql
sudo systemctl status nginx
```

### View Logs
```bash
# Daphne logs
sudo journalctl -u pytalk -f

# Celery logs
sudo journalctl -u pytalk-celery -f

# Application logs
sudo tail -f /opt/pytalk/backend/logs/security.log

# Nginx logs
sudo tail -f /var/log/nginx/pytalk_error.log
```

### Test the Application
```bash
# Test HTTP
curl http://your-ec2-ip/

# Test WebSocket (basic connectivity)
curl -i -N -H "Connection: Upgrade" \
     -H "Upgrade: websocket" \
     -H "Sec-WebSocket-Version: 13" \
     -H "Sec-WebSocket-Key: test" \
     http://your-ec2-ip/ws/room/test/
```

---

## Common Issues & Solutions

### Issue: 502 Bad Gateway
**Cause**: Daphne not running or wrong port
```bash
sudo systemctl status pytalk
sudo journalctl -u pytalk -n 50
```

### Issue: Static files not loading
```bash
cd /opt/pytalk/backend
sudo -u pytalk /opt/pytalk/venv/bin/python manage.py collectstatic --noinput
sudo systemctl restart nginx
```

### Issue: Database connection failed
```bash
# Test PostgreSQL connection
sudo -u postgres psql -c "\l"

# Check if pytalk database exists
sudo -u postgres psql -c "SELECT datname FROM pg_database WHERE datname='pytalk';"
```

### Issue: Redis connection failed
```bash
redis-cli ping
# Should return: PONG
```

### Issue: WebSocket connection fails
1. Check Nginx WebSocket configuration
2. Verify `WEBSOCKET_ALLOWED_ORIGINS` in `.env`
3. Check browser console for specific errors

### Issue: Out of Memory
```bash
# Check memory usage
free -m

# Check what's using memory
top -o %MEM

# Consider using swap
sudo dd if=/dev/zero of=/swapfile bs=128M count=8
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile swap swap defaults 0 0' | sudo tee -a /etc/fstab
```

---

## Maintenance Commands

### Restart Services
```bash
sudo systemctl restart pytalk pytalk-celery
```

### Update Code
```bash
cd /opt/pytalk
sudo -u pytalk git pull

# Reinstall dependencies if requirements.txt changed
sudo -u pytalk /opt/pytalk/venv/bin/pip install -r backend/requirements.txt

# Run migrations
cd backend
sudo -u pytalk /opt/pytalk/venv/bin/python manage.py migrate

# Collect static files
sudo -u pytalk /opt/pytalk/venv/bin/python manage.py collectstatic --noinput

# Restart services
sudo systemctl restart pytalk pytalk-celery
```

### Backup Database
```bash
sudo -u postgres pg_dump pytalk > /tmp/pytalk_backup_$(date +%Y%m%d).sql
```

### View Active Connections
```bash
# Redis connections
redis-cli INFO clients

# PostgreSQL connections
sudo -u postgres psql -c "SELECT count(*) FROM pg_stat_activity WHERE datname='pytalk';"
```

---

## Security Recommendations

1. **Keep system updated**: `sudo dnf update -y`
2. **Use fail2ban**: Protect against brute force
3. **Enable AWS CloudWatch**: Monitor resources
4. **Regular backups**: Automate database backups to S3
5. **Review security logs**: `/opt/pytalk/backend/logs/security.log`
6. **Rotate secrets**: Periodically update SECRET_KEY and ENCRYPTION_KEY

---

## Scaling Beyond t3.micro

When you outgrow t3.micro:

1. **Vertical Scaling**: Upgrade to t3.small (2GB) or t3.medium (4GB)
2. **Database**: Move to AWS RDS PostgreSQL
3. **Cache**: Move to AWS ElastiCache Redis
4. **Load Balancing**: Add Application Load Balancer
5. **Auto Scaling**: Use Auto Scaling Groups for multiple instances
