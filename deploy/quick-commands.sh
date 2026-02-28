#!/bin/bash
# PyTalk Quick Commands Reference
# Source this file: source quick-commands.sh

# Aliases for common operations
alias pytalk-status='sudo systemctl status pytalk pytalk-celery pytalk-celery-beat redis-server postgresql nginx'
alias pytalk-restart='sudo systemctl restart pytalk pytalk-celery pytalk-celery-beat'
alias pytalk-logs='sudo journalctl -u pytalk -f'
alias pytalk-celery-logs='sudo journalctl -u pytalk-celery -f'
alias pytalk-errors='sudo journalctl -u pytalk -p err --since "1 hour ago"'

# Functions
pytalk-shell() {
    cd /opt/pytalk/backend
    /opt/pytalk/venv/bin/python manage.py shell
}

pytalk-migrate() {
    cd /opt/pytalk/backend
    /opt/pytalk/venv/bin/python manage.py migrate
}

pytalk-collectstatic() {
    cd /opt/pytalk/backend
    /opt/pytalk/venv/bin/python manage.py collectstatic --noinput
}

pytalk-createsuperuser() {
    cd /opt/pytalk/backend
    /opt/pytalk/venv/bin/python manage.py createsuperuser
}

pytalk-update() {
    echo "Updating PyTalk..."
    cd /opt/pytalk
    git pull
    cd backend
    /opt/pytalk/venv/bin/pip install -r requirements.txt
    /opt/pytalk/venv/bin/python manage.py migrate
    /opt/pytalk/venv/bin/python manage.py collectstatic --noinput
    sudo systemctl restart pytalk pytalk-celery pytalk-celery-beat
    echo "Update complete!"
}

pytalk-backup() {
    BACKUP_FILE="/tmp/pytalk_backup_$(date +%Y%m%d_%H%M%S).sql"
    sudo -u postgres pg_dump pytalk > "$BACKUP_FILE"
    echo "Backup created: $BACKUP_FILE"
}

pytalk-health() {
    python3 /opt/pytalk/deploy/health-check.py
}

echo "PyTalk quick commands loaded!"
echo "Available: pytalk-status, pytalk-restart, pytalk-logs, pytalk-celery-logs"
echo "           pytalk-shell, pytalk-migrate, pytalk-update, pytalk-backup, pytalk-health"
