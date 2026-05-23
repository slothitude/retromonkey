# RetroMonkey — AI Store Manager

**Full-spectrum autonomous e-commerce operations powered by AI agents.**

---

## 1. Vision

An AI store manager that runs the entire retail operation — sourcing, listing, selling, shipping, accounting, and optimization — with minimal human oversight. Think of it as hiring a 24/7 store manager for $5/day instead of $25/hour.

---

## 2. Core Modules

### 2.1 Business Planner
- Generates business plans from niche/market research
- SWOT analysis, competitive landscape, margin calculations
- Seasonal demand forecasting
- Pricing strategy optimizer (cost-plus, competitive, dynamic)
- Outputs: business plan PDF, financial projections, market entry strategy

### 2.2 Accounting Engine
- Automated profit/loss tracking per SKU
- Fee calculator (eBay final value fees, PayPal/Stripe, shipping, packaging)
- Tax estimation (GST/VAT/sales tax by jurisdiction)
- Cash flow projections
- Expense categorization and receipt matching
- Integration: spreadsheet export, simple dashboard

### 2.3 Research & Sourcing Agent
- Market trend analysis (Google Trends, eBay Terapeak, Amazon BSR)
- Competitor price monitoring
- Niche opportunity scoring (demand vs competition vs margin)
- Alibaba supplier discovery, verification, and comparison
- Automated RFQ generation and response analysis
- Supplier reliability scoring (trade assurance, rating, response time)

### 2.4 Multi-Marketplace Manager
- **eBay** — full API integration (Sell API, Inventory API, Fulfillment API, Marketing API)
- **Amazon** — SP-API integration (listings, orders, FBA, reports)
- **Kogan** — listing and order management
- Cross-platform inventory sync (prevent overselling)
- Unified message/inquiry inbox across all platforms
- Centralized order management dashboard

### 2.5 Website Store
- Self-hosted storefront (Shopify alternative — Flask/Next.js)
- Product catalog auto-synced from inventory database
- SEO-optimized product pages (AI-generated descriptions, titles, keywords)
- Cart, checkout, payment processing (Stripe/PayPal)
- Analytics and conversion tracking

### 2.6 Workflow Automation Engine
- Trigger-action pipelines (order received → pick/pack → ship → track → follow up)
- n8n or custom workflow orchestrator
- Templates for common flows:
  - New product → research → list → optimize
  - Order → fulfillment → tracking → customer update
  - Low stock → reorder from supplier → update quantities
  - Return → refund → restock → quality flag
- Scheduled tasks: price adjustments, listing renewals, review monitoring

### 2.7 Communications Hub
- **Gmail** — read/write via Gmail API, order confirmations, supplier emails
- **eBay Messages** — auto-respond to common buyer questions
- **WhatsApp/Business** — supplier communication
- Templates for: order updates, return handling, review requests, dispute responses
- AI-drafted responses with human approval queue

---

## 3. Marketplace Integrations (Deep Dive)

### 3.1 eBay — Full API Coverage

**Authentication:** OAuth 2.0 (client credentials + user token refresh)

| API | Key Endpoints | Use Case |
|-----|---------------|----------|
| **Sell Inventory** | `createOrReplaceInventoryItem`, `createOffer`, `publishOffer`, `bulkCreateOffer` | Create/manage products, publish listings in bulk (up to 25 at a time) |
| **Sell Fulfillment** | `getOrders`, `getOrder`, `createShippingFulfillment` | Pull orders, mark shipped with carrier + tracking number |
| **Sell Marketing** | `createCampaign` (CPS/CPC), manage ad groups, item promotions | Run Promoted Listings campaigns, set daily budgets, track ROI |
| **Sell Analytics** | `getTrafficReport`, `getSellerDashboard` | Sales metrics, traffic data, seller performance |
| **Commerce Taxonomy** | `getDefaultCategoryTree`, `getCategorySuggestions` | Auto-categorize products |
| **Commerce Catalog** | `search`, `getProduct` | Match products to eBay catalog for better visibility |
| **Buy Browse** | `search`, `getItem` | Competitive research, price monitoring |
| **Notification API** | Webhooks for order created, item sold, account disputes | Real-time event-driven workflows |

**Listing Flow (Automated):**
1. AI generates title, description, item specifics from product data
2. `createOrReplaceInventoryItem` — register product with SKU, images, condition
3. `createOffer` — set price, quantity, category, listing policies (payment/return/fulfillment)
4. `publishOffer` — go live
5. `bulkCreateOffer` — batch up to 25 listings at once for scale

**Fulfillment Flow (Automated):**
1. Webhook fires → `ORDER.CREATED` notification
2. `getOrder` — pull full order details
3. Generate pick/pack instructions
4. After shipping: `createShippingFulfillment` with carrier code + tracking number
5. Auto-send tracking to buyer via email/message

**Marketing Flow (Automated):**
1. `createCampaign` — Promoted Listings with CPS (cost per sale %) or CPC (cost per click)
2. Set daily budget, targeting type (SMART or MANUAL)
3. Monitor via `getCampaign` + `getReport` → auto-adjust bids based on conversion rate

### 3.2 Amazon — SP-API

| Function | API Group | Notes |
|----------|-----------|-------|
| Listings | Catalog Items, Listings Items | Create/update product listings |
| Orders | Orders API | Pull orders, filter by status/date |
| Fulfillment | FBA Inbound, FBA Outbound | Ship via FBA or Merchant Fulfilled |
| Pricing | Product Pricing, Pricing | Competitive pricing data |
| Reports | Reports API | Sales reports, inventory reports, fees |
| Notifications | Notifications API | Webhooks for order, listing, fulfillment events |

### 3.3 Kogan.com
- Seller portal API (if available) or browser automation fallback
- Product listing, order management, shipment tracking

---

## 4. Alibaba Sourcing Automation

### 4.1 Supplier Discovery Pipeline
1. **Product Search** — Alibaba search API or structured scraping (keyword, category, price range)
2. **Supplier Scoring** — weighted algorithm:
   - Trade Assurance status (weight: 25%)
   - Supplier rating & review count (20%)
   - Response time (15%)
   - Minimum order quantity vs our target (15%)
   - Price competitiveness vs median (15%)
   - Years on platform, verified status (10%)
3. **RFQ Automation** — generate and send RFQs to top 5 suppliers with:
   - Product specifications
   - Target quantity and price range
   - Shipping requirements
   - Quality assurance expectations
4. **Response Analysis** — parse supplier responses, extract key terms, compare side-by-side
5. **Order Placement** — via Alibaba Trade Assurance for buyer protection

### 4.2 Reorder Automation
- Monitor inventory levels across all marketplaces
- When stock hits reorder threshold: auto-generate PO to known supplier
- Track shipment from supplier → warehouse
- Update inventory quantities upon receipt

### 4.3 Quality Control Workflow
- Log supplier performance per batch (defect rate, delivery time, packaging quality)
- Flag suppliers below threshold for review
- Auto-suggest alternative suppliers for flagged items

---

## 5. Gmail Integration

- **Gmail API** (Google OAuth 2.0) for full read/write access
- **Watch for:**
  - Order confirmations → parse and log
  - Supplier emails → extract quotes, shipping updates
  - Customer inquiries → draft response, queue for approval
  - Payment notifications → reconcile with orders
  - Return/dispute emails → trigger return workflow
- **Send:**
  - Order confirmation emails
  - Shipping notifications with tracking
  - Review request emails (post-delivery)
  - Supplier RFQ emails
- **Labels & Filters:** auto-categorize incoming mail by type (orders, suppliers, customers, disputes)

---

## 6. AI Worker Tiers

| Tier | Cost | Capability | Use Case |
|------|------|-----------|----------|
| **Claude/GPT** | ~$5/hr API | Complex reasoning, writing, strategy | Business plans, product descriptions, customer emails, dispute resolution |
| **Local LLM** (Ollama qwen3) | ~$5/day (electricity) | Simple classification, extraction, formatting | Email categorization, order parsing, listing formatting, data entry |
| **Rule Engine** | $0 | Deterministic logic | Inventory sync, fee calculation, reorder triggers, shipping label generation |

**Cost model:** Most tasks use the free rule engine or cheap local LLM. Cloud AI only for tasks requiring genuine reasoning. Target: under $5/day for full operations.

---

## 7. Architecture

```
┌─────────────────────────────────────────────────────┐
│                   RetroMonkey Core                   │
│                  (Orchestration Layer)                │
├─────────┬──────────┬──────────┬──────────┬──────────┤
│ Research │ Listing  │ Orders   │ Finance  │ Comms    │
│  Agent   │  Agent   │  Agent   │  Agent   │  Agent   │
├─────────┴──────────┴──────────┴──────────┴──────────┤
│              Shared Services Layer                    │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐            │
│  │ Inventory │ │ Workflow  │ │   LLM    │            │
│  │   DB      │ │  Engine   │ │  Router  │            │
│  └──────────┘ └──────────┘ └──────────┘            │
├─────────────────────────────────────────────────────┤
│              Marketplace Connectors                   │
│  ┌────┐ ┌────────┐ ┌───────┐ ┌────────┐ ┌────────┐ │
│  │eBay│ │Amazon  │ │Kogan  │ │Website │ │Alibaba │ │
│  └────┘ └────────┘ └───────┘ └────────┘ └────────┘ │
├─────────────────────────────────────────────────────┤
│              Communication Layer                      │
│  ┌───────┐ ┌───────────┐ ┌──────────┐              │
│  │ Gmail │ │eBay Msgs  │ │ WhatsApp │              │
│  └───────┘ └───────────┘ └──────────┘              │
└─────────────────────────────────────────────────────┘
```

### Tech Stack
- **Backend:** Python (Flask + APScheduler for cron jobs)
- **Database:** SQLite (start) → PostgreSQL (scale)
- **Workflow Engine:** n8n (self-hosted) or custom Python orchestrator
- **AI:** Claude API (complex) + Ollama/qwen3 (simple) with fallback routing
- **Marketplace APIs:** eBay (Sell/Buy/Commerce/Marketing), Amazon SP-API
- **Gmail:** Google API Python client
- **Frontend:** Simple dashboard (Flask templates or Next.js)

---

## 8. Implementation Phases

### Phase 1 — Foundation (Week 1-2)
- [ ] Set up project structure and SQLite database schema
- [ ] eBay API authentication (OAuth 2.0 flow, token refresh)
- [ ] Inventory management — CRUD for products (SKU, title, price, quantity, images)
- [ ] Basic eBay listing — `createOrReplaceInventoryItem` → `createOffer` → `publishOffer`
- [ ] Simple dashboard to view inventory and listings

### Phase 2 — Orders & Fulfillment (Week 3-4)
- [ ] eBay order polling (`getOrders`) + webhook listener (`ORDER.CREATED`)
- [ ] Order management dashboard (pending → processing → shipped → delivered)
- [ ] Shipping fulfillment — `createShippingFulfillment` with carrier + tracking
- [ ] Gmail integration — read order emails, send shipping notifications
- [ ] Accounting basics — track revenue, fees, shipping costs per order

### Phase 3 — Sourcing & Multi-Marketplace (Week 5-8)
- [ ] Alibaba supplier search and scoring algorithm
- [ ] Automated RFQ generation and response tracking
- [ ] Amazon SP-API integration (listings + orders)
- [ ] Cross-platform inventory sync (prevent overselling)
- [ ] Reorder automation (low stock → auto-PO to supplier)

### Phase 4 — Intelligence & Optimization (Week 9-12)
- [ ] AI product description generator (SEO-optimized titles, bullet points)
- [ ] Dynamic pricing engine (competitor monitoring + demand signals)
- [ ] eBay Marketing API — automated Promoted Listings campaigns
- [ ] Profit/loss reporting per SKU, per marketplace, per time period
- [ ] Customer communication automation (auto-respond, review requests)
- [ ] Business plan generator module

### Phase 5 — Scale (Month 4+)
- [ ] Website storefront (SEO, checkout, analytics)
- [ ] Kogan integration
- [ ] WhatsApp supplier communication
- [ ] Advanced analytics dashboard (sales trends, supplier performance)
- [ ] Multi-currency, multi-region support

---

## 9. MCP Server Plan — eBay Tool

Build a dedicated MCP server (`ebay_mcp.py`) exposing eBay operations as tools:

| Tool | eBay API | Description |
|------|----------|-------------|
| `ebay_list_item` | Sell Inventory | Create inventory item + offer + publish in one call |
| `ebay_bulk_list` | Sell Inventory | Bulk create up to 25 listings |
| `ebay_get_orders` | Sell Fulfillment | Pull orders by date/status |
| `ebay_ship_order` | Sell Fulfillment | Mark order shipped with tracking |
| `ebay_get_inventory` | Sell Inventory | List all inventory items with stock levels |
| `ebay_update_price` | Sell Inventory | Update offer price |
| `ebay_search` | Buy Browse | Search eBay for competitor research |
| `ebay_create_campaign` | Sell Marketing | Create Promoted Listings campaign |
| `ebay_get_analytics` | Sell Analytics | Pull traffic/sales reports |
| `ebay_get_messages` | Post-Order | Pull buyer messages |

This lets Claude (or any LLM) directly manage the eBay store through conversation.

---

## 10. Key Metrics to Track

| Metric | Target | Frequency |
|--------|--------|-----------|
| Listings active | 100+ | Daily |
| Sell-through rate | >15% | Weekly |
| Average margin | >30% | Per order |
| Order processing time | <4 hours | Per order |
| Customer response time | <1 hour | Per message |
| AI cost per order | <$0.50 | Daily |
| Reorder accuracy | >95% | Monthly |
| Supplier on-time delivery | >90% | Monthly |

---

## 11. Revenue Model (For Selling the AI Manager Itself)

If we productize RetroMonkey as a service:

| Plan | Price | Features |
|------|-------|----------|
| **Starter** | $29/mo | 1 marketplace (eBay), 100 listings, basic automation |
| **Growth** | $79/mo | 3 marketplaces, unlimited listings, sourcing agent, Gmail |
| **Scale** | $199/mo | All marketplaces, AI optimization, analytics, priority support |
| **Enterprise** | Custom | White-label, custom integrations, dedicated support |

---

*RetroMonkey — the AI store manager that works 24/7 for the price of a coffee.*
