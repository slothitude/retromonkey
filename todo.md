# RetroMonkey TODO

## URGENT — First Sale Fulfillment

- [ ] **Mark first eBay order as shipped**
  - Order: Anbernic RG35XX H, Buyer: Wade Sorensen, 260 Macquarie St, South Windsor NSW 2756
  - AliExpress Order: 8211895963242932 (AU$86.76 via Coopreme Game Store)
  - Waiting on AliExpress tracking number — est. delivery Jun 12
  - Once tracking received: use `dropship_update_tracking` + `dropship_mark_shipped` MCP tools
  - After delivery: request buyer review

- [ ] **Add bank details to eBay seller account**
  - Deadline: 28 Jun 2026 or selling account gets restricted
  - Do in eBay Seller Hub > Account > Payments
  - Email ref: #f6609940b1704139a99560b3d59b836a#

## Deployment & Verification

- [ ] **Deploy workflow overhaul to Oracle**
  - Two commits ready: `6a7a94f` (overhaul) + `7d071ff` (audit fixes)
  - Run `./deploy.sh` from Rog, health check after
  - Test: trigger `order_sync_ebay` MCP tool → verify Order appears in DB
  - Test: trigger workflow via `workflow_trigger` → verify Telegram/email fires

## Code — Remaining Audit Items

- [ ] **M2: AliExpress API signature validation**
  - Current HMAC signing may not match actual AliExpress spec (untested)
  - Need to test `aliexpress_search` MCP tool against live API
  - May need to use new REST API base (`/rest` not `/openapi`) and different signing

- [ ] **M4: Guard dropship_mark_shipped against missing tracking**
  - `_dropship_mark_shipped` can be called before tracking is set, silently skipping eBay ship
  - Add check: require tracking number before marking shipped

- [ ] **M5: Don't commit DB if eBay ship API fails**
  - `_dropship_mark_shipped` commits even if `conn.ship_order()` fails
  - Should rollback or at least not mark as shipped

- [ ] **M6: Alembic migration for DropshipOrder table**
  - Currently relies on `db.create_all()` — fine for now but add proper migration
  - Run `alembic revision --autogenerate -m "add dropship_orders table"`

- [ ] **M8: Fix eBay order confirmation email template**
  - `send_order_confirmation()` uses `name/qty/price` keys but order_sync stores `sku/quantity/unit_price`
  - Confirmation emails for eBay-synced orders show blank items

- [ ] **M9: eBay webhook signature verification**
  - `webhooks.py` eBay handler doesn't verify the X-API-Signature header
  - Anyone could POST fake order events
  - Low priority (webhook endpoint is behind obscurity)

## Code — Doc/Metadata Fixes

- [ ] **L2: Update WORKFLOWS.md**
  - Still says workflows are "Missing"/"Broken" that were fixed in the overhaul
  - Update status columns to reflect reality

- [ ] **L3: Fix MCP tool count comment**
  - `retromonkey_mcp.py` header comment says "76 tools" — now 95

## Infrastructure

- [ ] **Fix MX records — switch from ImprovMX to Resend**
  - Add at VentraIP: `MX @ inbound-smtp.us-east-1.amazonaws.com priority 10`
  - Enable "Receiving" on retromonkey.com.au domain in Resend dashboard
  - Cancel ImprovMX once confirmed working

- [ ] **Verify age on retromonkey.com.au Google account**
  - SafeSearch forced on, personalised ads off, Timeline off

## Email Monitoring

- [x] **Build IMAP email polling monitor** (2 Jun 2026)
  - NEW `retromonkey/services/imap_monitor.py` — IMAPMonitor class (poll Gmail via IMAP SSL)
  - Scheduler job `imap_poll` every 5 min in `app.py`
  - Sender rules with **human checkpoints**: customer/supplier emails get Telegram inline buttons
  - Auto-processes routine emails (eBay notifications, Stripe receipts)
  - Human approval needed for: buyer inquiries, customer questions, supplier quotes, Stripe disputes

- [ ] **Set up Gmail App Password for IMAP**
  - Go to https://myaccount.google.com/apppasswords
  - Generate app password for "RetroMonkey"
  - Add `IMAP_PASSWORD=<app-password>` to `.env` on Oracle
  - `IMAP_USER=retromonkey.com.au@gmail.com` (default, may not need to set)
  - **Cannot deploy IMAP monitor until this is done**

## AliExpress API

- [ ] **Complete AliExpress OAuth flow**
  - AppKey: 535696, Status: Test
  - Need to get access_token via OAuth (currently empty)
  - Without access_token, order creation and tracking won't work
  - Developer portal: openservice.aliexpress.com

- [ ] **Update AliExpress connector to match real API spec**
  - Plan doc shows new REST endpoints (`/rest`) vs old TOP (`/openapi`)
  - `createOrder` uses different param structure than what we implemented
  - Affirmative product query uses `aliexpress.affiliate.product.query` not `dropship.product.search`

## Re-listing (after infrastructure solid)

- [ ] **Re-list products on eBay** (when ready)
  - All 5 listings delisted 1 Jun 2026
  - Use MCP listing tools when infrastructure is verified

## Done

- [x] Fresh Gmail OAuth auth (1 Jun 2026)
- [x] Processed 12 unread emails, labeled and categorized
- [x] Created Gmail labels: RM-eBay-Action, RM-eBay-Routine
- [x] Delist all eBay products (1 Jun 2026)
- [x] **Workflow overhaul — all 12 steps implemented** (2 Jun 2026)
  - [x] WORKFLOWS.md documentation
  - [x] Fix workflow loading in MCP
  - [x] Fix email confirmation (use Resend)
  - [x] Fix scheduler logging
  - [x] Fix web store stock decrement for dropship
  - [x] eBay order sync service + enhance parse_order
  - [x] Wire webhooks → workflow engine
  - [x] AliExpress connector (search, details, order, tracking)
  - [x] DropshipOrder model
  - [x] Dropship workflow YAML
  - [x] Dropship MCP tools (4 tools)
  - [x] Stock building advisory (should_stock)
- [x] **Code audit + fixes** (2 Jun 2026)
  - [x] C1: Add Order.source column
  - [x] C2: Guard OrderItem.product_id NOT NULL
  - [x] C3: Add Order.created_at column
  - [x] H1: Fix unit_price calc (was line total)
  - [x] H2: Fix wrong key in Telegram handlers
  - [x] H6: Fix stock validation for dropship
  - [x] H7: Fix datetime.utcnow() → datetime.now(timezone.utc)
  - [x] M3: Wire workflow triggers with YAML templates
