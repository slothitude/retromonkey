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

- [ ] **M8: Fix eBay order confirmation email template**
  - `send_order_confirmation()` uses `name/qty/price` keys but order_sync stores `sku/quantity/unit_price`
  - Confirmation emails for eBay-synced orders show blank items

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
- [x] **Deploy to Oracle** (2 Jun 2026)
  - [x] All 3 commits pushed + deployed (overhaul, audit, IMAP)
  - [x] DB migrated (added supplier_url, Order.source, Order.created_at, dropship_orders table)
  - [x] Health check passing
- [x] **IMAP email monitor** (2 Jun 2026)
  - [x] `retromonkey/services/imap_monitor.py` — polls Gmail every 5 min
  - [x] Human checkpoints via Telegram inline buttons
  - [x] Gmail app password configured on Oracle
  - [x] Tested: 5 messages processed, 2 alerts, 1 waiting human
- [x] **Set up Gmail App Password** (21 May 2026)
  - [x] App password: `mgvd wwbf cxns jcck` (RetroMonkey Store)
  - [x] Added to Oracle .env as `IMAP_PASSWORD`
