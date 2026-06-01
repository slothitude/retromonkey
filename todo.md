# RetroMonkey TODO

## URGENT — FINISH FIRST SALE (do this first)

- [x] **Fulfill first eBay order — Anbernic RG35XX H (DROP SHIP)**
  - Buyer: Wade Sorensen, 260 Macquarie St, South Windsor NSW 2756
  - Price: AU $94.95 + AU $6.40 shipping = AU $101.35
  - Sold: 31 May 2026 — buyer has paid, waiting on us
  - **Ordered on AliExpress** (1 Jun 2026): ANBERNIC RG35XX H Black 64GB from Coopreme Game Store
  - AliExpress Order: 8211895963242932, Total: AU$86.76 (incl. tax)
  - Estimated delivery: Jun 12, 2026
  - Profit: AU$101.35 revenue - AU$86.76 cost = **AU$14.59** (~14% margin)
  - Stock unit: Also purchased, delivered to Aaron's house (same listing)

- [ ] **Mark order as shipped on eBay**
  - **Deadline: Fri 5 Jun** — upload tracking ASAP once AliExpress provides it
  - Tracking not yet available from Coopreme Game Store

- [ ] **Mark order as shipped on eBay**
  - Once supplier ships, get tracking number and update eBay order
  - This closes the loop with the buyer

- [ ] **Request buyer review**
  - After delivery confirmed, ask Wade for positive feedback

## Critical — Store Setup (after first sale)

- [x] **Delist all eBay products** (1 Jun 2026)
  - Reason: Aaron decision — all 5 listings removed from eBay
  - Note: eBay store still exists, can re-list at any time

- [ ] **Sync eBay order into RetroMonkey DB**
  - Order exists on eBay but NOT in local DB (0 orders)
  - Check: is poll_orders scheduler working? Is eBay API auth valid?
  - Fix order sync so future sales flow automatically

- [ ] **Fix Alibaba sourcing tool**
  - `retromonkey/services/sourcing.py` scraper returns empty (blocked by anti-bot)
  - Need working supplier search to fulfill dropship orders
  - Options: fix scraper, use Alibaba API, or manual sourcing workflow

## High Priority

- [ ] **Add bank details to eBay seller account**
  - Deadline: 28 Jun 2026 or selling account gets restricted
  - Do in eBay Seller Hub > Account > Payments
  - Email ref: #f6609940b1704139a99560b3d59b836a#

## Medium Priority

- [ ] **Fix MX records — switch from ImprovMX to Resend**
  - Current: no MX records at VentraIP (ImprovMX alert says they changed)
  - Add at VentraIP: `MX @ inbound-smtp.us-east-1.amazonaws.com priority 10`
  - Enable "Receiving" on retromonkey.com.au domain in Resend dashboard
  - Cancel ImprovMX once confirmed working

## Low Priority

- [ ] **Verify age on retromonkey.com.au Google account**
  - SafeSearch forced on, personalised ads off, Timeline off
  - Low impact, do when convenient

## Done

- [x] Fresh Gmail OAuth auth (1 Jun 2026)
- [x] Processed 12 unread emails, labeled and categorized
- [x] Created Gmail labels: RM-eBay-Action, RM-eBay-Routine
- [x] Saved email processing log to tomb/services/Retromonkey-Email-Processing.md
