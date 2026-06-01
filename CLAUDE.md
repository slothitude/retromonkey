# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## CRITICAL RULES

- **NEVER use alphabetty/alphabetty-cloud MCP tools from this project.** Those belong to a different project entirely.
- **NEVER SSH into, modify, restart, or interact with 152.69.184.137.** That is the Alphabetty Oracle instance.
- **Only use 168.138.8.0** for RetroMonkey Oracle operations.

## Project Status

**Live.** Customer-facing store + AI manager platform. Deployed on Oracle Cloud ARM instance at retromonkey.com.au.

## What RetroMonkey Is

AI-powered autonomous e-commerce platform. An "AI store manager" that handles sourcing, listing, selling, shipping, accounting, and optimization across multiple marketplaces (eBay, Amazon stub, Kogan stub) with minimal human oversight. Also runs a customer-facing web store with Stripe Checkout.

## Common Commands

```bash
# Dev server (port 5000)
python run.py

# Run tests (pytest, in-memory SQLite via tests/conftest.py)
pytest

# MCP server mode (no scheduler, no webhooks — for Claude Code tool use)
MCP_MODE=1 python retromonkey_mcp.py

# Deploy to Oracle
./deploy.sh            # Code only (safe, default)
./deploy.sh --full     # Full rebuild (down + build + up)

# Data sync
./sync_data.sh --status       # Compare local vs remote
./sync_data.sh --db-pull      # Pull Oracle DB to local
./sync_data.sh --db-push      # Push local DB (with backup)
./sync_data.sh --images-push  # Upload images
./sync_data.sh --images-pull  # Download images

# Docker production
docker compose up -d --build    # gunicorn, 2 workers, 4 threads
```

No linter/formatter is configured. No Makefile or pyproject.toml exists.

## Deployment

| Environment | Details |
|-------------|---------|
| **Oracle Cloud** | IP: `168.138.8.0`, SSH: `ssh -i ~/.oci/retromonkey_ssh_key ubuntu@168.138.8.0` |
| **Dev** | Local on Rog, `python run.py` on port 5000 |
| **Domain** | `retromonkey.com.au` → Oracle via Caddy reverse proxy |

### Data Protection Rules
- **Never tar the DB** — it's a Docker volume mount on Oracle
- **Never overwrite .env** — has production secrets (Stripe, API keys)
- **Never overwrite images** — volume-mounted, managed separately
- **Always backup remote DB before any data sync**
- **Always health-check after deploy** — deploy.sh auto-rolls back on failure

### Oracle Volume Mounts
- `~/retromonkey-deploy/instance/retromonkey.db` → `/app/instance/retromonkey.db` (**NOT** `/app/retromonkey.db` — Flask resolves `sqlite:///retromonkey.db` relative to its instance folder)
- `~/retromonkey-deploy/retromonkey/static/images/` → `/app/retromonkey/static/images/`
- `.env` → loaded via `env_file` in docker-compose

## Architecture

```
Flask + SQLAlchemy + SQLite
├── retromonkey/
│   ├── app.py              — App factory (9 blueprints, 7 scheduler jobs, model imports)
│   ├── config.py           — DevConfig/ProdConfig, env vars from .env
│   ├── models/             — 12 SQLAlchemy model classes across 10 files
│   ├── services/           — 20 business logic services
│   ├── connectors/         — Abstract base + eBay (live), Amazon/Kogan (stubs)
│   ├── routes/             — 9 Flask blueprints, ~108 HTTP endpoints total
│   │   ├── store.py        — Public storefront (/, /product/<slug>, /cart, /checkout, Stripe webhook)
│   │   ├── customers.py    — Customer accounts (/account/*)
│   │   ├── pages.py        — Admin dashboard HTML (/admin/*)
│   │   ├── api.py          — Admin JSON API (/api/*)
│   │   ├── marketplace.py  — eBay management (/api/marketplace/*)
│   │   ├── sourcing.py     — Suppliers/Alibaba (/api/sourcing/*)
│   │   ├── intelligence.py — AI/comms/workflows (/api/intelligence/*) — 42 endpoints
│   │   ├── webhooks.py     — Incoming webhooks (eBay, Gmail, Telegram)
│   │   └── tasks.py        — Task management (/api/tasks/*)
│   ├── templates/          — Jinja2 (store/, customers/, admin HTML views)
│   ├── static/             — CSS (Neon Noir Luxury theme, --accent: #00ff88), JS, images
│   └── workflows/          — 4 YAML event-driven workflow templates
├── retromonkey_mcp.py      — MCP server (76 tools across 21 domains)
├── run.py                  — Entry point
├── tests/conftest.py       — pytest fixtures (app, client, in-memory SQLite)
├── alembic/                — Database migrations (no migrations generated yet)
├── Dockerfile              — Python 3.13-slim + gunicorn
├── docker-compose.yml      — Single-store production
├── docker-compose.stores.yml — Multi-store (container-per-store)
└── Caddyfile               — Reverse proxy, TLS, security headers, static caching
```

## Key Design Patterns

- **LLM Router** (`services/llm_router.py`) — routes by complexity: keyword matching → `ollama/qwen3` (simple) or `claude-sonnet` (complex) with mutual fallback. Modes: `auto`, `rule`, `ollama`, `claude`.
- **Connector pattern** — `BaseConnector` ABC with 9 abstract methods, per-marketplace implementations. Only eBay is live.
- **MCP tool dispatch** — tools defined as JSON schemas in a `TOOLS` list, dispatched via handler dict, each wrapped in `_ctx()` for Flask app context. Lazy singleton pattern for all services.
- **Shared inventory pool** — `Inventory` table with `quantity_reserved` column, reserve/release/commit flow prevents overselling across marketplaces.
- **Workflow engine** (`services/workflow.py`) — loads YAML templates, 12 action types (email, stock, PO, LLM, notify, wait, condition, price, status, log, telegram, alert).
- **Multi-store** — `docker-compose.stores.yml` supports container-per-store with parameterized branding, separate ports (5001+), agent auth tokens.

## Scheduler Jobs (prod only, skipped in MCP_MODE)

| Job | Schedule | Purpose |
|-----|----------|---------|
| `poll_orders` | 15 min | Poll eBay for new orders, alert each |
| `sync_inventory` | 30 min | Sync inventory across marketplaces |
| `reorder_check` | Daily 07:00 | Low stock detection + alerts |
| `daily_checklist` | Daily 08:30 | Generate checklist + morning briefing |
| `daily_summary` | Daily 18:00 | P&L, stock, tasks summary; auto-complete EOD |
| `weekly_report` | Monday 09:00 | Weekly P&L, top sellers, stock report |
| `gmail_watch_renewal` | Daily 03:00 | Renew Gmail Pub/Sub watch (expires ~7d) |

## eBay Integration

- **Connector**: `retromonkey/connectors/ebay.py` — fully implemented
- **Auth**: OAuth tokens in `marketplaces` table, auto-refresh
- **Listing**: 3-step flow: create inventory item → create offer → publish listing
- **Env vars**: `EBAY_CLIENT_ID`, `EBAY_CLIENT_SECRET`, `EBAY_DEV_ID`, `EBAY_USER_TOKEN`, `EBAY_PAYMENT_POLICY_ID`, `EBAY_RETURN_POLICY_ID`, `EBAY_FULFILLMENT_POLICY_ID`
- **Marketplace**: EBAY_AU

## Database

- SQLite at `instance/retromonkey.db` (local), `~/retromonkey-deploy/instance/retromonkey.db` (Oracle)
- **Images column is JSON** — always use `json.dumps()` when updating via sqlite3, never raw strings
- **Product image URLs must be local** (`/static/images/`) — external URLs break when source sites change
- 12 model classes: Product, Inventory, Marketplace, Listing, Order, OrderItem, Shipment, Transaction, Fee, Supplier, PurchaseOrder, RFQ, SupplierScore, Message, Customer, StripeEvent, Task

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.13, Flask, SQLAlchemy, APScheduler |
| Database | SQLite (dev+prod), Alembic migrations |
| AI | Claude API (anthropic SDK) + Ollama (qwen3) + rule engine |
| Marketplaces | eBay API (live), Amazon SP-API (stub), Kogan (stub) |
| Payments | Stripe Checkout |
| Frontend | Jinja2 templates, vanilla JS |
| Email | Resend (@retromonkey.com.au) + Gmail fallback |
| Proxy | Caddy (auto-TLS) |
| MCP | Custom server (76 tools, 21 domains) |
