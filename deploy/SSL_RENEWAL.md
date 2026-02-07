# Wildcard SSL Certificate Renewal Guide

## Overview

PyTalk uses a wildcard SSL certificate from Let's Encrypt to support custom subdomains (e.g., `acme.pytalk.veriright.com`).

- **Certificate covers:** `pytalk.veriright.com` and `*.pytalk.veriright.com`
- **Validity:** 90 days
- **Renewal method:** Manual DNS-01 challenge (requires updating TXT record at GoDaddy)

---

## When to Renew

- Certificates expire after **90 days**
- Renew **at least 2 weeks before expiry** to avoid downtime
- Set a calendar reminder for renewal

### Check Current Expiry Date

```bash
sudo certbot certificates
```

Or:

```bash
echo | openssl s_client -servername pytalk.veriright.com -connect pytalk.veriright.com:443 2>/dev/null | openssl x509 -noout -dates
```

---

## Renewal Steps

### Step 1: Start the Renewal Process

SSH into the server and run:

```bash
sudo certbot certonly --manual --preferred-challenges dns \
  -d pytalk.veriright.com \
  -d "*.pytalk.veriright.com"
```

When prompted, press `E` to expand/replace the existing certificate.

### Step 2: Note the TXT Record Value

Certbot will display something like:

```
Please deploy a DNS TXT record under the name:

_acme-challenge.pytalk.veriright.com.

with the following value:

xYz123AbC456DefGhI789JkLmNoPqRsTuVwXyZ
```

**DO NOT press Enter yet!**

### Step 3: Update DNS at GoDaddy

1. Log in to [GoDaddy DNS Management](https://dcc.godaddy.com/)
2. Select domain: `veriright.com`
3. Find or add the TXT record:

| Type | Name | Value | TTL |
|------|------|-------|-----|
| TXT | `_acme-challenge.pytalk` | (paste the value from certbot) | 600 |

4. Save the record

### Step 4: Verify DNS Propagation

Open a **new terminal** (keep certbot waiting) and verify:

```bash
dig TXT _acme-challenge.pytalk.veriright.com +short
```

You should see the value in quotes:
```
"xYz123AbC456DefGhI789JkLmNoPqRsTuVwXyZ"
```

If empty, wait 2-3 minutes and try again.

### Step 5: Complete Certification

Once DNS is verified, go back to the certbot terminal and press **Enter**.

You should see:

```
Successfully received certificate.
Certificate is saved at: /etc/letsencrypt/live/pytalk.veriright.com/fullchain.pem
Key is saved at:         /etc/letsencrypt/live/pytalk.veriright.com/privkey.pem
```

### Step 6: Reload Nginx

```bash
sudo nginx -t && sudo systemctl reload nginx
```

### Step 7: Verify the New Certificate

```bash
echo | openssl s_client -servername pytalk.veriright.com -connect pytalk.veriright.com:443 2>/dev/null | openssl x509 -noout -dates
```

Check that `notAfter` shows the new expiry date (90 days from now).

### Step 8: Clean Up (Optional)

You can delete the TXT record from GoDaddy after successful renewal, but it's harmless to leave it.

---

## Troubleshooting

### "DNS problem: NXDOMAIN looking up TXT"

- The TXT record hasn't propagated yet
- Wait 2-5 minutes and verify with `dig` before pressing Enter
- Make sure the record name is `_acme-challenge.pytalk` (GoDaddy appends `.veriright.com`)

### "Timeout during connect"

- Check if port 443 is open: `sudo ufw status`
- Check nginx is running: `sudo systemctl status nginx`

### Certificate Not Updating in Browser

- Hard refresh: `Ctrl+Shift+R`
- Clear browser cache
- Try incognito/private window

---

## Automation (Future Improvement)

For automated renewal, consider:

1. **Certbot DNS Plugin for GoDaddy** (requires API key)
   ```bash
   sudo apt install python3-certbot-dns-godaddy
   ```

2. **Move DNS to Cloudflare** (free, has official certbot plugin)
   ```bash
   sudo apt install python3-certbot-dns-cloudflare
   sudo certbot certonly --dns-cloudflare \
     --dns-cloudflare-credentials ~/.secrets/cloudflare.ini \
     -d pytalk.veriright.com -d "*.pytalk.veriright.com"
   ```

3. **Use AWS Route53** (if using AWS infrastructure)
   ```bash
   sudo apt install python3-certbot-dns-route53
   ```

These methods allow fully automated renewal via cron.

---

## Quick Reference

| Task | Command |
|------|---------|
| Check expiry | `sudo certbot certificates` |
| Start renewal | `sudo certbot certonly --manual --preferred-challenges dns -d pytalk.veriright.com -d "*.pytalk.veriright.com"` |
| Verify DNS | `dig TXT _acme-challenge.pytalk.veriright.com +short` |
| Reload nginx | `sudo nginx -t && sudo systemctl reload nginx` |
| Test SSL | `curl -I https://pytalk.veriright.com` |

---

## Important Dates

| Event | Date |
|-------|------|
| Certificate issued | February 7, 2026 |
| Certificate expires | May 8, 2026 |
| Recommended renewal | April 24, 2026 (2 weeks before) |

---

## Support

If you encounter issues:
1. Check Let's Encrypt status: https://letsencrypt.status.io/
2. Community forum: https://community.letsencrypt.org/
3. Certbot docs: https://certbot.eff.org/docs/
