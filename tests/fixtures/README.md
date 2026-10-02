# Test fixtures

Tests run fully offline against these files. The filename says where each one came from.

| Suffix | Meaning |
|---|---|
| `*.live.*` | Captured from the real public site, then redacted (no IPs, tokens or personal data). |
| `*.synthetic.*` | **Hand-built.** No real tracking IDs were available. Synthetic HTML files start with a `SYNTHETIC FIXTURE` comment. |

All synthetic IDs are obviously fake (`9990000000xx`).

## Trackon (captured 2026-10-02)

| File | Source | Notes |
|---|---|---|
| `trackon/invalid.live.html` | live | Real page for an unknown AWB: the page shell, no result block. Form anti-forgery token replaced with `REDACTED-FORM-TOKEN`. |
| `trackon/delivered.synthetic.html` | synthetic | Live page shell plus an **invented** `#divtrackStatus` result block. The file starts with a `SYNTHETIC FIXTURE` comment, and the block itself is marked too. Prepaid. |
| `trackon/in_transit.synthetic.html` | synthetic | Same; COD. |
| `trackon/rto.synthetic.html` | synthetic | Same; COD, "RTO DELIVERED". |
| `trackon/rto_prepaid.synthetic.html` | synthetic | Same as `rto`, but prepaid. |
| `trackon/failed.synthetic.html` | synthetic | Same; COD, failed attempt. |

Trackon's real result markup has not been seen, because no real AWB was available. Only the
result block is invented; everything around it is the real page.

## Replacing synthetic fixtures with real ones

When a real tracking ID is available, run
`python -m courier_tracking.drift --live --id trackon=<AWB> --save`. It writes redacted live
responses to `.drift/`, which is gitignored. Redact names, phone numbers and addresses, then copy
the file here as `<case>.live.html` and delete the synthetic one.
