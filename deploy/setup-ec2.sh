#!/bin/bash
# PyTalk EC2 Setup Script for Ubuntu 24.04 LTS
# Run as: sudo bash setup-ec2.sh

set -e

echo "=========================================="
echo "PyTalk EC2 Production Setup Script"
echo "=========================================="

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Please run as root (sudo)${NC}"
    exit 1
fi

echo -e "${GREEN}Step 1: Updating system packages...${NC}"
apt-get update && apt-get upgrade -y

echo -e "${GREEN}Step 2: Installing required packages...${NC}"
apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    python3-dev \
    nginx \
    redis-server \
    postgresql \
    postgresql-contrib \
    libpq-dev \
    git \
    gcc \
    libffi-dev \
    libssl-dev \
    certbot \
    python3-certbot-nginx

echo -e "${GREEN}Step 3: Setting up PostgreSQL...${NC}"
systemctl start postgresql
systemctl enable postgresql

sudo -u postgres psql -c "CREATE USER pytalk WITH PASSWORD 'CHANGE_ME_secure_password';" 2>/dev/null || true
sudo -u postgres psql -c "CREATE DATABASE pytalk OWNER pytalk;" 2>/dev/null || true
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE pytalk TO pytalk;" 2>/dev/null || true

echo -e "${GREEN}Step 4: Setting up Redis...${NC}"
# Configure Redis for production use
cat > /etc/redis/redis-pytalk.conf << 'EOF'
# PyTalk Redis overrides (loaded after default config)
maxmemory 256mb
maxmemory-policy volatile-lru
databases 4
EOF

# Include overrides in main config if not already present
if ! grep -q 'redis-pytalk.conf' /etc/redis/redis.conf 2>/dev/null; then
    echo 'include /etc/redis/redis-pytalk.conf' >> /etc/redis/redis.conf
fi

systemctl start redis-server
systemctl enable redis-server

echo -e "${GREEN}Step 5: Creating directories...${NC}"
mkdir -p /opt/pytalk
mkdir -p /var/log/pytalk

# Set permissions for ubuntu user
chown -R ubuntu:ubuntu /opt/pytalk
chown -R ubuntu:ubuntu /var/log/pytalk

echo -e "${GREEN}Step 6: Setting up Python virtual environment...${NC}"
cd /opt/pytalk
sudo -u ubuntu python3 -m venv venv

echo -e "${GREEN}Step 7: Setting up log rotation...${NC}"
cat > /etc/logrotate.d/pytalk << 'EOF'
/var/log/pytalk/*.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    maxsize 50M
    copytruncate
}
EOF

echo -e "${GREEN}Step 8: Capping journal size...${NC}"
mkdir -p /etc/systemd/journald.conf.d
cat > /etc/systemd/journald.conf.d/size.conf << 'EOF'
[Journal]
SystemMaxUse=100M
EOF
systemctl restart systemd-journald

echo -e "${GREEN}Step 9: Setting up Nginx...${NC}"
systemctl start nginx
systemctl enable nginx

echo ""
echo -e "${GREEN}=========================================="
echo "Base system setup complete!"
echo "==========================================${NC}"
echo ""
echo "System services installed:"
echo "  - PostgreSQL (running on port 5432)"
echo "  - Redis (running on port 6379)"
echo "  - Nginx (running on ports 80/443)"
echo "  - Python 3 with venv at /opt/pytalk/venv"
echo ""
echo -e "${YELLOW}NEXT STEPS:${NC}"
echo "  1. Upload your code to /opt/pytalk/backend"
echo "  2. Run: sudo bash /opt/pytalk/deploy/finalize-setup.sh"
echo ""
