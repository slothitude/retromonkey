# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Status

**Planning phase.** No code yet — three planning docs define the full system:
- `ideas.md` — initial brainstorm
- `ideas2.md` — detailed feature specifications (7 modules, API integrations, architecture)
- `plan.md` — execution plan (5 subagents, 40+ tasks, 10-week timeline, DB schema)

## What RetroMonkey Is

AI-powered autonomous e-commerce operations platform. An "AI store manager" that handles sourcing, listing, selling, shipping, accounting, and optimization across multiple marketplaces (eBay, Amazon, Kogan) with minimal human oversight. Target: $5/day operating cost vs $25/hour human manager.

## Planned Architecture

```
Flask + SQLAlchemy + SQLite (dev) / PostgreSQL (prod)
├── retromonkey/
│   ├── app.py              — Flask app factory
│   ├── config.py           — dev/prod config, env vars
│   ├── models/             — SQLAlchemy models (product, order, marketplace, finance, supplier, communication)
│   ├── services/           — business logic layer
│   │   ├── llm_router.py   — Claude/Ollama/rule engine routing with fallback chain
│   │   ├── inventory.py    — stock management, reservation, cross-platform sync
│   │   ├── sync.py         — cross-marketplace inventory sync
│   │   ├── research.py     — market research (Google Trends, eBay Terapeak, Amazon BSR)
│   │   ├── sourcing.py     — Alibaba supplier pipeline
│   │   ├── scoring.py      — weighted supplier scoring algorithm
│   │   ├── rfq.py          — RFQ generation and tracking
│   │   ├── reorder.py      — auto-reorder on low stock
│   │   ├── quality.py      — supplier quality control
│   │   ├── workflow.py     — trigger-action pipeline engine
│   │   ├── gmail_client.py — Gmail API integration
│   │   ├── communications.py — multi-channel messaging hub
│   │   ├── pricing.py      — dynamic pricing engine
│   │   ├── listing_ai.py   — AI listing optimization (SEO titles, descriptions)
│   │   ├── accounting.py   — P&L, fee calculator, tax estimation
│   │   ├── customer_service.py — auto-response engine
│   │   └── business_planner.py — business plan generator
│   ├── connectors/         — marketplace API clients
│   │   ├── base.py         — abstract base connector
│   │   ├── ebay.py         — eBay full API (Sell/Buy/Commerce/Marketing/Notification)
│   │   ├── amazon.py       — Amazon SP-API
│   │   ├── kogan.py        — Kogan connector
│   │   └── website.py      — self-hosted store connector
│   ├── routes/             — Flask blueprints (api, marketplace, sourcing, intelligence, pages)
│   ├── templates/          — Jinja2 templates (8-page dashboard)
│   ├── static/             — CSS, JS
│   └── workflows/          — workflow templates (YAML/JSON)
├── ebay_mcp.py             — MCP server exposing eBay operations as tools
├── run.py                  — entry point
├── alembic/                — database migrations
└── requirements.txt
```

## Key Design Decisions

- **LLM Router** routes by complexity: `rule` (free, deterministic) → `ollama/qwen3` (local, ~$0.50/day) → `claude` (API, ~$2-3/day). Fallback chain: Claude → Ollama → rule engine.
- **Connector pattern** — abstract base class with common interface (`list_item`, `get_orders`, `ship_order`, etc.), per-marketplace implementations
- **Shared inventory pool** across all marketplaces with stock reservation on order placement to prevent overselling
- **Supplier scoring** — weighted algorithm: trade assurance 25%, rating 20%, response time 15%, MOQ fit 15%, price 15%, platform history 10%
- **Workflow engine** — event-driven trigger-action pipelines (order_received, low_stock, message_received, etc.)
- **eBay MCP server** (`ebay_mcp.py`) — exposes eBay operations as MCP tools for conversational store management

## Database Schema (13 tables)

products, inventory, marketplaces, listings, orders, order_items, shipments, transactions, fees, suppliers, purchase_orders, rfqs, messages, supplier_scores — see `plan.md` for full column definitions.

## Development Phases

| Sprint | Week | Focus |
|--------|------|-------|
| 1 | 1-2 | Foundation: scaffold, DB, LLM router, inventory service, base connector, eBay auth |
| 2 | 3-4 | Marketplace core: eBay inventory/listings/orders/marketing, Alibaba search, Gmail |
| 3 | 5-6 | Sourcing & comms: RFQ automation, reorder, eBay MCP, inventory sync, comms hub |
| 4 | 7-8 | Intelligence: AI listing optimization, dynamic pricing, Amazon SP-API, accounting |
| 5 | 9-10 | Integration, testing, polish |

## Planned Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.13, Flask, SQLAlchemy, APScheduler |
| Database | SQLite (dev) → PostgreSQL (prod), Alembic migrations |
| AI | Claude API (complex) + Ollama qwen3 (simple) + rule engine (free) |
| Marketplaces | eBay (Sell/Buy/Commerce/Marketing API), Amazon SP-API, Kogan |
| Email | Gmail API (Google OAuth 2.0) |
| Frontend | Flask templates + HTMX (or Next.js, TBD) |
| Workflow | n8n (self-hosted) or custom Python orchestrator |
| MCP | Custom eBay MCP server |
