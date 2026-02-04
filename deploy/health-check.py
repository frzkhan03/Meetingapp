#!/usr/bin/env python3
"""
PyTalk Health Check Script
Run: python health-check.py

Checks:
- Django application
- PostgreSQL database
- Redis cache
- Celery workers
- Disk space
- Memory usage
"""

import subprocess
import sys
import os

# Add color support
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    RESET = '\033[0m'

def ok(msg):
    print(f"  {Colors.GREEN}[OK]{Colors.RESET} {msg}")

def fail(msg):
    print(f"  {Colors.RED}[FAIL]{Colors.RESET} {msg}")

def warn(msg):
    print(f"  {Colors.YELLOW}[WARN]{Colors.RESET} {msg}")

def run_cmd(cmd):
    """Run a shell command and return output"""
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
        return result.returncode == 0, result.stdout.strip()
    except Exception as e:
        return False, str(e)

def check_service(name):
    """Check if a systemd service is running"""
    success, output = run_cmd(f"systemctl is-active {name}")
    return success and output == "active"

def check_port(port):
    """Check if a port is listening"""
    success, _ = run_cmd(f"ss -tlnp | grep :{port}")
    return success

def main():
    print("\n" + "="*50)
    print("PyTalk Health Check")
    print("="*50 + "\n")

    all_ok = True

    # Check systemd services
    print("Checking Services...")
    services = [
        ("pytalk", "Daphne ASGI Server"),
        ("pytalk-celery", "Celery Worker"),
        ("redis6", "Redis Cache"),
        ("postgresql", "PostgreSQL Database"),
        ("nginx", "Nginx Web Server"),
    ]

    for service, desc in services:
        if check_service(service):
            ok(f"{desc} ({service})")
        else:
            fail(f"{desc} ({service})")
            all_ok = False

    # Check ports
    print("\nChecking Ports...")
    ports = [
        (80, "HTTP"),
        (443, "HTTPS"),
        (8001, "Daphne"),
        (5432, "PostgreSQL"),
        (6379, "Redis"),
    ]

    for port, desc in ports:
        if check_port(port):
            ok(f"Port {port} ({desc})")
        else:
            warn(f"Port {port} ({desc}) - not listening")

    # Check Redis
    print("\nChecking Redis...")
    success, output = run_cmd("redis-cli ping")
    if success and "PONG" in output:
        ok("Redis responding to PING")
    else:
        fail("Redis not responding")
        all_ok = False

    # Check PostgreSQL
    print("\nChecking PostgreSQL...")
    success, _ = run_cmd("sudo -u postgres psql -c 'SELECT 1' -t")
    if success:
        ok("PostgreSQL accepting connections")
    else:
        fail("PostgreSQL not responding")
        all_ok = False

    # Check disk space
    print("\nChecking Disk Space...")
    success, output = run_cmd("df -h / | tail -1 | awk '{print $5}'")
    if success:
        usage = int(output.replace('%', ''))
        if usage < 80:
            ok(f"Disk usage: {usage}%")
        elif usage < 90:
            warn(f"Disk usage: {usage}% (getting full)")
        else:
            fail(f"Disk usage: {usage}% (critical!)")
            all_ok = False

    # Check memory
    print("\nChecking Memory...")
    success, output = run_cmd("free -m | grep Mem | awk '{print $3, $2}'")
    if success:
        used, total = map(int, output.split())
        percent = (used / total) * 100
        if percent < 80:
            ok(f"Memory: {used}MB / {total}MB ({percent:.1f}%)")
        elif percent < 90:
            warn(f"Memory: {used}MB / {total}MB ({percent:.1f}%) - high usage")
        else:
            fail(f"Memory: {used}MB / {total}MB ({percent:.1f}%) - critical!")
            all_ok = False

    # Check application logs for recent errors
    print("\nChecking Recent Errors...")
    success, output = run_cmd("journalctl -u pytalk --since '10 minutes ago' -p err --no-pager 2>/dev/null | wc -l")
    if success:
        error_count = int(output) if output.isdigit() else 0
        if error_count == 0:
            ok("No errors in last 10 minutes")
        else:
            warn(f"{error_count} errors in last 10 minutes")

    # Summary
    print("\n" + "="*50)
    if all_ok:
        print(f"{Colors.GREEN}All critical checks passed!{Colors.RESET}")
    else:
        print(f"{Colors.RED}Some checks failed - review above{Colors.RESET}")
    print("="*50 + "\n")

    return 0 if all_ok else 1

if __name__ == "__main__":
    sys.exit(main())
