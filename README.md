# courier-tracking-api

> **Demonstration project. Read [LIMITATIONS.md](LIMITATIONS.md) before using it against live sites.**

A JSON API over the public tracking page of the Indian courier **Trackon**, which offers no
public API. It also includes an MCP tool that tells a merchant what a delivery status means for
COD and refunds. The adapter design lets more couriers be added later, ideally through official
APIs.

- `GET /track/{courier}/{tracking_id}` returns `status` (`delivered`, `in_transit`, `returned`, `failed` or `unknown`), `events`, `last_updated`, and `payment_mode`. The only supported courier is `trackon`; any other name gives a typed `UNSUPPORTED_COURIER` error.
- The MCP tool `get_delivery_status(courier, tracking_id)` returns the same data plus a **refund hint**. The hint is a suggestion only; the tool never refunds or cancels anything.
- The drift check warns when the courier page changes layout.

Why only Trackon: other couriers were dropped for compliance reasons. Their terms forbid
automated access, their endpoints only answer their own website, or they use CAPTCHAs.
Trackon's terms have no explicit ban, but they make automated access a gray area, so this is a
demonstration, not a production scraper. [LIMITATIONS.md](LIMITATIONS.md) names each courier and
the reason.

## Status

**Trackon is experimental: the parser was written against a layout not seen live.** No real
tracking ID was available. The page shell and the unknown-AWB answer were seen live; the result
block for a real shipment was not.

If a real response does not match what the parser expects, the API answers
**502 `LAYOUT_CHANGED`**. It never guesses a status: when the newest event uses wording it does not
know, it answers `unknown`. To check with a real ID, see
[How to verify with a real ID](#how-to-verify-with-a-real-id). Once a real result is available, the
parser will be fixed if needed and the synthetic fixtures replaced with real ones.

### Which test fixtures are real

Most fixtures are **synthetic** (hand-built). Every file says which it is in its name (`.live.` or
`.synthetic.`), and synthetic HTML files also start with a `SYNTHETIC FIXTURE` comment.

| Real (live capture, redacted) | Synthetic (hand-built) |
|---|---|
| `trackon/invalid.live.html`: the unknown-AWB page | `delivered`, `in_transit`, `rto`, `rto_prepaid`, `failed` `.synthetic.html`: the real page shell plus an **invented** result block |

Details: [tests/fixtures/README.md](tests/fixtures/README.md).

## Responsible use

- **At most one request per second** to the courier, with timeouts and polite retries that honour `Retry-After`.
- **A cache:** a successful lookup is reused for 5 minutes instead of asking the courier again.
- **An honest User-Agent** that names this project and a contact URL. The project never pretends to be a browser or the courier's own site.
- **No personal data stored.** Nothing is written to disk; results live only in the 5-minute in-memory cache. Proof-of-delivery, signature and NDR images are never fetched. The one exception is `drift --live --save`, which writes pages to `.drift/` (gitignored). It strips tokens and IPs automatically, but names, phone numbers and addresses must be redacted by hand before any page becomes a fixture. A test fails if a fixture ever holds a token, IP, unknown email or mobile number.
- **Tests and the demo run offline.** In tests, any live network call fails the test; CI never calls the courier.
- **Live calls only by hand:** when you run the API yourself, or `drift --live`.

## Setup

Python 3.11 or newer (CI runs 3.12; also tested on 3.14).

```bash
git clone https://github.com/MohammedZaid-AI/courier-tracking-api.git && cd courier-tracking-api
python3.12 -m venv .venv            # Windows: py -3.12 -m venv .venv
source .venv/bin/activate           # Windows PowerShell: .venv\Scripts\Activate.ps1   Git Bash: source .venv/Scripts/activate
pip install -e ".[dev]"
```

If `pip install` fails with `Connection broken: InvalidChunkLength`, an antivirus web shield
(Avast, for example) is corrupting downloads from PyPI. Pause the shield for the install, or
download the `mcp` wheel from https://pypi.org/project/mcp/#files, run `pip install <that .whl file>`,
then run `pip install -e ".[dev]"` again.

### Contact URL in the User-Agent

Every request says who is calling, so a courier's ops team can reach you:
`courier-tracking-api/0.1.0 (+<contact URL>; public tracking pages only)`.
It works with no setup: the default is `DEFAULT_CONTACT` in `courier_tracking/http.py`.
To point it at your own repo, set `COURIER_TRACKING_CONTACT`:

```bash
export COURIER_TRACKING_CONTACT="https://github.com/<you>/<repo>"     # replace with your repo URL
```
```powershell
$env:COURIER_TRACKING_CONTACT = "https://github.com/<you>/<repo>"     # replace with your repo URL (this session only)
setx COURIER_TRACKING_CONTACT "https://github.com/<you>/<repo>"       # replace with your repo URL (permanent; open a new terminal)
```

## Run the tests (offline)

```bash
pytest                              # all tests; any live network call fails the test
python scripts/run_all_cases.py     # pass/fail table: delivered, in transit, RTO, invalid ID, site down
python scripts/prepush.py           # all of the above plus a hand-done checklist before pushing
python -m courier_tracking.drift    # drift check against the saved fixtures
```

GitHub Actions runs `pytest`, the all-cases script and the offline drift check on every push.
None of these commands calls a courier site.

## Run the demo (offline)

```bash
python scripts/demo.py            # about 2 minutes on screen
python scripts/demo.py --pause    # waits for Enter between sections, for screen recording
```

It shows five things in order:
1. the API's JSON for a delivered parcel;
2. a returned COD parcel, with its refund hint;
3. a failed attempt, with the "wait, do not cancel" hint;
4. a typed error;
5. the MCP tool answering "this parcel came back, should I refund?" for a prepaid return.

## Run against live sites

These call the live Trackon site. Read [LIMITATIONS.md](LIMITATIONS.md) first, and use tracking IDs you are allowed to look up.

```bash
uvicorn courier_tracking.api:app                      # then open http://127.0.0.1:8000/docs
curl http://127.0.0.1:8000/track/trackon/<AWB>

python -m courier_tracking.mcp_server                 # MCP server over stdio

python -m courier_tracking.drift --live               # check the live page against the baseline
python -m courier_tracking.drift --live --id trackon=<AWB> --save   # also parse a real ID, save redacted responses to .drift/
```

To use the MCP tool from an MCP client (for example Claude Desktop), add the following. Use the
full path to the venv's Python: `<repo>/.venv/bin/python` on macOS and Linux, or
`<repo>\\.venv\\Scripts\\python.exe` on Windows (backslashes doubled in JSON).

```json
{
  "mcpServers": {
    "courier-tracking": {
      "command": "/full/path/to/<repo>/.venv/bin/python",
      "args": ["-m", "courier_tracking.mcp_server"]
    }
  }
}
```

## How to verify with a real ID

This calls the live Trackon site: one request per second at most, with an honest User-Agent. Use a
tracking ID you are allowed to look up, such as one of your own shipments. Trackon keeps only 75
days of history.

```bash
python -m courier_tracking.drift --live --id trackon=<AWB> --save
```

Expected output when everything matches:

```
Drift check (LIVE: calling courier sites)
[OK         ] trackon  unknown-ID answer (100000000000)
[OK         ] trackon  real ID <AWB>
              parsed: status=in_transit, 4 events
saved .drift/trackon/<timestamp>-unknown-id-answer-100000000000.html
saved .drift/trackon/<timestamp>-real-id-<awb>.html
Redact names, phone numbers and addresses before copying any saved file into tests/fixtures/.
Result: no drift
```

What a reviewer should expect, and do:

| Line for the real ID | Meaning | What to do |
|---|---|---|
| `[OK] ... parsed: status=..., N events` | The parser read it | Open Trackon's own tracking page for the same AWB. Status and newest event must match. If they do, that case is verified. |
| `[DRIFT] ... API returns LAYOUT_CHANGED` | The real result does not match the parser. This is likely, since the result layout was never seen. | The safety net worked: the API refuses to answer for this AWB instead of guessing. The saved file in `.drift/` is what the parser needs to be fixed against. |
| `[WARN] ... came back NOT_FOUND` | The page shows no result | Check the AWB on Trackon's website. If the website does show a result, treat it like DRIFT. |
| `[WARN] ... newest status not recognised` | Parsed, but the latest wording is new to us | The API answers `unknown` for it. Add the wording to `courier_tracking/status_map.py`. |
| `[UNREACHABLE]` | The site is down, slow or blocking us | Try again later. |

Exit code: 0 means no drift, 1 means drift, 2 means the site was unreachable.

You can also ask the running API: `curl http://127.0.0.1:8000/track/trackon/<AWB>` returns 200 with
a status, or 502 `LAYOUT_CHANGED`. It never returns a guessed status.

Before turning a saved file into a fixture, redact names, phone numbers and addresses in
`.drift/trackon/...`. Then save it as `tests/fixtures/trackon/<case>.live.html` and delete the
synthetic one.

## Errors

| HTTP | `error` | Meaning |
|---|---|---|
| 404 | `NOT_FOUND` | The courier has no such shipment, or it is older than the courier keeps |
| 404 | `UNSUPPORTED_COURIER` | Only `trackon` is supported |
| 422 | `INVALID_TRACKING_ID` | Wrong format; rejected before any request is sent |
| 502 | `LAYOUT_CHANGED` | The response does not match what the parser expects (page changed, or a real layout never seen before). No status is guessed. Run the drift check. |
| 503 | `COURIER_UNAVAILABLE` | The site is down, timed out or rate limited us, after retries |

## Layout

```
courier_tracking/
  schema.py          unified JSON models
  http.py            polite client: User-Agent, timeouts, retries, rate limit
  adapters/          base.py (interface for adding couriers), trackon.py
  status_map.py      courier wording -> five statuses
  service.py         courier registry and cache
  api.py             FastAPI app
  drift.py           drift check CLI
  refund_hint.py     COD / refund suggestion rules
  mcp_server.py      MCP tool get_delivery_status
scripts/             run_all_cases.py, demo.py, prepush.py
tests/fixtures/      saved pages and responses (live and synthetic)
```
