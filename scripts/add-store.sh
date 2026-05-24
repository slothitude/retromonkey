#!/usr/bin/env bash
# add-store.sh — Onboard a new store to the multi-store infrastructure.
# Usage: ./scripts/add-store.sh <store-name> <domain> [port]
#
# Creates:
#   - stores/<name>/ directory with .env template
#   - stores/<name>/db/ (SQLite volume)
#   - stores/<name>/images/ (product images volume)
#   - Caddy entry (printed, not auto-inserted)
#
# After running this script:
# 1. Edit stores/<name>.env with real credentials
# 2. Add the Caddy block from the Caddyfile
# 3. docker compose -f docker-compose.stores.yml up -d <name>

set -euo pipefail

NAME="${1:?Usage: add-store.sh <store-name> <domain> [port]}"
DOMAIN="${2:?Usage: add-store.sh <store-name> <domain> [port]}"
PORT="${3:-5002}"

STORES_DIR="$(cd "$(dirname "$0")/.." && pwd)/stores"
STORE_DIR="$STORES_DIR/$NAME"

if [ -d "$STORE_DIR" ]; then
    echo "ERROR: Store '$NAME' already exists at $STORE_DIR"
    exit 1
fi

echo "==> Creating store: $NAME ($DOMAIN) on port $PORT"

# Create directory structure
mkdir -p "$STORE_DIR/db" "$STORE_DIR/images"

# Generate .env template
cat > "$STORE_DIR/.env" << EOF
# Store Identity
STORE_NAME=${NAME^}
STORE_TAGLINE=Your Store Tagline Here
STORE_LOGO=/static/images/logo.png
STORE_THEME=neon_noir
STORE_CURRENCY=AUD
STORE_AGENT_TOKEN=

# Site
SITE_URL=https://${DOMAIN}
FLASK_ENV=production
DATABASE_URL=sqlite:///retromonkey.db
SECRET_KEY=CHANGE-ME-$(openssl rand -hex 16)

# Business
ABN=
BUSINESS_NAME=${NAME^}
GST_RATE=0.10

# Stripe
STRIPE_PUBLIC_KEY=
STRIPE_SECRET_KEY=
STRIPE_WEBHOOK_SECRET=

# eBay
EBAY_CLIENT_ID=
EBAY_CLIENT_SECRET=
EBAY_DEV_ID=
EBAY_REDIRECT_URI=
EBAY_ENV=sandbox
EBAY_PAYMENT_POLICY_ID=
EBAY_RETURN_POLICY_ID=
EBAY_FULFILLMENT_POLICY_ID=
EBAY_USER_TOKEN=

# LLM
CLAUDE_API_KEY=
OLLAMA_BASE_URL=http://host.docker.internal:11434
LLM_DEFAULT_MODE=auto

# Telegram Alerts
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
ALERT_EMAIL=
ALERT_TELEGRAM_ENABLED=false
EOF

# Symlink .env to the stores directory for docker-compose
ln -sf "$STORE_DIR/.env" "$STORES_DIR/$NAME.env"

echo ""
echo "==> Store created at: $STORE_DIR"
echo ""
echo "Next steps:"
echo "  1. Edit $STORE_DIR/.env with real credentials"
echo "  2. Copy logo.png to $STORE_DIR/images/"
echo "  3. Add this to docker-compose.stores.yml:"
echo ""
cat << COMPOSE
  ${NAME}:
    build: .
    container_name: ${NAME}
    restart: unless-stopped
    env_file: ./stores/${NAME}.env
    environment:
      - FLASK_ENV=production
      - DATABASE_URL=sqlite:///retromonkey.db
    volumes:
      - ./stores/${NAME}/db:/app/instance
      - ./stores/${NAME}/images:/app/retromonkey/static/images
    ports:
      - "${PORT}:5000"
    networks:
      - store-net
COMPOSE

echo ""
echo "  4. Add this to Caddyfile:"
echo ""
cat << CADDY
${DOMAIN} {
    reverse_proxy ${NAME}:5000
    encode gzip
    @static path /static/*
    header @static Cache-Control "public, max-age=31536000, immutable"
    header {
        X-Frame-Options DENY
        X-Content-Type-Options nosniff
        Referrer-Policy strict-origin-when-cross-origin
    }
}
CADDY

echo ""
echo "  5. docker compose -f docker-compose.stores.yml up -d ${NAME}"
echo "  6. caddy reload --config /etc/caddy/Caddyfile"
