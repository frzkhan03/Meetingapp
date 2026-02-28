#!/bin/bash
# Setup swap space (safety net for memory pressure)
# Run as: sudo bash setup-swap.sh

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Please run as root (sudo)${NC}"
    exit 1
fi

if swapon --show | grep -q '/swapfile'; then
    echo "Swap file already exists."
    swapon --show
    exit 0
fi

echo -e "${GREEN}Creating 1GB swap file...${NC}"

dd if=/dev/zero of=/swapfile bs=128M count=8 status=progress
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile

# Make permanent
if ! grep -q '/swapfile' /etc/fstab; then
    echo '/swapfile swap swap defaults 0 0' >> /etc/fstab
fi

# Optimize swappiness
echo 'vm.swappiness=10' > /etc/sysctl.d/99-swappiness.conf
sysctl vm.swappiness=10

echo ""
echo -e "${GREEN}Swap setup complete!${NC}"
echo ""
swapon --show
free -h
