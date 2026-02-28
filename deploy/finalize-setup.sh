#!/bin/bash
# PyTalk Finalize Setup Script
# Run AFTER uploading your code to /opt/pytalk/backend
# Run as: sudo bash finalize-setup.sh [single|multi]
#
# Modes:
#   single (default) — 1 Daphne worker on port 8001
#   multi            — 4 Daphne workers on ports 8001-8004

set -e

MODE="${1:-single}"

echo "=========================================="
echo "PyTalk - Finalizing Production Setup"
echo "Mode: $MODE worker"
echo "=========================================="

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Please run as root (sudo)${NC}"
    exit 1
fi

if [ ! -d "/opt/pytalk/backend" ]; then
    echo -e "${RED}Error: /opt/pytalk/backend not found!${NC}"
    echo "Please upload your code first."
    exit 1
fi

echo -e "${GREEN}Step 1: Setting up environment file...${NC}"
if [ ! -f "/opt/pytalk/backend/.env" ]; then
    if [ -f "/opt/pytalk/deploy/production.env" ]; then
        cp /opt/pytalk/deploy/production.env /opt/pytalk/backend/.env
        chown ubuntu:ubuntu /opt/pytalk/backend/.env
        chmod 600 /opt/pytalk/backend/.env
        echo -e "${YELLOW}Created .env from template. EDIT IT NOW!${NC}"
        echo "Run: sudo nano /opt/pytalk/backend/.env"
        read -p "Press Enter after editing .env to continue..."
    else
        echo -e "${RED}No .env file found! Create one from production.env template${NC}"
        exit 1
    fi
fi

echo -e "${GREEN}Step 2: Installing Python dependencies...${NC}"
cd /opt/pytalk
sudo -u ubuntu /opt/pytalk/venv/bin/pip install --upgrade pip
sudo -u ubuntu /opt/pytalk/venv/bin/pip install -r backend/requirements.txt

echo -e "${GREEN}Step 3: Creating logs directory...${NC}"
mkdir -p /opt/pytalk/backend/logs
chown -R ubuntu:ubuntu /opt/pytalk/backend/logs

echo -e "${GREEN}Step 4: Running database migrations...${NC}"
cd /opt/pytalk/backend
sudo -u ubuntu /opt/pytalk/venv/bin/python manage.py migrate --noinput

echo -e "${GREEN}Step 5: Collecting static files...${NC}"
sudo -u ubuntu /opt/pytalk/venv/bin/python manage.py collectstatic --noinput

echo -e "${GREEN}Step 6: Creating superuser (if needed)...${NC}"
echo "Do you want to create a superuser? (y/n)"
read -r create_superuser
if [ "$create_superuser" = "y" ]; then
    sudo -u ubuntu /opt/pytalk/venv/bin/python manage.py createsuperuser
fi

echo -e "${GREEN}Step 7: Setting permissions...${NC}"
chown -R ubuntu:ubuntu /opt/pytalk
chmod 600 /opt/pytalk/backend/.env

echo -e "${GREEN}Step 8: Installing systemd services...${NC}"
cp /opt/pytalk/deploy/pytalk-celery.service /etc/systemd/system/
cp /opt/pytalk/deploy/pytalk-celery-beat.service /etc/systemd/system/

if [ "$MODE" = "multi" ]; then
    echo -e "${YELLOW}Installing multi-worker template service...${NC}"
    cp /opt/pytalk/deploy/pytalk@.service /etc/systemd/system/
    NGINX_CONF="nginx-multiworker.conf"
else
    echo -e "${YELLOW}Installing single-worker service...${NC}"
    cp /opt/pytalk/deploy/pytalk.service /etc/systemd/system/
    NGINX_CONF="nginx.conf"
fi

systemctl daemon-reload

echo -e "${GREEN}Step 9: Starting services...${NC}"
if [ "$MODE" = "multi" ]; then
    systemctl start pytalk@8001 pytalk@8002 pytalk@8003 pytalk@8004
    systemctl enable pytalk@8001 pytalk@8002 pytalk@8003 pytalk@8004
else
    systemctl start pytalk
    systemctl enable pytalk
fi

systemctl start pytalk-celery
systemctl enable pytalk-celery
systemctl start pytalk-celery-beat
systemctl enable pytalk-celery-beat

echo -e "${GREEN}Step 10: Configuring Nginx...${NC}"
# Remove default site if it exists
rm -f /etc/nginx/sites-enabled/default

# Copy config
cp /opt/pytalk/deploy/$NGINX_CONF /etc/nginx/sites-available/pytalk
ln -sf /etc/nginx/sites-available/pytalk /etc/nginx/sites-enabled/pytalk

echo -e "${YELLOW}IMPORTANT: Edit Nginx config with your domain!${NC}"
echo "Run: sudo nano /etc/nginx/sites-available/pytalk"
read -p "Press Enter after editing nginx config..."

nginx -t && systemctl reload nginx

echo ""
echo -e "${GREEN}=========================================="
echo "Setup Complete! (Mode: $MODE)"
echo "==========================================${NC}"
echo ""

if [ "$MODE" = "multi" ]; then
    echo "Services running:"
    systemctl status pytalk@8001 --no-pager -l | head -5 || true
    systemctl status pytalk@8002 --no-pager -l | head -5 || true
    systemctl status pytalk@8003 --no-pager -l | head -5 || true
    systemctl status pytalk@8004 --no-pager -l | head -5 || true
else
    echo "Services running:"
    systemctl status pytalk --no-pager -l | head -5 || true
fi

systemctl status pytalk-celery --no-pager -l | head -5 || true
systemctl status pytalk-celery-beat --no-pager -l | head -5 || true

echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo "1. Set up SSL: sudo certbot --nginx -d pytalk.veriright.com"
echo "2. Configure AWS Security Group to allow ports 80 and 443"
echo "3. Test your application at https://pytalk.veriright.com"
echo ""
echo "Useful commands:"
if [ "$MODE" = "multi" ]; then
    echo "  View logs:  journalctl -u pytalk@8001 -f"
    echo "  Restart:    systemctl restart pytalk@8001 pytalk@8002 pytalk@8003 pytalk@8004 pytalk-celery pytalk-celery-beat"
    echo "  Status:     systemctl status pytalk@8001 pytalk@8002 pytalk@8003 pytalk@8004"
else
    echo "  View logs:  journalctl -u pytalk -f"
    echo "  Restart:    systemctl restart pytalk pytalk-celery pytalk-celery-beat"
    echo "  Status:     systemctl status pytalk pytalk-celery pytalk-celery-beat"
fi
