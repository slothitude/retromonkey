#!/bin/bash
# RetroMonkey Deployment Script
# Safely deploys code to Oracle without touching DB, .env, or images.
#
# Usage:
#   ./deploy.sh          — deploy code only (default)
#   ./deploy.sh --full   — deploy code + rebuild from scratch
#
# NEVER touches: retromonkey.db, .env, static/images/

set -euo pipefail

ORACLE_HOST=168.138.8.0
SSH_KEY="$HOME/.oci/retromonkey_ssh_key"
REMOTE_USER="ubuntu"
REMOTE_HOME="/home/ubuntu"
REMOTE_DIR="$REMOTE_HOME/retromonkey-deploy"
SSH="ssh -i $SSH_KEY -o StrictHostKeyChecking=no ${REMOTE_USER}@${ORACLE_HOST}"
TAR_FILE="/tmp/retromonkey-deploy.tar.gz"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[DEPLOY]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
err()  { echo -e "${RED}[ERROR]${NC} $1"; }

FULL_REBUILD=false
[[ "${1:-}" == "--full" ]] && FULL_REBUILD=true

# --- Pre-flight ---
log "Pre-flight checks..."

# Check SSH connectivity
if ! $SSH "echo ok" > /dev/null 2>&1; then
    err "Cannot SSH to Oracle. Check connectivity."
    exit 1
fi
log "SSH connection OK"

# Check current site health
CURRENT_HEALTH=$($SSH "curl -s -o /dev/null -w '%{http_code}' http://localhost:5000/health" 2>/dev/null || echo "000")
log "Current site health: $CURRENT_HEALTH"

# --- Step 1: Backup remote DB ---
log "Backing up remote database..."
$SSH "cp $REMOTE_DIR/retromonkey.db $REMOTE_DIR/instance/retromonkey.db.bak-$TIMESTAMP" 2>/dev/null || true
$SSH "cp $REMOTE_DIR/retromonkey.db $REMOTE_DIR/instance/retromonkey.db.bak" 2>/dev/null || true
log "DB backed up as retromonkey.db.bak-$TIMESTAMP"

# --- Step 2: Package code ---
log "Packaging code (excluding DB, .env, images)..."

tar czf "$TAR_FILE" \
    --exclude='./instance' \
    --exclude='./.env' \
    --exclude='./.env.*' \
    --exclude='./__pycache__' \
    --exclude='./.git' \
    --exclude='./*.pyc' \
    --exclude='./*.db' \
    --exclude='./*.db.bak' \
    --exclude='./node_modules' \
    --exclude='./.venv' \
    --exclude='./venv' \
    --exclude='./.claude' \
    --exclude='./.vscode' \
    --exclude='./.idea' \
    --exclude='./plans' \
    --exclude='./data' \
    --exclude='./deploy.sh' \
    --exclude='./sync_data.sh' \
    --exclude='./tmp-upload' \
    --exclude='./retromonkey/static/images' \
    .

log "Package created: $(du -h "$TAR_FILE" | cut -f1)"

# --- Step 3: Upload ---
log "Uploading to Oracle..."
scp -i "$SSH_KEY" "$TAR_FILE" "${REMOTE_USER}@${ORACLE_HOST}:${REMOTE_DIR}/retromonkey-deploy.tar.gz"

# --- Step 4: Extract on remote ---
log "Extracting on remote..."
$SSH "cd $REMOTE_DIR && tar xzf retromonkey-deploy.tar.gz && rm retromonkey-deploy.tar.gz"

# --- Step 5: Rebuild container ---
if $FULL_REBUILD; then
    log "Full rebuild requested — taking down container first..."
    $SSH "cd $REMOTE_DIR && docker compose down"
fi

log "Rebuilding container..."
$SSH "cd $REMOTE_DIR && docker compose up -d --build"

# Wait for container to start
log "Waiting for container to start..."
HEALTH="000"
for i in $(seq 1 30); do
    sleep 2
    HEALTH=$($SSH "curl -s -o /dev/null -w '%{http_code}' http://localhost:5000/health" 2>/dev/null || echo "000")
    if [[ "$HEALTH" == "200" ]]; then
        break
    fi
    log "Waiting... ($HEALTH)"
done

# --- Step 6: Health check ---

if [[ "$HEALTH" == "200" ]]; then
    log "Health check PASSED (200 OK)"
    sleep 3
    log "Checking image URLs..."
    IMG_CHECK=$($SSH "curl -s -o /dev/null -w '%{http_code}' http://localhost:5000/static/images/logo.png" 2>/dev/null || echo "000")
    if [[ "$IMG_CHECK" == "200" ]]; then
        log "Images OK"
    else
        warn "Logo image returned $IMG_CHECK — check image volume mount"
    fi
    log "Deployment complete!"
else
    err "Health check FAILED (got $HEALTH)"
    err "Rolling back..."

    # --- Step 7: Rollback ---
    $SSH "cd $REMOTE_DIR && docker compose down"
    $SSH "cp $REMOTE_DIR/instance/retromonkey.db.bak $REMOTE_DIR/retromonkey.db"
    $SSH "cd $REMOTE_DIR && docker compose up -d --build"

    sleep 5
    ROLLBACK_HEALTH=$($SSH "curl -s -o /dev/null -w '%{http_code}' http://localhost:5000/health" 2>/dev/null || true)
    if [[ "$ROLLBACK_HEALTH" == "200" ]]; then
        warn "Rollback succeeded — site restored from backup"
    else
        err "Rollback FAILED — manual intervention required!"
        err "SSH in: $SSH"
        exit 1
    fi
    exit 1
fi

# Cleanup local tar
rm -f "$TAR_FILE"
log "Local tar cleaned up"
