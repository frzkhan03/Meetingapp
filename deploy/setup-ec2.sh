#!/bin/bash
# PyTalk EC2 Setup Script for Amazon Linux 2023
# Run as: sudo bash setup-ec2.sh

set -e  # Exit on any error

echo "=========================================="
echo "PyTalk EC2 Production Setup Script"
echo "=========================================="

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Please run as root (sudo)${NC}"
    exit 1
fi

echo -e "${GREEN}Step 1: Updating system packages...${NC}"
dnf update -y

echo -e "${GREEN}Step 2: Installing required packages...${NC}"
dnf install -y \
    python3.11 \
    python3.11-pip \
    python3.11-devel \
    nginx \
    redis6 \
    postgresql15-server \
    postgresql15-devel \
    git \
    gcc \
    libffi-devel \
    openssl-devel

echo -e "${GREEN}Step 3: Setting up PostgreSQL...${NC}"
# Initialize PostgreSQL if not already done
if [ ! -f /var/lib/pgsql/data/PG_VERSION ]; then
    postgresql-setup --initdb
fi

# Start and enable PostgreSQL
systemctl start postgresql
systemctl enable postgresql

# Create database and user
sudo -u postgres psql -c "CREATE USER pytalk WITH PASSWORD 'CHANGE_ME_secure_password';" 2>/dev/null || true
sudo -u postgres psql -c "CREATE DATABASE pytalk OWNER pytalk;" 2>/dev/null || true
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE pytalk TO pytalk;" 2>/dev/null || true

echo -e "${GREEN}Step 4: Setting up Redis...${NC}"
# Configure Redis for low memory usage (t3.micro optimization)
cat > /etc/redis6/redis6.conf << 'EOF'
bind 127.0.0.1
port 6379
daemonize no
supervised systemd
loglevel notice
logfile /var/log/redis/redis.log
databases 4
save 900 1
save 300 10
save 60 10000
stop-writes-on-bgsave-error yes
rdbcompression yes
rdbchecksum yes
dbfilename dump.rdb
dir /var/lib/redis6
maxmemory 100mb
maxmemory-policy allkeys-lru
EOF

systemctl start redis6
systemctl enable redis6

echo -e "${GREEN}Step 5: Creating pytalk user and directories...${NC}"
# Create pytalk user if not exists
id -u pytalk &>/dev/null || useradd -r -s /bin/false pytalk

# Create directories
mkdir -p /opt/pytalk
mkdir -p /var/log/pytalk
mkdir -p /var/www/certbot

# Set permissions
chown -R pytalk:pytalk /opt/pytalk
chown -R pytalk:pytalk /var/log/pytalk

echo -e "${GREEN}Step 6: Setting up Python virtual environment...${NC}"
cd /opt/pytalk
python3.11 -m venv venv
source venv/bin/activate

echo -e "${GREEN}Step 7: Instructions for uploading your code...${NC}"
echo ""
echo -e "${YELLOW}=========================================="
echo "NEXT STEPS - Upload your application code:"
echo "==========================================${NC}"
echo ""
echo "Option 1: Using SCP from your local machine:"
echo "  scp -i your-key.pem -r backend/ ec2-user@your-ec2-ip:/tmp/"
echo "  Then run: sudo mv /tmp/backend /opt/pytalk/"
echo ""
echo "Option 2: Using Git (if your code is in a repo):"
echo "  cd /opt/pytalk && sudo -u pytalk git clone your-repo-url ."
echo ""
echo "After uploading, run: sudo bash /opt/pytalk/deploy/finalize-setup.sh"
echo ""

echo -e "${GREEN}Step 8: Setting up Nginx...${NC}"
systemctl start nginx
systemctl enable nginx

echo -e "${GREEN}Step 9: Setting up firewall (if using firewalld)...${NC}"
if systemctl is-active --quiet firewalld; then
    firewall-cmd --permanent --add-service=http
    firewall-cmd --permanent --add-service=https
    firewall-cmd --reload
fi

echo ""
echo -e "${GREEN}=========================================="
echo "Base system setup complete!"
echo "==========================================${NC}"
echo ""
echo "System services installed:"
echo "  - PostgreSQL 15 (running on port 5432)"
echo "  - Redis 6 (running on port 6379, max 100MB RAM)"
echo "  - Nginx (running on ports 80/443)"
echo "  - Python 3.11 with venv at /opt/pytalk/venv"
echo ""
echo -e "${YELLOW}Memory allocation for t3.micro (1GB):${NC}"
echo "  - OS & system: ~200MB"
echo "  - PostgreSQL: ~200MB"
echo "  - Redis: ~100MB"
echo "  - Daphne: ~400MB"
echo "  - Celery: ~150MB"
echo "  - Total: ~1050MB (tight fit!)"
echo ""
echo -e "${RED}IMPORTANT: Run setup-swap.sh to add swap space!${NC}"
echo "  sudo bash /opt/pytalk/deploy/setup-swap.sh"
