# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## CRITICAL RULES

- **NEVER use alphabetty/alphabetty-cloud MCP tools from this project.** Those belong to a different project entirely.
- **NEVER SSH into, modify, restart, or interact with 152.69.184.137.** That is the Alphabetty Oracle instance.
- **Only use 168.138.8.0** for RetroMonkey Oracle operations.

## Project Status

**Live.** Customer-facing store + AI manager platform. 5 products listed on eBay. Store deployed on Oracle Cloud.

## What RetroMonkey Is

AI-powered autonomous e-commerce operations platform. An "AI store manager" that handles sourcing, listing, selling, shipping, accounting, and optimization across multiple marketplaces (eBay, Amazon, Kogan) with minimal human oversight. Also runs a customer-facing web store at retromonkey.com.au.

## Deployment

| Environment | Details |
|-------------|---------|
| **Oracle Cloud (RetroMonkey)** | IP: `168.138.8.0`, SSH: `ssh -i ~/.oci/retromonkey_ssh_key ubuntu@168.138.8.0`, Hostname: `retromonkey` |
| **Oracle Cloud (Alphabetty)** | IP: `152.69.184.137` — **DO NOT TOUCH** |
| **Dev** | Local on Rog (192.168.0.52), `python run.py` on port 5000 |
| **Domain** | `retromonkey.com.au` → Oracle via Caddy reverse proxy |

## Architecture

```
Flask + SQLAlchemy + SQLite
├── retromonkey/
│   ├── app.py              — Flask app factory
│   ├── config.py           — dev/prod config, env vars
│   ├── models/             — SQLAlchemy models (product, order, marketplace, customer, etc.)
│   ├── services/           — business logic layer (17 services)
│   ├── connectors/         — marketplace API clients (eBay, Amazon, Kogan)
│   ├── routes/             — Flask blueprints
│   │   ├── store.py        — Public store (/, /product/<slug>, /cart, /checkout, /track)
│   │   ├── customers.py    — Customer accounts (/account/*)
│   │   ├── marketplace.py  — eBay/Amazon management
│   │   ├── api.py          — Admin API
│   │   ├── sourcing.py     — Supplier/Alibaba
│   │   └── intelligence.py — AI/analytics
│   ├── templates/          — Jinja2 templates
│   │   ├── store/          — Public storefront (base, index, product, cart, checkout, etc.)
│   │   └── customers/      — Account pages
│   ├── static/             — CSS, JS, images
│   │   ├── css/store.css   — Neon Noir Luxury theme
│   │   └── images/         — Logo, product images, banners
│   └── workflows/          — workflow templates
├── retromonkey_mcp.py      — MCP server (68 tools)
├── run.py                  — entry point
├── alembic/                — database migrations
├── Dockerfile              — Production container
├── docker-compose.yml      — Docker Compose config
├── Caddyfile               — Reverse proxy for retromonkey.com.au
└── requirements.txt
```

## Store Features

- Product grid with scroll-reveal animations, tilt effects
- Stripe Checkout integration
- Session-based cart
- Customer accounts (register/login/order history)
- Order tracking
- Newsletter signup
- SEO (JSON-LD, Open Graph, sitemap, robots.txt)
- Mobile-responsive with hamburger menu
- "Neon Noir Luxury" theme (--accent: #00ff88)

## eBay Integration

- OAuth tokens stored in `marketplaces` table
- eBay connector: `retromonkey/connectors/ebay.py`
- Routes: `retromonkey/routes/marketplace.py`
- Merchant location key: `merch_loc_1`
- 5 products listed on eBay (all ACTIVE)
- 3-step listing: inventory item → offer → publish

## Database

- SQLite at `instance/retromonkey.db`
- Products use `/static/images/` paths for images
- 5 products, all with local images
- **Images column is JSON** — always use `json.dumps()` when updating via sqlite3, never raw strings
- **Product image URLs must be local** (`/static/images/`) — some products had external URLs (anbernic.com) which broke when external sites changed

## Key Design Decisions

- **LLM Router** routes by complexity: `rule` → `ollama/qwen3` → `claude` with fallback chain
- **Connector pattern** — abstract base class, per-marketplace implementations
- **Shared inventory pool** with stock reservation to prevent overselling
- **Workflow engine** — event-driven trigger-action pipelines
- **MCP server** (68 tools) for conversational store management

## Deployment

### Scripts
- `deploy.sh` — Safe code deployment (never touches DB, .env, images)
- `sync_data.sh` — Data sync (DB, images) with `--db-push`, `--db-pull`, `--images-push`, `--images-pull`, `--status`

### Data Protection Rules
- **Never tar the DB** — it's a Docker volume mount on Oracle
- **Never overwrite .env** — has production secrets (Stripe keys, API keys)
- **Never overwrite images** — volume-mounted, managed separately
- **Always backup remote DB before any data sync**
- **Always health-check after deploy** — auto-rollback on failure

### Deploy Workflow
```bash
./deploy.sh           # Deploy code only (safe, default)
./deploy.sh --full    # Full rebuild (down + build + up)
./sync_data.sh --status   # Compare local vs remote
./sync_data.sh --db-pull  # Pull Oracle DB to local
```

### Oracle Volume Mounts
- `~/retromonkey-deploy/instance/retromonkey.db` → `/app/instance/retromonkey.db` (**NOT** `/app/retromonkey.db` — Flask resolves `sqlite:///retromonkey.db` relative to its instance folder)
- `~/retromonkey-deploy/retromonkey/static/images/` → `/app/retromonkey/static/images/`
- `.env` → loaded via `env_file` in docker-compose

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.13, Flask, SQLAlchemy |
| Database | SQLite (dev+prod), Alembic migrations |
| AI | Claude API + Ollama + rule engine |
| Marketplaces | eBay API, Amazon SP-API (stub), Kogan (stub) |
| Payments | Stripe Checkout |
| Frontend | Jinja2 templates, vanilla JS |
| Proxy | Caddy (auto-TLS) |
| MCP | Custom server (68 tools) |
