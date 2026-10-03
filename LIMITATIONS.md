# Limitations

## Summary

- **What it does:** it reads Trackon's public tracking page and returns one clean JSON answer: delivered, in transit, returned, failed or unknown, with the events. An MCP tool adds a refund hint for COD and returned orders. The hint is only a suggestion; the tool never refunds or cancels anything.
- **Only one courier:** Ekart's terms forbid automated access, Delhivery would need us to pretend to be its website, and others use CAPTCHAs. So we left them out.
- **Not production ready:** Trackon's terms do not ban automated access, but they do not allow it either. This is a demonstration.
- **Never tested on a real shipment:** no real tracking ID was available, so the parser was written against a page layout we could not see. If the real page does not match, the API says `LAYOUT_CHANGED` instead of guessing.
- **It can break at any time:** the courier can change its page, block us, or change its terms. A drift check warns when the page changes.
- **Polite by design:** at most one request per second, a cache, an honest User-Agent, and no personal data stored.
- **The long-term fix:** official courier API agreements, or an aggregator contract, behind the same JSON shape and refund hint.

The detailed sections follow.

---

**This is a demonstration project, not a production scraper.** It reads one courier's public
tracking page (Trackon), which was built for people, not programs. It is tested offline, and it
will break someday. This file explains why, what already limits it, and what the real fix is.

Courier adapters were dropped for compliance reasons (sections 8 and 9). The long-term fix is
official courier API agreements.

## 1. Why scraping is fragile

Every adapter depends on things the courier never promised to keep stable. All of these came
up while building this project:

| What can change | Seen here |
|---|---|
| **Page markup** | Trackon's result block is plain HTML. A redesign or a renamed column breaks parsing. |
| **Hidden endpoints and session flows** | Other couriers' pages call internal JSON endpoints that need tokens issued by the page. Any frontend release can change them. |
| **Access controls** | Delhivery's endpoint only answers requests that claim to come from its own website (section 9). India Post, DTDC, Blue Dart and Xpressbees put a CAPTCHA on tracking. Any courier can add one tomorrow. |
| **Bot protection and rate limits** | Courier firewalls can start blocking a server's IP without notice. We back off on 429/5xx, but we cannot negotiate a higher limit. |
| **Status wording** | Couriers write free text ("Undelivered - Consignee refused", "RTO In Transit"). We map it to five statuses with keyword rules, and new wording can land in `unknown`. |
| **History retention** | Trackon keeps status for 75 days only, so older AWBs come back as `NOT_FOUND`. |
| **Terms of use** | Terms can forbid automated access, and they can change at any time. Ekart's terms do forbid it (section 8). |

### What this project does about it

- **Typed failures instead of wrong answers.** A response that does not match the parser gives `LAYOUT_CHANGED` (HTTP 502), never a guessed status (section 2).
- **Drift check.** `python -m courier_tracking.drift --live`, run by hand, compares the live page with the saved baseline. It reports DRIFT when required markers are missing, and WARN when the structure moves.
- **Responsible use.** The rules are in the README's "Responsible use" section: at most 1 request per second, a cache, an honest User-Agent, no personal data stored, and live calls only by hand.

These measures make breakage visible and fast to fix. They do not make it go away.

## 2. Known gaps in this version

**Trackon is experimental: the parser was written against a layout not seen live.** No real
tracking ID was available. The page shell and the unknown-AWB answer were seen live; a real
result block was not. The parser finds the result by its id and the history columns by header
text. That is a guess made tolerant, not a verified layout.

**What happens when a real response does not match.** The API answers 502 `LAYOUT_CHANGED`;
it does not guess. Every parse is checked before a status is returned. These all raise
`LAYOUT_CHANGED`:
- a page that mentions the AWB but has no result block;
- history rows that cannot be read;
- dates that are unreadable, out of order, or in the future;
- no recognisable status in any event;
- a "current status" that contradicts the newest event;
- any unexpected parser error.

When only the newest event uses new wording, the answer is `unknown`, never an older event's
status. The MCP tool gives no refund hint in either case; it says to check manually.
`tests/test_layout_safety.py` covers each of these.

To verify with a real ID, follow the README section "How to verify with a real ID". Once a real
result is available, the parser will be fixed if needed and the synthetic fixtures replaced with
real ones.

Other gaps:
- **Most fixtures are synthetic.** Only the unknown-AWB page was captured live; see `tests/fixtures/README.md`.
- **The five statuses lose detail.** "Lost", "cancelled" and "damaged" map to `unknown`, and "RTO in transit" and "RTO delivered" both map to `returned`. The courier's own text is always kept in `raw_status`.
- **Polling, not push.** There are no webhooks. Callers have to ask again, and the 5-minute cache limits how fresh an answer can be.
- **Single process.** The cache and rate limiter live in memory. Several API replicas would each make their own requests.

## 3. The refund hint is a suggestion, never an action

`get_delivery_status` returns a `refund_hint`. It is advice for the merchant, nothing more:

- The tool **never refunds, cancels or changes an order**. It has no code path to do so, and it is declared read-only and non-destructive to MCP clients.
- Every hint carries `is_suggestion: true` and a disclaimer.
- **Only `returned` gets a refund hint.** COD means no money was collected, so normally there is no refund. Prepaid means consider a refund under your policy. An unknown payment mode means check your own order system.
- **`failed` always says: wait for the next delivery attempt, do not cancel yet.** One failed attempt is normal; couriers usually retry.
- **Every merchant has its own refund policy.** Some refund when the return is booked, some after the parcel arrives back, some after inspection. Some take partial COD advances or charge return shipping. The hint cannot know any of this.
- The hint is only as good as the tracking data. If the courier page is wrong, late, or misread, the hint is wrong too.

Do not show a customer "your refund has been issued" based on this hint.

## 4. Trackon terms of use (read by the author on 2026-10-02)

In simple words:

- **No explicit ban.** No clause mentions scraping, crawling, robots or automated access.
- **Tracking is not limited to the recipient.** No clause says only the recipient may track a shipment.
- **Rule 3 is broad.** You must not use any service or information "in a manner not expressly permitted" by Trackon. Automated access is not expressly permitted, so it is a **gray area**.
- **Rule 7: do not hurt the website's performance.** We send at most 1 request per second, cache results, and never run live calls in tests or CI.
- robots.txt allows everything (`Disallow:` is empty).

**So this is a demonstration, not a production scraper.** Before any real use, get permission.
The long-term fix is an **official Trackon API agreement, or the tracking API that comes with a
Trackon merchant account**.

## 5. Compliance check of other couriers (2026-10-02)

| Courier | robots.txt | Tracking requires | Terms of use | Included |
|---|---|---|---|---|
| Trackon | `Disallow:` (empty, allows all) | Nothing (plain HTML) | Read by the author; see section 4 | Yes, as a demonstration |
| Ekart | No robots.txt | A token issued by its tracking page | Read by the author: forbids automated access and limits tracking to the recipient | No (section 8) |
| Delhivery | `Disallow:` (empty, allows all) | A request claiming to come from delhivery.com | Not read: the page renders with JavaScript only | No (section 9) |
| India Post, DTDC, Blue Dart, Xpressbees | Allowed or no robots.txt | CAPTCHA | Not checked | No: we do not bypass CAPTCHAs |
| Shadowfax | — | An auth token from its JS bundle; OTP for full details | Not checked | No |
| Professional Couriers | `Disallow: /tracking`, `/api` | — | — | No |

Only public tracking pages are used. There is no login and no CAPTCHA bypass. Proof-of-delivery,
signature and NDR images are never fetched, and saved fixtures are redacted.

## 6. The long-term fix

Scraping is a stopgap. The durable options are, in order of preference:

1. **Official courier API agreements.** Couriers usually give business shippers an account-based tracking API; Delhivery documents one publicly, and Trackon should be asked directly. A contract brings permission, a stable interface, real payment-mode and RTO fields, webhooks instead of polling, and rate limits you can negotiate.
2. **An aggregator contract.** One integration covers many couriers, and the aggregator holds the courier agreements (see section 7).
3. **Keep this project's interface and swap its insides.** Adapters sit behind one interface (`CourierAdapter`) and one schema (`TrackingResult`). The scraper can be replaced by an official API client, and more couriers added, without changing the REST API or the MCP tool.

## 7. Existing alternatives, and why a merchant might still want this

**Alternatives that already exist:**

- **Tracking aggregators** such as Tracktry, [Shipway](https://www.shipway.com/), [Ship24](https://www.ship24.com/tracking-api/bluedart), AfterShip and TrackingMore. They offer multi-carrier tracking APIs under contract. Shipway is India-focused, advertises 100+ courier tracking integrations, and adds branded tracking pages and SMS, email and WhatsApp notifications. Ship24 lists 1,500+ couriers and has a free tier. These cover far more couriers than this project, with contracts, support and webhooks. (Tracktry's site was unreachable when checked, so it is listed without details.)
- **Shipping platforms** that merchants already use (for example Shiprocket or Shipway) include tracking for shipments booked through them.
- **Open-source courier trackers** on GitHub: usually one scraper per courier, with the same fragility and terms-of-use questions described above.

**Honestly, this project should not compete on courier coverage.** An aggregator wins there.

**Why a Razorpay merchant could still want it: the COD and refund decision layer.**
Aggregators answer "where is my parcel?". A merchant's harder question is "what should I do
about the money?":

- Is this a returned COD order, where nothing was collected and nothing should be refunded?
- Is it a returned prepaid order that needs a refund under my policy?
- Is it a failed attempt, where I should wait and not cancel yet?

That decision sits next to the payment, not the parcel. It can be exposed as an agent tool
(MCP), so a support or ops agent can answer it in one step. The adapter in this repo is the
replaceable part. The schema, the status mapping and the refund hint are the part worth keeping,
and they can run on top of an aggregator or an official courier API instead of scraping.

## 8. Why Ekart is not included

Ekart's terms of use forbid automated access to the website: clause 1.2 prohibits any "page
scrape", "robot", "spider" or other automatic device or program. Clause 12 limits tracking updates
to shipments where the user is the recipient. So we did not build it. An earlier draft did, and it
was removed after the author read the terms.

The long-term fix is an official Ekart API agreement.

## 9. Why Delhivery is not included

Delhivery's public tracking endpoint rejects any request that does not claim to come from
Delhivery's own website. Without the header naming `www.delhivery.com` as the requesting page,
it answers `401 "ERROR: Invalid Origin"`.

Working around that would mean pretending to be Delhivery's page. That looks like bypassing an
access control, so we chose not to.

The long-term fix is an official Delhivery API agreement, or the tracking API that comes with a
Delhivery merchant account.
