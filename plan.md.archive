# RetroMonkey — Workflow Overhaul Plan

## Context
RetroMonkey just completed its first sale (manual dropship via AliExpress). All eBay listings delisted. The codebase has 85 MCP tools, 108 endpoints, 21 services, and a workflow engine — but nothing is wired together. eBay orders never enter the DB, workflows never trigger, the sourcing scraper is dead, and email confirmations fail. The user wants to: document all workflows, fix broken automation, build proper dropship flows, and set up the business model (dropship-first, stock later).

**AliExpress seller account**: `ae935127` (registered). **API developer account**: NOT YET — apply at openservice.aliexpress.com (1-2 day approval).

---

# AliExpress Open Platform API — Complete Reference

## Getting Access
1. Register developer account at https://openservice.aliexpress.com
2. Create an app (App Management tab → Self Developer type)
3. 1-2 business day approval → receive `app_key` + `app_secret`
4. OAuth flow → get `access_token` + `refresh_token`

## API Base URLs
- **Migrated (TOP) APIs**: `https://api-sg.aliexpress.com/sync`
- **New (OP) APIs**: `https://api-sg.aliexpress.com/rest`
- All requests: **POST**, HMAC-SHA256 signing

## SYSTEM AUTH (4 endpoints)
| Endpoint | Description |
|----------|-------------|
| `/auth/token/create` | Generate access token from auth code |
| `/auth/token/refresh` | Refresh access token before expiry |
| `/auth/token/security/create` | Generate security token |
| `/auth/token/security/refresh` | Refresh security token |

## DROPSHIPPING API (13 endpoints — 6 active, 7 deprecated)
| Endpoint | Method | Description | Status |
|----------|--------|-------------|--------|
| `aliexpress.ds.order.create` | `createOrder()` | **Place dropship order** with address + product items | ACTIVE |
| `aliexpress.ds.product.get` | `productDetails()` | **Get product info** — price, SKUs, images, specs | ACTIVE |
| `aliexpress.logistics.buyer.freight.calculate` | `shippingInfo()` | **Calculate shipping costs** for product + destination | ACTIVE |
| `aliexpress.trade.ds.order.get` | `orderDetails()` | **Get order details** — status, logistics, items | ACTIVE |
| `aliexpress.ds.category.get` | `getCategories()` | Browse product categories | ACTIVE |
| `aliexpress.ds.feedname.get` | `queryFeaturedPromos()` | List promotional campaigns | ACTIVE |
| `aliexpress.logistics.buyer.freight.get` | freightInfo() | Get freight info (older) | DEPRECATED |
| `aliexpress.logistics.ds.trackinginfo.query` | trackingInfo() | Get tracking events | DEPRECATED |
| `aliexpress.ds.recommend.feed.get` | queryfeaturedPromoProducts() | Get promo products | DEPRECATED |
| `aliexpress.ds.add.info` | addDropshippingInfo() | Add DS info to order | DEPRECATED |
| `aliexpress.ds.commissionorder.listbyindex` | ordersListByIndex() | List orders by index | DEPRECATED |
| `aliexpress.ds.member.orderdata.submit` | submitOrderData() | Submit order data | DEPRECATED |

### createOrder — The Key Endpoint
```json
{
  "logistics_address": {
    "full_name": "Wade Sorensen",
    "mobile_no": "61457870354",
    "phone_country": "+61",
    "address": "260 Macquarie St",
    "city": "South Windsor",
    "province": "NSW",
    "country": "AU",
    "zip": "2756"
  },
  "product_items": [{
    "product_id": 1005004043442825,
    "product_count": 1,
    "sku_attr": "14:350853#Black;5:361386",
    "logistics_service_name": "AliExpress Standard Shipping",
    "order_memo": "eBay order #12345"
  }],
  "promo_and_payment": {
    "payment_method": "CREDIT_CARD"
  }
}
```
Returns order numbers for payment + fulfillment tracking.

## AFFILIATE API (12 endpoints)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `aliexpress.affiliate.product.query` | queryProducts() | **Search products by keywords** — replaces dead scraper |
| `aliexpress.affiliate.productdetail.get` | productDetails() | Product detail with commission % |
| `aliexpress.affiliate.hotproduct.query` | getHotProducts() | Trending products |
| `aliexpress.affiliate.hotproduct.download` | getHotProductsDownload() | Download hot products data |
| `aliexpress.affiliate.link.generate` | generateAffiliateLinks() | Generate tracking links |
| `aliexpress.affiliate.category.get` | getCategories() | Get categories |
| `aliexpress.affiliate.featuredpromo.get` | featuredPromoInfo() | Featured promo details |
| `aliexpress.affiliate.featuredpromo.products.get` | featuredPromoProducts() | Products in a promo |
| `aliexpress.affiliate.product.smartmatch` | smartMatchProducts() | Find similar products |
| `aliexpress.affiliate.order.get` | orderInfo() | Affiliate order detail |
| `aliexpress.affiliate.order.list` | ordersList() | List affiliate orders |
| `aliexpress.affiliate.order.listbyindex` | ordersListByIndex() | Paginated order list |

## SDK: `ae_sdk` (npm, 65 stars, MIT)
- Unofficial TypeScript SDK by moh3a
- Three clients: `AESystemClient`, `DropshipperClient`, `AffiliateClient`
- Fully typed, handles HMAC-SHA256 signing, auth, response normalization
- `callAPIDirectly()` for undocumented endpoints
- Install: `npm install ae_sdk`
- Source: https://github.com/moh3a/ae_sdk

### SDK Usage
```typescript
import { DropshipperClient } from "ae_sdk";

const client = new DropshipperClient({
  app_key: "YOUR_APP_KEY",
  app_secret: "YOUR_APP_SECRET",
  session: "ACCESS_TOKEN_FROM_AUTH_FLOW",
});

// Get product details
const product = await client.productDetails({
  product_id: 1005004043442825,
  ship_to_country: "AU",
  target_currency: "USD",
  target_language: "en",
});

// Calculate shipping
const shipping = await client.shippingInfo({
  country_code: "AU",
  product_id: 1005004043442825,
  product_num: 1,
  send_goods_country_code: "CN",
});

// Place order
const order = await client.createOrder({
  logistics_address: { /* buyer address */ },
  product_items: [{ /* product details */ }],
});

// Check order status
const details = await client.orderDetails({
  order_id: "1234567890",
});
```

## Key Sources
- AliExpress Open Platform: https://openservice.aliexpress.com
- API Reference: https://openservice.aliexpress.com/doc/api.htm
- Getting Started: https://openservice.aliexpress.com/doc/doc.htm
- ae_sdk GitHub: https://github.com/moh3a/ae_sdk
- Zuplo Developer Guide: https://zuplo.com/learning-center/aliexpress-api-guide

---

# RetroMonkey — Workflow Overhaul Plan

## Phase 1: Document Workflows

Create `WORKFLOWS.md` mapping all 10 business processes:

| # | Workflow | Status |
|---|----------|--------|
| 1 | eBay listing | Works (MCP) |
| 2 | Web store order | Partial (no workflow trigger, no email, decrements stock for dropship) |
| 3 | eBay order sync | **Broken** — orders never enter DB |
| 4 | Supplier sourcing | **Broken** — scraper returns empty → **AliExpress API will replace** |
| 5 | Dropship fulfillment | **Missing** — no model, no tracking bridge |
| 6 | Shipping/tracking | Manual only |
| 7 | Customer support | Manual only |
| 8 | Reporting | Works (but empty data) |
| 9 | Stock management | Works (not adapted for dropship) |
| 10 | Pricing | Stub/placeholder |

**Files**: NEW `WORKFLOWS.md`

---

## Phase 2: Fix Critical Automation

### 2.1 eBay Order Sync (P0 — biggest impact)
**Problem**: `poll_orders` scheduler calls `conn.get_orders()` but never writes Order records. Just alerts.

**Fix**:
- NEW `retromonkey/services/order_sync.py` — fetches eBay orders, deduplicates by `external_order_id`, creates `Order` + `OrderItem` records, matches SKUs to local Products
- MODIFY `retromonkey/app.py` — replace `poll_orders` body to use OrderSyncService
- MODIFY `retromonkey/connectors/ebay.py` — enhance `_parse_order()` to extract `shippingDetails` (address, city, state, postcode, country)
- MODIFY `retromonkey_mcp.py` — add `order_sync_ebay` MCP tool

### 2.2 Workflow Loading (P0 — 1-line fix)
**Problem**: `svc_workflow()` in MCP server creates `WorkflowEngine(db)` without loading YAML templates.

**Fix**: Pass `workflows_dir` param in `retromonkey_mcp.py` line ~106.

### 2.3 Wire Webhooks → Workflows (P1)
**Problem**: `webhooks.py` has `# TODO: trigger order processing workflow`. Stripe handler in `store.py` doesn't trigger either.

**Fix**: Add `WorkflowEngine.trigger('order_received', context)` in both webhook handlers.

### 2.4 Fix Email Confirmation (P0)
**Problem**: Store uses SMTP (Zoho) — not configured. Gmail OAuth broken. Only Resend works.

**Fix**: Replace `send_order_confirmation()` in `store.py` to use `resend_sender.py`.

### 2.5 Replace Sourcing with AliExpress API (P1)
**Problem**: BeautifulSoup scraper on Alibaba returns empty (JS-rendered pages).

**Fix**:
- NEW `retromonkey/connectors/aliexpress.py` — AliExpress API connector (product search, product details, order creation, shipping calculation, order tracking)
- Uses `requests` with HMAC-SHA256 signing (Python equivalent of ae_sdk)
- Endpoints: `aliexpress.affiliate.product.query`, `aliexpress.ds.product.get`, `aliexpress.ds.order.create`, `aliexpress.logistics.buyer.freight.calculate`, `aliexpress.trade.ds.order.get`
- Requires app_key + app_secret + access_token in .env
- Keep manual entry as fallback

### 2.6 Scheduler Logging (P1)
**Problem**: All scheduler jobs silently `except Exception: pass`.

**Fix**: Replace `pass` with `app.logger.error()` in all scheduler functions in `app.py`.

---

## Phase 3: Build Dropship Workflows

### 3.1 DropshipOrder Model (P2)
NEW model in `retromonkey/models/supplier.py`:
- `order_id` FK → orders table
- `supplier_id` FK → suppliers table
- `supplier_order_url`, `supplier_order_id`, `supplier_tracking`
- `unit_cost`, `status` (pending → ordered → tracking_received → shipped → delivered)
- Timestamps for each status transition

### 3.2 Dropship Workflow YAML (P2)
NEW `retromonkey/workflows/dropship_fulfillment.yml`:
- Trigger: `order_received`
- Actions: Telegram alert with order details, create DropshipOrder record, notify human to source
- Conditional logic: different flow for eBay vs web store

### 3.3 Dropship MCP Tools (P2)
4 new tools in `retromonkey_mcp.py`:
- `dropship_record` — link Order to supplier with cost
- `dropship_update_tracking` — add supplier tracking number
- `dropship_mark_shipped` — mark shipped, call `EbayConnector.ship_order()`
- `dropship_list_pending` — list all pending dropship orders

### 3.4 Fix Web Store for Dropship (P2 — 1-line fix)
**Problem**: Stripe webhook decrements `quantity_on_hand` for dropship products (always 0).

**Fix**: Only decrement if `quantity_on_hand > 0` in `store.py`.

---

## Phase 4: Business Model Setup

### 4.1 Sourcing Workflow (P3)
Mostly manual via existing MCP tools. Add `should_stock()` advisory method to inventory service — checks order frequency, margins, supplier reliability.

### 4.2 Multi-channel (P3)
Shared inventory pool already exists. For dropship, list with quantity=1. Keep one channel at a time for now.

---

## Implementation Order

| Step | What | Effort |
|------|------|--------|
| 0 | **Apply for AliExpress API developer account** | 15 min (forms) + 1-2 day wait |
| 1 | Create WORKFLOWS.md documentation | 30 min |
| 2 | Fix workflow loading in MCP (1 line) | 5 min |
| 3 | Fix email confirmation (use Resend) | 30 min |
| 4 | Fix scheduler logging | 15 min |
| 5 | Fix web store stock decrement for dropship | 5 min |
| 6 | eBay order sync service + enhance parse_order | 2h |
| 7 | Wire webhooks → workflow engine | 30 min |
| 8 | **Build AliExpress connector** (product search, product details, order create, shipping calc, order tracking) | 3h |
| 9 | DropshipOrder model + migration | 1h |
| 10 | Dropship workflow YAML | 30 min |
| 11 | Dropship MCP tools (4 tools) | 2h |
| 12 | Stock building advisory | 30 min |

## Verification
- `pytest` — run existing tests after each change
- Manual test: trigger `order_sync_ebay` MCP tool → verify Order appears in DB
- Manual test: trigger workflow via `workflow_trigger` MCP tool → verify Telegram/email fires
- Deploy to Oracle with `./deploy.sh`, health check
- Test full flow: eBay order → DB sync → workflow trigger → AliExpress product search → createOrder → tracking → eBay ship update

## Key Files
- `retromonkey/services/order_sync.py` (NEW)
- `retromonkey/connectors/aliexpress.py` (NEW — AliExpress API connector)
- `retromonkey/models/supplier.py` (MODIFY — add DropshipOrder)
- `retromonkey/connectors/ebay.py` (MODIFY — parse shipping details)
- `retromonkey/app.py` (MODIFY — poll_orders, scheduler logging)
- `retromonkey/services/workflow.py` (READ — understand trigger API)
- `retromonkey/routes/webhooks.py` (MODIFY — wire triggers)
- `retromonkey/routes/store.py` (MODIFY — email, stock decrement, workflow trigger)
- `retromonkey/services/sourcing.py` (MODIFY — use AliExpress API)
- `retromonkey/services/resend_sender.py` (READ — use for email fix)
- `retromonkey_mcp.py` (MODIFY — workflow loading, new tools)
