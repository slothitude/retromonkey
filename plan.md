# RetroMonkey AI Manager — Project Plan

**Created:** 2026-05-23
**Status:** Planning
**Execution Model:** 5 subagents (BOSS-managed)

---

## Executive Summary

RetroMonkey is a full-spectrum autonomous e-commerce operations platform. An AI store manager that handles sourcing, listing, selling, shipping, accounting, and optimization with minimal human oversight. This plan breaks the build into 5 parallel workstreams, each assigned to a dedicated subagent.

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────────┐
│                    RetroMonkey Core                       │
│                  (Flask + SQLite + APScheduler)           │
├────────────┬─────────────┬──────────────┬────────────────┤
│  Agent 1   │  Agent 2    │  Agent 3     │  Agent 4       │
│ Foundation │ Marketplace │  Sourcing &  │  Intelligence  │
│  & DB      │ Connectors  │  Research    │  & Automation  │
├────────────┴─────────────┴──────────────┴────────────────┤
│                    Agent 5 — Dashboard & UI              │
├──────────────────────────────────────────────────────────┤
│              Shared: LLM Router (Claude + Ollama)        │
│              Shared: Workflow Engine (n8n or custom)     │
└──────────────────────────────────────────────────────────┘
```

---

## Subagent Assignments

### Agent 1 — Foundation & Database
**Role:** Project scaffold, database schema, auth, shared services
**Priority:** P0 — starts first, others depend on this

### Agent 2 — Marketplace Connectors
**Role:** eBay API, Amazon SP-API, Kogan, inventory sync
**Priority:** P0 — depends on Agent 1's DB schema

### Agent 3 — Sourcing & Research
**Role:** Alibaba pipeline, market research, supplier scoring, RFQ automation
**Priority:** P1 — can start in parallel with Agent 2 after DB is ready

### Agent 4 — Intelligence & Automation
**Role:** AI workers, workflow engine, Gmail integration, communications hub
**Priority:** P1 — builds on top of marketplace connectors

### Agent 5 — Dashboard & Frontend
**Role:** Web UI, product management views, order dashboard, analytics
**Priority:** P2 — builds last, consumes APIs from all other agents

---

## Detailed Task Breakdown

---

### Agent 1 — Foundation & Database

**Files to create:**
- `retromonkey/` — main package
- `retromonkey/__init__.py`
- `retromonkey/app.py` — Flask app factory
- `retromonkey/config.py` — configuration (env vars, secrets)
- `retromonkey/models/` — SQLAlchemy models
- `retromonkey/models/__init__.py`
- `retromonkey/models/product.py` — Product, SKU, Inventory
- `retromonkey/models/order.py` — Order, OrderItem, Shipment
- `retromonkey/models/marketplace.py` — Marketplace, Listing
- `retromonkey/models/finance.py` — Transaction, Fee, Invoice
- `retromonkey/models/supplier.py` — Supplier, PurchaseOrder, RFQ
- `retromonkey/models/communication.py` — Message, EmailLog
- `retromonkey/services/` — business logic layer
- `retromonkey/services/llm_router.py` — Claude/Ollama fallback routing
- `retromonkey/services/inventory.py` — inventory management
- `retromonkey/routes/` — API blueprints
- `retromonkey/routes/api.py` — REST API endpoints
- `requirements.txt`
- `run.py` — entry point
- `alembic/` — database migrations

#### Tasks

- [ ] **T1.1** Initialize project structure (Flask app factory pattern)
  - Create package layout with `__init__.py` files
  - Set up `requirements.txt` with core deps: flask, flask-sqlalchemy, flask-apscheduler, requests, python-dotenv
  - Create `run.py` entry point
  - Create `config.py` with dev/prod config classes

- [ ] **T1.2** Design and implement database schema (SQLite → PostgreSQL ready)
  - **products table:** id, sku, title, description, category, condition, images (JSON), cost_price, created_at, updated_at
  - **inventory table:** id, product_id (FK), quantity_on_hand, quantity_reserved, reorder_threshold, reorder_qty, location
  - **marketplaces table:** id, name (eBay/Amazon/Kogan/Website), credentials (JSON encrypted), active, settings (JSON)
  - **listings table:** id, product_id (FK), marketplace_id (FK), external_id, title, price, status (active/ended/draft), listed_at, updated_at
  - **orders table:** id, marketplace_id (FK), external_order_id, buyer_name, buyer_email, status (pending/processing/shipped/delivered/cancelled/returned), total, currency, ordered_at, shipped_at, delivered_at
  - **order_items table:** id, order_id (FK), product_id (FK), listing_id (FK), quantity, unit_price, subtotal
  - **shipments table:** id, order_id (FK), carrier, tracking_number, shipped_at, delivered_at, label_url
  - **transactions table:** id, order_id (FK), type (sale/refund/fee/shipping/tax), amount, currency, description, timestamp
  - **fees table:** id, order_id (FK), marketplace_id (FK), fee_type (final_value/payment_processing/shipping/packaging), amount, percentage, description
  - **suppliers table:** id, name, platform (Alibaba/etc), url, contact_email, rating, trade_assurance, response_time_hours, min_order_qty, years_on_platform, verified, notes
  - **purchase_orders table:** id, supplier_id (FK), product_id (FK), status (rfq_sent/quoted/ordered/shipped/received/cancelled), qty, unit_cost, total_cost, currency, expected_delivery, actual_delivery, tracking_number
  - **rfqs table:** id, supplier_id (FK), product_id (FK), status (sent/responded/accepted/rejected), specifications (JSON), target_qty, target_price_range, sent_at, response_at, response_data (JSON)
  - **messages table:** id, marketplace_id (FK nullable), channel (email/ebay_msg/whatsapp), direction (inbound/outbound), from_addr, to_addr, subject, body, related_order_id (FK nullable), related_product_id (FK nullable), ai_draft (bool), approved (bool), sent_at, created_at
  - **supplier_scores table:** id, supplier_id (FK), purchase_order_id (FK), defect_rate, delivery_on_time, packaging_quality, communication_rating, overall_score, notes
  - Create SQLAlchemy models with relationships
  - Set up Alembic for migrations

- [ ] **T1.3** Implement LLM Router service
  - `llm_router.py` — routes requests to Claude API or Ollama based on task complexity
  - Task classification: `simple` → Ollama qwen3, `complex` → Claude API, `rule` → no LLM
  - Fallback chain: Claude → Ollama → rule engine
  - Cost tracking per request
  - Prompt templates for common tasks (listing generation, email drafting, etc.)

- [ ] **T1.4** Implement inventory management service
  - CRUD operations for products and inventory
  - Stock reservation (when order placed, reserve stock)
  - Stock release (when order cancelled)
  - Low-stock detection → trigger reorder workflow
  - Cross-marketplace quantity sync logic (shared pool vs allocated)

- [ ] **T1.5** Create REST API foundation
  - `/api/products` — CRUD for products
  - `/api/inventory` — stock levels, adjustments
  - `/api/orders` — order listing, status updates
  - `/api/marketplaces` — marketplace configuration
  - `/api/health` — system status, LLM availability
  - Auth middleware (API key for internal, OAuth for external)

- [ ] **T1.6** Set up APScheduler for cron jobs
  - Order polling (every 15 min per marketplace)
  - Inventory sync (every 30 min)
  - Price monitoring (daily)
  - Reorder check (daily)
  - Report generation (weekly)

---

### Agent 2 — Marketplace Connectors

**Files to create:**
- `retromonkey/connectors/` — marketplace API clients
- `retromonkey/connectors/__init__.py`
- `retromonkey/connectors/base.py` — abstract base connector
- `retromonkey/connectors/ebay.py` — eBay full API client
- `retromonkey/connectors/amazon.py` — Amazon SP-API client
- `retromonkey/connectors/kogan.py` — Kogan connector
- `retromonkey/connectors/website.py` — self-hosted store connector
- `retromonkey/services/sync.py` — cross-platform inventory sync
- `retromonkey/routes/marketplace.py` — marketplace API routes
- `ebay_mcp.py` — MCP server for eBay tools (Claude integration)

#### Tasks

- [ ] **T2.1** Build base connector abstract class
  - Common interface: `list_item()`, `update_listing()`, `get_orders()`, `ship_order()`, `get_inventory()`, `search()`
  - Auth management (token storage, refresh)
  - Rate limiting per marketplace
  - Error handling and retry logic
  - Logging per request/response

- [ ] **T2.2** eBay connector — Authentication
  - OAuth 2.0 flow (authorization code grant)
  - Token storage and auto-refresh
  - Sandbox vs production environment toggle
  - Credential management via config

- [ ] **T2.3** eBay connector — Inventory & Listing
  - `createOrReplaceInventoryItem` — register product (SKU, images, condition, item specifics)
  - `createOffer` — set price, quantity, category, listing policies
  - `publishOffer` — go live
  - `bulkCreateOffer` — batch up to 25 listings
  - `updateOffer` — price/quantity changes
  - `withdrawOffer` — end listing
  - `getInventoryItems` — pull current inventory from eBay

- [ ] **T2.4** eBay connector — Orders & Fulfillment
  - `getOrders` — pull orders by date range, status
  - `getOrder` — single order details
  - `createShippingFulfillment` — mark shipped with carrier + tracking
  - Webhook listener for `ORDER.CREATED`, `ITEM_SOLD`, `ACCOUNT_DISPUTE`
  - Order state machine: pending → processing → shipped → delivered

- [ ] **T2.5** eBay connector — Marketing & Analytics
  - `createCampaign` — Promoted Listings (CPS/CPC)
  - `getCampaign` + `getReport` — campaign performance
  - `getTrafficReport` — listing traffic data
  - `getSellerDashboard` — seller metrics
  - Auto-bid adjustment based on conversion rate

- [ ] **T2.6** eBay connector — Browse & Research
  - `search` — product search for competitor research
  - `getItem` — listing details
  - `getDefaultCategoryTree` + `getCategorySuggestions` — auto-categorization
  - `search` (Catalog) — match to eBay catalog for visibility

- [ ] **T2.7** eBay MCP Server (`ebay_mcp.py`)
  - Expose eBay operations as MCP tools:
    - `ebay_list_item`, `ebay_bulk_list`, `ebay_get_orders`, `ebay_ship_order`
    - `ebay_get_inventory`, `ebay_update_price`, `ebay_search`
    - `ebay_create_campaign`, `ebay_get_analytics`, `ebay_get_messages`
  - Register in `.mcp.json` for Claude integration
  - Allows conversational eBay management

- [ ] **T2.8** Amazon SP-API connector
  - Auth (AWS Signature v4, LWA tokens)
  - Listings: create/update product listings
  - Orders: pull and filter orders
  - Fulfillment: FBA inbound/outbound
  - Pricing: competitive pricing data
  - Reports: sales, inventory, fee reports
  - Notifications: webhook for order/listing events

- [ ] **T2.9** Kogan connector
  - API discovery (seller portal API or browser automation fallback)
  - Product listing, order management, shipment tracking

- [ ] **T2.10** Cross-platform inventory sync service
  - Shared inventory pool across all marketplaces
  - Reserve stock on order placement
  - Release stock on cancellation
  - Prevent overselling with quantity locking
  - Reconcile discrepancies between platforms
  - Scheduled sync every 30 minutes

- [ ] **T2.11** Marketplace API routes
  - `POST /api/marketplace/ebay/list` — list product on eBay
  - `POST /api/marketplace/ebay/bulk-list` — batch list
  - `GET /api/marketplace/ebay/orders` — pull orders
  - `POST /api/marketplace/ebay/ship` — mark shipped
  - `GET /api/marketplace/ebay/inventory` — eBay inventory
  - `POST /api/marketplace/amazon/list` — list on Amazon
  - `GET /api/marketplace/amazon/orders` — Amazon orders
  - `POST /api/marketplace/sync` — trigger cross-platform sync

---

### Agent 3 — Sourcing & Research

**Files to create:**
- `retromonkey/services/research.py` — market research tools
- `retromonkey/services/sourcing.py` — Alibaba supplier pipeline
- `retromonkey/services/scoring.py` — supplier and niche scoring
- `retromonkey/services/rfq.py` — RFQ generation and tracking
- `retromonkey/services/reorder.py` — reorder automation
- `retromonkey/services/quality.py` — supplier quality control
- `retromonkey/routes/sourcing.py` — sourcing API routes
- `retromonkey/services/business_planner.py` — business plan generator

#### Tasks

- [ ] **T3.1** Market research service
  - Google Trends integration (trend data via API or scraping)
  - eBay Terapeak-style analysis (competitor sales velocity from search data)
  - Amazon BSR (Best Sellers Rank) monitoring
  - Niche opportunity scoring algorithm: `score = (demand * margin) / competition`
  - Seasonal demand forecasting (historical pattern analysis)
  - Output: research report with recommendations

- [ ] **T3.2** Alibaba supplier discovery pipeline
  - Product search (keyword, category, price range filtering)
  - Supplier data extraction (name, rating, trade assurance, MOQ, price, response time)
  - Structured data storage in suppliers table

- [ ] **T3.3** Supplier scoring algorithm
  - Weighted multi-factor scoring:
    - Trade Assurance status (25%)
    - Supplier rating & review count (20%)
    - Response time (15%)
    - MOQ vs target quantity (15%)
    - Price competitiveness vs median (15%)
    - Years on platform + verified status (10%)
  - Output: ranked supplier list with scores and comparison

- [ ] **T3.4** RFQ automation
  - Generate RFQ from product specifications + target price/qty
  - Send to top 5 scored suppliers
  - Track responses, parse key terms (price, MOQ, lead time, shipping)
  - Side-by-side comparison table generation
  - Recommendation engine: best overall vs best price vs fastest delivery

- [ ] **T3.5** Reorder automation
  - Monitor inventory levels across all marketplaces (from Agent 2's sync service)
  - When stock hits reorder threshold: auto-generate Purchase Order to known supplier
  - Track supplier shipment → warehouse receipt
  - Update inventory quantities on receipt
  - Alert on delayed shipments

- [ ] **T3.6** Supplier quality control
  - Log supplier performance per batch:
    - Defect rate (%)
    - Delivery on-time (%)
    - Packaging quality (1-5)
    - Communication rating (1-5)
  - Calculate rolling `overall_score` per supplier
  - Flag suppliers below threshold for review
  - Auto-suggest alternative suppliers for flagged items
  - Supplier performance dashboard data

- [ ] **T3.7** Sourcing API routes
  - `POST /api/sourcing/research` — run market research for a niche
  - `GET /api/sourcing/suppliers` — list scored suppliers
  - `POST /api/sourcing/rfq` — generate and send RFQs
  - `GET /api/sourcing/rfq/{id}/responses` — view RFQ responses
  - `POST /api/sourcing/reorder` — trigger reorder
  - `GET /api/sourcing/quality` — supplier quality reports

- [ ] **T3.8** Business plan generator
  - Input: niche/market data from research service
  - Generate: SWOT analysis, competitive landscape, margin calculations
  - Seasonal demand forecasting
  - Pricing strategy optimizer (cost-plus, competitive, dynamic)
  - Financial projections (revenue, costs, profit by month)
  - Output: business plan document (markdown → PDF)

---

### Agent 4 — Intelligence & Automation

**Files to create:**
- `retromonkey/services/workflow.py` — workflow engine
- `retromonkey/services/gmail_client.py` — Gmail API integration
- `retromonkey/services/communications.py` — multi-channel messaging
- `retromonkey/services/pricing.py` — dynamic pricing engine
- `retromonkey/services/listing_ai.py` — AI listing optimization
- `retromonkey/services/accounting.py` — P&L, fees, tax
- `retromonkey/services/customer_service.py` — auto-response engine
- `retromonkey/routes/intelligence.py` — automation API routes
- `retromonkey/workflows/` — workflow templates (YAML/JSON)

#### Tasks

- [ ] **T4.1** Workflow engine
  - Trigger-action pipeline system
  - Event types: order_received, order_shipped, low_stock, price_change, message_received, return_requested
  - Action types: send_email, update_listing, create_order, generate_report, call_llm, notify
  - Template workflows:
    - New product → research → list → optimize
    - Order → fulfillment → tracking → customer update
    - Low stock → reorder from supplier → update quantities
    - Return → refund → restock → quality flag
  - Scheduled task runner (price adjustments, listing renewals, review monitoring)
  - Integration with APScheduler (from Agent 1)

- [ ] **T4.2** Gmail integration
  - Google OAuth 2.0 setup for Gmail API
  - Read: watch for order confirmations, supplier emails, customer inquiries, payment notifications, dispute emails
  - Parse: extract structured data (order numbers, tracking numbers, amounts, supplier quotes)
  - Write: send order confirmations, shipping notifications, review requests, supplier RFQs
  - Labels & filters: auto-categorize by type (orders, suppliers, customers, disputes)
  - Thread tracking for conversation context

- [ ] **T4.3** Multi-channel communications hub
  - **Gmail** — via Gmail API (T4.2)
  - **eBay Messages** — via eBay Post-Order API — auto-respond to common buyer questions
  - **WhatsApp Business** — supplier communication (API or browser automation)
  - Unified inbox view across channels
  - AI-drafted responses with human approval queue
  - Template library: order updates, return handling, review requests, dispute responses

- [ ] **T4.4** AI listing optimization
  - Product description generator (SEO-optimized titles, bullet points, descriptions)
  - Keyword research from eBay/Amazon search suggestions
  - A/B testing framework for titles/descriptions
  - Image optimization suggestions
  - Category suggestion via eBay Taxonomy API
  - Feed into Agent 2's listing flow

- [ ] **T4.5** Dynamic pricing engine
  - Competitor price monitoring (eBay Buy Browse, Amazon Pricing API)
  - Demand signal analysis (search volume, sell-through rate)
  - Pricing strategies: cost-plus, competitive, dynamic (surge/practice)
  - Min/max price guards (never sell below cost + min margin)
  - Scheduled price adjustments (daily or on competitor change)
  - Price history tracking

- [ ] **T4.6** Accounting engine
  - Automated profit/loss tracking per SKU, per order
  - Fee calculator:
    - eBay final value fees (category-dependent %)
    - PayPal/Stripe processing fees
    - Shipping costs (carrier + weight/dim)
    - Packaging costs
  - Tax estimation (GST/VAT/sales tax by jurisdiction)
  - Cash flow projections (30/60/90 day)
  - Expense categorization and receipt matching
  - Spreadsheet export (CSV/XLSX)

- [ ] **T4.7** Customer service automation
  - Auto-respond to common buyer questions (FAQ matching via LLM)
  - Return/dispute handler: classify severity → draft response → route
  - Review request automation (post-delivery, configurable timing)
  - Feedback monitoring and response
  - Escalation rules: complex issues → human queue

- [ ] **T4.8** Intelligence API routes
  - `POST /api/intelligence/workflow/trigger` — manually trigger workflow
  - `GET /api/intelligence/workflow/status` — workflow execution history
  - `POST /api/intelligence/pricing/update` — trigger price recalculation
  - `GET /api/intelligence/accounting/pnl` — profit/loss report
  - `GET /api/intelligence/accounting/fees` — fee breakdown
  - `POST /api/intelligence/listing/optimize` — AI optimize a listing
  - `GET /api/intelligence/communications/inbox` — unified inbox
  - `POST /api/intelligence/communications/reply` — send response

---

### Agent 5 — Dashboard & Frontend

**Files to create:**
- `retromonkey/templates/` — Jinja2 templates (or Next.js app)
- `retromonkey/templates/base.html` — layout shell
- `retromonkey/templates/dashboard.html` — main dashboard
- `retromonkey/templates/products.html` — product management
- `retromonkey/templates/orders.html` — order management
- `retromonkey/templates/listings.html` — marketplace listings
- `retromonkey/templates/sourcing.html` — supplier/sourcing view
- `retromonkey/templates/finance.html` — financial dashboard
- `retromonkey/templates/communications.html` — inbox view
- `retromonkey/templates/settings.html` — configuration
- `retromonkey/static/` — CSS, JS, images
- `retromonkey/static/css/` — stylesheets
- `retromonkey/static/js/` — frontend JS
- `retromonkey/routes/pages.py` — page routes

#### Tasks

- [ ] **T5.1** Dashboard layout and navigation
  - Base template with sidebar navigation
  - Sections: Dashboard, Products, Orders, Listings, Sourcing, Finance, Communications, Settings
  - Responsive design (works on desktop + tablet)
  - Dark/light theme
  - Global search bar (search products, orders, suppliers)

- [ ] **T5.2** Main dashboard page
  - KPI cards: active listings, orders today, revenue today, pending shipments, low-stock alerts
  - Recent orders table (last 10)
  - Revenue chart (7-day trend)
  - Marketplace status indicators (API health)
  - AI cost tracker (today's spend)
  - Workflow status (running/recently completed)

- [ ] **T5.3** Product management view
  - Product list with filters (category, status, marketplace)
  - Product detail page (all fields, images, listing history)
  - Add/edit product form (with AI description generation button)
  - Bulk actions (list on marketplace, update prices, export)
  - Inventory levels per product with reorder indicators

- [ ] **T5.4** Order management view
  - Order list with status filters and date range
  - Order detail page (items, buyer info, shipment, fees, profit)
  - Status workflow actions (process → ship → complete)
  - Shipping label generation integration
  - Batch operations (mark shipped, print invoices)

- [ ] **T5.5** Marketplace listings view
  - All listings across marketplaces in one table
  - Filter by marketplace, status, category
  - Listing performance metrics (views, clicks, sell-through)
  - Quick actions: edit price, end listing, relist, promote
  - eBay campaign management (create/manage Promoted Listings)

- [ ] **T5.6** Sourcing & supplier view
  - Supplier directory with scores and ratings
  - RFQ tracker (sent → responded → ordered)
  - Purchase order list with status
  - Supplier quality reports (charts: defect rate, delivery time trends)
  - Reorder alerts with one-click reorder

- [ ] **T5.7** Finance & accounting view
  - Profit/loss dashboard (per SKU, per marketplace, per period)
  - Fee breakdown charts
  - Cash flow projection graph
  - Expense categories pie chart
  - Export to spreadsheet button
  - Tax summary by jurisdiction

- [ ] **T5.8** Communications inbox
  - Unified inbox across Gmail, eBay Messages, WhatsApp
  - Message thread view with AI-suggested replies
  - Approval queue for AI-drafted responses
  - Template selector for common responses
  - Filter by channel, type, status (unread/draft/sent)

- [ ] **T5.9** Settings & configuration page
  - Marketplace credential management (OAuth flows)
  - LLM configuration (API keys, model selection)
  - Workflow templates (enable/disable, configure)
  - Notification preferences (email, webhook)
  - Reorder thresholds per product
  - Pricing strategy configuration

- [ ] **T5.10** Page routes
  - `GET /` — dashboard
  - `GET /products` — product list
  - `GET /products/{id}` — product detail
  - `GET /orders` — order list
  - `GET /orders/{id}` — order detail
  - `GET /listings` — marketplace listings
  - `GET /sourcing` — sourcing dashboard
  - `GET /finance` — financial dashboard
  - `GET /inbox` — communications
  - `GET /settings` — configuration

---

## Execution Timeline

### Sprint 1 (Week 1-2): Foundation
| Agent | Tasks | Deliverables |
|-------|-------|-------------|
| **Agent 1** | T1.1 → T1.6 | Project scaffold, DB schema, LLM router, inventory service, API base, scheduler |
| **Agent 2** | T2.1, T2.2 | Base connector, eBay auth |
| **Agent 3** | T3.1 | Market research service |
| **Agent 4** | T4.1 (partial) | Workflow engine skeleton |
| **Agent 5** | T5.1, T5.2 | Layout shell, main dashboard |

### Sprint 2 (Week 3-4): Marketplace Core
| Agent | Tasks | Deliverables |
|-------|-------|-------------|
| **Agent 1** | Support/blocking issues | Stable API + DB |
| **Agent 2** | T2.3 → T2.6 | eBay inventory, listings, orders, marketing, browse |
| **Agent 3** | T3.2, T3.3 | Alibaba search, supplier scoring |
| **Agent 4** | T4.2, T4.6 | Gmail integration, accounting basics |
| **Agent 5** | T5.3, T5.4 | Product + order views |

### Sprint 3 (Week 5-6): Sourcing & Comms
| Agent | Tasks | Deliverables |
|-------|-------|-------------|
| **Agent 2** | T2.7, T2.10, T2.11 | eBay MCP server, inventory sync, marketplace routes |
| **Agent 3** | T3.4, T3.5, T3.7 | RFQ automation, reorder, sourcing API |
| **Agent 4** | T4.3, T4.7 | Communications hub, customer service |
| **Agent 5** | T5.5, T5.6, T5.8 | Listings, sourcing, inbox views |

### Sprint 4 (Week 7-8): Intelligence
| Agent | Tasks | Deliverables |
|-------|-------|-------------|
| **Agent 2** | T2.8, T2.9 | Amazon SP-API, Kogan connector |
| **Agent 3** | T3.6, T3.8 | Quality control, business planner |
| **Agent 4** | T4.4, T4.5, T4.8 | AI listing optimization, pricing engine, intelligence API |
| **Agent 5** | T5.7, T5.9, T5.10 | Finance view, settings, page routes |

### Sprint 5 (Week 9-10): Integration & Polish
| Agent | Tasks | Deliverables |
|-------|-------|-------------|
| **All** | End-to-end testing, bug fixes, performance tuning | Production-ready system |

---

## Dependency Graph

```
Agent 1 (Foundation)
  ├── Agent 2 (Marketplaces) ──→ needs DB schema + inventory service
  ├── Agent 3 (Sourcing) ──→ needs DB schema + inventory data
  ├── Agent 4 (Intelligence) ──→ needs marketplace connectors + DB
  └── Agent 5 (Dashboard) ──→ needs all API endpoints
```

**Critical path:** Agent 1 → Agent 2 → Agent 4 → Agent 5
**Parallel tracks:** Agent 3 can run alongside Agent 2 once DB is ready

---

## Tech Stack Summary

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.13, Flask, SQLAlchemy |
| Database | SQLite (dev) → PostgreSQL (prod) |
| Scheduler | APScheduler |
| AI - Complex | Claude API (Sonnet 4.6) |
| AI - Simple | Ollama qwen3 (local) |
| AI - Free | Rule engine (deterministic) |
| Marketplace APIs | eBay (Sell/Buy/Commerce/Marketing), Amazon SP-API |
| Email | Gmail API (Google OAuth 2.0) |
| MCP | Custom eBay MCP server |
| Frontend | Flask templates + HTMX (or Next.js) |
| Workflow | n8n (self-hosted) or custom Python |

---

## Key Metrics (Success Criteria)

| Metric | Target |
|--------|--------|
| End-to-end listing flow | Working by Sprint 2 |
| Order → Ship automation | Working by Sprint 2 |
| Alibaba sourcing pipeline | Working by Sprint 3 |
| Cross-platform sync | Working by Sprint 3 |
| AI listing optimization | Working by Sprint 4 |
| Dynamic pricing | Working by Sprint 4 |
| Full dashboard | Complete by Sprint 4 |
| Production ready | Sprint 5 |

---

## Cost Model

| Component | Daily Cost |
|-----------|-----------|
| Claude API (complex tasks) | ~$2-3/day |
| Ollama qwen3 (local, electricity) | ~$0.50/day |
| Rule engine | $0 |
| Hosting (VPS) | ~$1/day |
| **Total** | **~$3.50-5/day** |

---

## Next Steps

1. Review and approve this plan
2. Launch Agent 1 (Foundation) immediately — blocks everything else
3. Launch Agents 2-5 in parallel once their dependencies are met
4. Daily sync on progress via the dashboard
5. End-of-sprint demos for each phase

---

*RetroMonkey — the AI store manager that works 24/7 for the price of a coffee.*
