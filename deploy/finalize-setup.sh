#!/bin/bash
# PyTalk Finalize Setup Script
# Run AFTER uploading your code to /opt/pytalk/backend
# Run as: sudo bash finalize-setup.sh

set -e

echo "=========================================="
echo "PyTalk - Finalizing Production Setup"
echo "=========================================="

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Please run as root (sudo)${NC}"
    exit 1
fi

# Check if backend directory exists
if [ ! -d "/opt/pytalk/backend" ]; then
    echo -e "${RED}Error: /opt/pytalk/backend not found!${NC}"
    echo "Please upload your code first."
    exit 1
fi

echo -e "${GREEN}Step 1: Setting up environment file...${NC}"
if [ ! -f "/opt/pytalk/backend/.env" ]; then
    if [ -f "/opt/pytalk/deploy/production.env" ]; then
        cp /opt/pytalk/deploy/production.env /opt/pytalk/backend/.env
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
source venv/bin/activate
pip install --upgrade pip
pip install -r backend/requirements.txt

echo -e "${GREEN}Step 3: Creating logs directory...${NC}"
mkdir -p /opt/pytalk/backend/logs
chown -R pytalk:pytalk /opt/pytalk/backend/logs

echo -e "${GREEN}Step 4: Running database migrations...${NC}"
cd /opt/pytalk/backend
sudo -u pytalk /opt/pytalk/venv/bin/python manage.py migrate --noinput

echo -e "${GREEN}Step 5: Collecting static files...${NC}"
sudo -u pytalk /opt/pytalk/venv/bin/python manage.py collectstatic --noinput

echo -e "${GREEN}Step 6: Creating superuser (if needed)...${NC}"
echo "Do you want to create a superuser? (y/n)"
read -r create_superuser
if [ "$create_superuser" = "y" ]; then
    sudo -u pytalk /opt/pytalk/venv/bin/python manage.py createsuperuser
fi

echo -e "${GREEN}Step 7: Setting permissions...${NC}"
chown -R pytalk:pytalk /opt/pytalk
chmod 600 /opt/pytalk/backend/.env

echo -e "${GREEN}Step 8: Installing systemd services...${NC}"
cp /opt/pytalk/deploy/pytalk.service /etc/systemd/system/
cp /opt/pytalk/deploy/pytalk-celery.service /etc/systemd/system/
systemctl daemon-reload

echo -e "${GREEN}Step 9: Starting services...${NC}"
systemctl start pytalk
systemctl enable pytalk
systemctl start pytalk-celery
systemctl enable pytalk-celery

echo -e "${GREEN}Step 10: Configuring Nginx...${NC}"
# Backup default config
if [ -f /etc/nginx/conf.d/default.conf ]; then
    mv /etc/nginx/conf.d/default.conf /etc/nginx/conf.d/default.conf.bak
fi

# Copy PyTalk nginx config
cp /opt/pytalk/deploy/nginx.conf /etc/nginx/conf.d/pytalk.conf

echo -e "${YELLOW}IMPORTANT: Edit Nginx config with your domain!${NC}"
echo "Run: sudo nano /etc/nginx/conf.d/pytalk.conf"
echo "Replace 'your-domain.com' with your actual domain or EC2 public IP"
read -p "Press Enter after editing nginx config..."

# Test nginx config
nginx -t
systemctl reload nginx

echo ""
echo -e "${GREEN}=========================================="
echo "Setup Complete!"
echo "==========================================${NC}"
echo ""
echo "Services status:"
systemctl status pytalk --no-pager -l || true
systemctl status pytalk-celery --no-pager -l || true
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo "1. Set up SSL certificate (see ssl-setup.sh)"
echo "2. Configure AWS Security Group to allow ports 80 and 443"
echo "3. Point your domain DNS to the EC2 public IP"
echo "4. Test your application at https://your-domain.com"
echo ""
echo "Useful commands:"
echo "  View logs: sudo journalctl -u pytalk -f"
echo "  Restart: sudo systemctl restart pytalk pytalk-celery"
echo "  Status: sudo systemctl status pytalk pytalk-celery"
