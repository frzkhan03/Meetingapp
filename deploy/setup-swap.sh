#!/bin/bash
# Setup swap space for t3.micro (1GB RAM)
# Run as: sudo bash setup-swap.sh

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Please run as root (sudo)${NC}"
    exit 1
fi

# Check if swap already exists
if [ -f /swapfile ]; then
    echo "Swap file already exists."
    swapon --show
    exit 0
fi

echo -e "${GREEN}Creating 1GB swap file...${NC}"

# Create swap file (1GB)
dd if=/dev/zero of=/swapfile bs=128M count=8 status=progress

# Set correct permissions
chmod 600 /swapfile

# Set up swap space
mkswap /swapfile

# Enable swap
swapon /swapfile

# Make it permanent
echo '/swapfile swap swap defaults 0 0' >> /etc/fstab

# Optimize swappiness for server workload
echo 'vm.swappiness=10' >> /etc/sysctl.conf
sysctl vm.swappiness=10

echo ""
echo -e "${GREEN}Swap setup complete!${NC}"
echo ""
echo "Current swap status:"
swapon --show
free -h
