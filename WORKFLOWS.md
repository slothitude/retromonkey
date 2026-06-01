# RetroMonkey Business Workflows

Status: Live (dropship model). eBay listings delisted, re-listing pending.

## 1. eBay Listing

**Status**: Works (MCP only)
**Trigger**: Manual via `ebay_list` MCP tool or `/api/marketplace/ebay/list`
**Flow**: Product → create inventory item → create offer → publish listing
**MCP tools**: `ebay_list`, `ebay_update_price`, `ebay_end_listing`, `ebay_bulk_list`
**Gaps**: No auto-listing from stock arrivals; no repricing automation

## 2. Web Store Order

**Status**: Partial
**Trigger**: Stripe `checkout.session.completed` webhook at `/webhook`
**Flow**: Cart → Stripe Checkout → webhook creates Order + OrderItem → send confirmation
**Known issues**:
- Email confirmation uses SMTP (Zoho) — not configured. Falls back to silent failure.
- Stock decrement happens even for dropship products (stock=0 → no-op but unnecessary code path)
- No workflow trigger after order creation
**Fixes needed**: Use Resend for email, skip decrement for dropship, trigger workflow

## 3. eBay Order Sync

**Status**: Broken — orders never enter DB
**Trigger**: `poll_orders` scheduler (every 15 min)
**Current flow**: Fetches eBay orders via API → alerts via Telegram → does NOT write to DB
**Fix**: New `OrderSyncService` — deduplicate by `external_order_id`, create Order + OrderItem records

## 4. Supplier Sourcing

**Status**: Broken — Alibaba scraper returns empty (JS-rendered pages)
**Trigger**: Manual via MCP tools or `/api/sourcing/search`
**Current flow**: BeautifulSoup scrape Alibaba → parse cards → save to Suppliers table
**Workaround**: Manual supplier entry via `sourcing_add_manual` MCP tool
**Future**: AliExpress API connector (approved, AppKey: 535696)

## 5. Dropship Fulfillment

**Status**: Missing — no model, no workflow
**Trigger**: `order_received` workflow event
**Target flow**:
1. Order received → Telegram alert
2. Human sources product on AliExpress
3. Record dropship order with cost + supplier link
4. Await tracking number
5. Update tracking → call eBay `ship_order()` if applicable
6. Mark as shipped
**New model**: `DropshipOrder` (links Order → Supplier, tracks status flow)
**New MCP tools**: `dropship_record`, `dropship_update_tracking`, `dropship_mark_shipped`, `dropship_list_pending`

## 6. Shipping / Tracking

**Status**: Manual only
**Current**: eBay `ship_order()` available but not wired to dropship flow
**Target**: Automatic ship call when dropship tracking received

## 7. Customer Support

**Status**: Manual only
**Triggers**: Gmail webhook labels emails, Telegram notifies
**MCP tools**: `comms_draft_reply`, `comms_send`, `support_auto_respond`
**Gaps**: No auto-response for common queries (WISMO, returns)

## 8. Reporting

**Status**: Works (but empty data)
**Triggers**: `daily_summary` (18:00), `weekly_report` (Mon 09:00)
**MCP tools**: `report_daily_summary`, `report_morning_briefing`, `report_weekly`, `finance_pnl`
**Gaps**: P&L data is empty until orders flow through

## 9. Stock Management

**Status**: Works (not adapted for dropship)
**Model**: `Inventory` with `quantity_on_hand` / `quantity_reserved` / `reorder_threshold`
**MCP tools**: `stock_level`, `stock_reserve`, `stock_release`, `stock_commit`, `stock_reorder_check`
**Gaps**: For dropship, stock is always 0; need `should_stock()` advisory for when to hold inventory

## 10. Pricing

**Status**: Stub / placeholder
**MCP tools**: `pricing_calculate`, `pricing_update_all`
**Gaps**: No actual repricing logic; just placeholder responses

---

## Event → Workflow Mapping

| Event | Workflow YAML | Status |
|-------|-------------|--------|
| `order_received` | `new_order_alert.yml` | YAML exists, never triggered |
| `low_stock` | `low_stock_reorder.yml` | YAML exists, never triggered |
| `return_requested` | `return_handler.yml` | YAML exists, never triggered |
| `order_received` (dropship) | `dropship_fulfillment.yml` | **Missing** — needs creation |

## Scheduler Jobs

| Job | Schedule | Wired to DB | Wired to Workflow |
|-----|----------|-------------|-------------------|
| `poll_orders` | 15 min | No | No |
| `sync_inventory` | 30 min | Yes | No |
| `reorder_check` | Daily 07:00 | Yes | No |
| `daily_checklist` | Daily 08:30 | Yes | No |
| `daily_summary` | Daily 18:00 | Yes | No |
| `weekly_report` | Mon 09:00 | Yes | No |
| `gmail_watch_renewal` | Daily 03:00 | N/A | N/A |
