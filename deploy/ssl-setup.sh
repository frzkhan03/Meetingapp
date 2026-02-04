#!/bin/bash
# PyTalk SSL Setup Script using Let's Encrypt
# Run as: sudo bash ssl-setup.sh your-domain.com

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Please run as root (sudo)${NC}"
    exit 1
fi

if [ -z "$1" ]; then
    echo -e "${RED}Usage: sudo bash ssl-setup.sh your-domain.com${NC}"
    exit 1
fi

DOMAIN=$1
EMAIL=${2:-"admin@$DOMAIN"}

echo "=========================================="
echo "Setting up SSL for: $DOMAIN"
echo "=========================================="

echo -e "${GREEN}Step 1: Installing certbot...${NC}"
dnf install -y certbot python3-certbot-nginx

echo -e "${GREEN}Step 2: Temporarily configuring Nginx for HTTP challenge...${NC}"
# Create a temporary nginx config for SSL verification
cat > /etc/nginx/conf.d/pytalk-temp.conf << EOF
server {
    listen 80;
    server_name $DOMAIN www.$DOMAIN;

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location / {
        return 200 'OK';
        add_header Content-Type text/plain;
    }
}
EOF

# Disable the main pytalk config temporarily
if [ -f /etc/nginx/conf.d/pytalk.conf ]; then
    mv /etc/nginx/conf.d/pytalk.conf /etc/nginx/conf.d/pytalk.conf.disabled
fi

nginx -t && systemctl reload nginx

echo -e "${GREEN}Step 3: Obtaining SSL certificate...${NC}"
certbot certonly \
    --webroot \
    -w /var/www/certbot \
    -d "$DOMAIN" \
    -d "www.$DOMAIN" \
    --email "$EMAIL" \
    --agree-tos \
    --non-interactive

echo -e "${GREEN}Step 4: Restoring Nginx configuration...${NC}"
# Remove temporary config
rm -f /etc/nginx/conf.d/pytalk-temp.conf

# Restore main config
if [ -f /etc/nginx/conf.d/pytalk.conf.disabled ]; then
    mv /etc/nginx/conf.d/pytalk.conf.disabled /etc/nginx/conf.d/pytalk.conf
fi

# Update nginx config with actual domain
sed -i "s/your-domain.com/$DOMAIN/g" /etc/nginx/conf.d/pytalk.conf

nginx -t && systemctl reload nginx

echo -e "${GREEN}Step 5: Setting up auto-renewal...${NC}"
# Create renewal hook to reload nginx
cat > /etc/letsencrypt/renewal-hooks/post/reload-nginx.sh << 'EOF'
#!/bin/bash
systemctl reload nginx
EOF
chmod +x /etc/letsencrypt/renewal-hooks/post/reload-nginx.sh

# Test renewal
certbot renew --dry-run

echo -e "${GREEN}Step 6: Enabling certbot timer for auto-renewal...${NC}"
systemctl enable certbot-renew.timer
systemctl start certbot-renew.timer

echo ""
echo -e "${GREEN}=========================================="
echo "SSL Setup Complete!"
echo "==========================================${NC}"
echo ""
echo "Certificate location: /etc/letsencrypt/live/$DOMAIN/"
echo "Auto-renewal: Enabled (certbot-renew.timer)"
echo ""
echo -e "${YELLOW}IMPORTANT: Update your .env file!${NC}"
echo "Make sure these settings use your domain:"
echo "  ALLOWED_HOSTS=$DOMAIN,www.$DOMAIN"
echo "  CSRF_TRUSTED_ORIGINS=https://$DOMAIN,https://www.$DOMAIN"
echo "  WEBSOCKET_ALLOWED_ORIGINS=https://$DOMAIN,wss://$DOMAIN"
echo ""
echo "Then restart PyTalk:"
echo "  sudo systemctl restart pytalk pytalk-celery"
echo ""
echo "Your site should now be accessible at: https://$DOMAIN"
