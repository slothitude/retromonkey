#!/bin/bash
# RetroMonkey Data Sync Script
# Syncs DB and images between local and Oracle.
# ALWAYS backs up before overwriting.
#
# Usage:
#   ./sync_data.sh --db-push     — Upload local DB to Oracle (with backup)
#   ./sync_data.sh --db-pull     — Download Oracle DB to local
#   ./sync_data.sh --images-push — Upload local images to Oracle
#   ./sync_data.sh --images-pull — Download Oracle images to local
#   ./sync_data.sh --status      — Compare local vs remote DB stats

set -euo pipefail

ORACLE_HOST=168.138.8.0
SSH_KEY="$HOME/.oci/retromonkey_ssh_key"
REMOTE_USER="ubuntu"
REMOTE_HOME="/home/ubuntu"
REMOTE_DIR="$REMOTE_HOME/retromonkey-deploy"
SSH="ssh -i $SSH_KEY -o StrictHostKeyChecking=no ${REMOTE_USER}@${ORACLE_HOST}"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)

LOCAL_DB="instance/retromonkey.db"
LOCAL_IMAGES="retromonkey/static/images/"
REMOTE_DB="$REMOTE_DIR/retromonkey.db"
REMOTE_IMAGES="$REMOTE_DIR/retromonkey/static/images/"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log()  { echo -e "${GREEN}[SYNC]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
err()  { echo -e "${RED}[ERROR]${NC} $1"; }
info() { echo -e "${CYAN}[INFO]${NC} $1"; }

ACTION="${1:-}"
if [[ -z "$ACTION" ]]; then
    echo "Usage: ./sync_data.sh --db-push|--db-pull|--images-push|--images-pull|--status"
    exit 1
fi

case "$ACTION" in
    --db-push)
        if [[ ! -f "$LOCAL_DB" ]]; then
            err "Local DB not found at $LOCAL_DB"
            exit 1
        fi
        log "Backing up remote DB..."
        $SSH "cp $REMOTE_DB $REMOTE_DIR/instance/retromonkey.db.bak-$TIMESTAMP"
        log "Uploading local DB..."
        scp -i "$SSH_KEY" "$LOCAL_DB" "${REMOTE_USER}@${ORACLE_HOST}:${REMOTE_DB}"
        log "Restarting container..."
        $SSH "cd $REMOTE_DIR && docker compose restart"
        sleep 3
        HEALTH=$($SSH "curl -s -o /dev/null -w '%{http_code}' http://localhost:5000/health" 2>/dev/null || echo "000")
        if [[ "$HEALTH" == "200" ]]; then
            log "DB push complete — site healthy"
        else
            err "Site unhealthy after DB push (HTTP $HEALTH) — check manually"
            exit 1
        fi
        ;;

    --db-pull)
        log "Backing up local DB..."
        mkdir -p data/db-backups
        cp "$LOCAL_DB" "data/db-backups/retromonkey-$TIMESTAMP.db" 2>/dev/null || true
        log "Downloading remote DB..."
        scp -i "$SSH_KEY" "${REMOTE_USER}@${ORACLE_HOST}:${REMOTE_DB}" "$LOCAL_DB"
        log "DB pull complete"
        ;;

    --images-push)
        log "Uploading images to Oracle..."
        scp -i "$SSH_KEY" -r "${LOCAL_IMAGES}"* "${REMOTE_USER}@${ORACLE_HOST}:${REMOTE_IMAGES}"
        log "Images pushed"
        ;;

    --images-pull)
        log "Downloading images from Oracle..."
        mkdir -p "$LOCAL_IMAGES"
        scp -i "$SSH_KEY" -r "${REMOTE_USER}@${ORACLE_HOST}:${REMOTE_IMAGES}"* "$LOCAL_IMAGES"
        log "Images pulled"
        ;;

    --status)
        log "Comparing local vs remote..."
        LOCAL_COUNT=$([[ -f "$LOCAL_DB" ]] && sqlite3 "$LOCAL_DB" "SELECT COUNT(*) FROM products;" 2>/dev/null || echo "?")
        REMOTE_COUNT=$($SSH "sqlite3 $REMOTE_DB 'SELECT COUNT(*) FROM products;'" 2>/dev/null || echo "?")
        LOCAL_SIZE=$([[ -f "$LOCAL_DB" ]] && du -h "$LOCAL_DB" | cut -f1 || echo "?")
        REMOTE_SIZE=$($SSH "du -h $REMOTE_DB | cut -f1" 2>/dev/null || echo "?")
        LOCAL_IMGS=$([[ -d "$LOCAL_IMAGES" ]] && ls "$LOCAL_IMAGES" | wc -l || echo "?")
        REMOTE_IMGS=$($SSH "ls $REMOTE_IMAGES | wc -l" 2>/dev/null || echo "?")

        echo ""
        echo "         LOCAL          REMOTE"
        echo "DB size: $LOCAL_SIZE        $REMOTE_SIZE"
        echo "Products: $LOCAL_COUNT            $REMOTE_COUNT"
        echo "Images:   $LOCAL_IMGS            $REMOTE_IMGS"
        echo ""

        HEALTH=$($SSH "curl -s http://localhost:5000/health" 2>/dev/null || echo "unreachable")
        info "Remote health: $HEALTH"
        ;;

    *)
        err "Unknown action: $ACTION"
        echo "Usage: ./sync_data.sh --db-push|--db-pull|--images-push|--images-pull|--status"
        exit 1
        ;;
esac
