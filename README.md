# RedRail — Train Availability Alerts

RedRail is a Python-based **train availability watcher** for train searches on RedBus. It monitors configured routes, travel dates, trains and travel classes, tracks availability changes between runs, and sends HTML email alerts through **Resend** when a watched class becomes newly available.

RedRail is for train availability only. Bus monitoring is not part of this project's purpose. The repository currently uses the existing `REDBUS_WATCHES` GitHub Actions variable name for configuration; that variable should contain **train watches only**.

The watcher runs in GitHub Actions and persists its last-known availability snapshot in `state.json`. This lets later runs compare current results with previous results instead of repeatedly sending the same availability alert.

## Features

- **Train availability:** train name and number, departure time, arrival time, journey duration, class-level availability, quota and fare when supplied by the source.
- **Flexible train watches:** monitor one or more routes and dates, select classes such as SL, 3A, 2A and 1A, and optionally filter by train number or name.
- **Grouped email cards:** one row/card per train instance, with each watched class displayed on its own line.
- **Clear availability styling:** distinct colours for Available, RAC, waiting list, quota-related and unavailable statuses.
- **Class-specific fares:** show the fare returned for each class when available.
- **Responsive email layout:** designed to adapt to desktop and mobile email clients.
- **Change detection:** send an availability digest when a watched class becomes newly available rather than sending the same alert on every successful run.
- **Failure alerts:** send a separate email after repeated consecutive fetch failures for a watch.
- **Automated tests:** unit tests cover configuration, state transitions, train scraping/parsing, email rendering and watcher orchestration.

The scraper uses RedBus website endpoints through a Playwright browser session. These endpoints are implementation details, not a public API contract, and can change without notice.

## How a run works

1. Load and validate the train-watch configuration from `REDBUS_WATCHES`.
2. Load the previous availability snapshot from `state.json`.
3. Fetch train availability for each configured route, date and class filter.
4. Compare the current results with the saved snapshot.
5. If a watched class becomes newly available, send a combined Resend email for the affected watch, with a `NEW` badge where appropriate.
6. Track consecutive fetch failures and send a separate failure alert when the configured threshold is reached.
7. Save the updated snapshot to `state.json`.

**A successful run does not necessarily send an availability email.** If no watched class becomes newly available, the digest may not be sent. Repeated-fetch-failure alerts are handled separately.

## Repository layout

```text
.
├── .github/
│   └── workflows/
│       ├── redbus-watch.yml   # Train availability watcher (legacy filename)
│       └── tests.yml          # Unit tests on pushes, PRs and manual dispatch
├── redrail_watch/             # Train watcher package, if present in this checkout
├── redbus_watch/
│   ├── config.py              # Watch configuration parsing and validation
│   ├── scraper_train.py       # Train search and availability normalization
│   ├── state.py               # Snapshot persistence and availability diffing
│   ├── email_template.py      # Responsive train digest and failure alert
│   ├── notifier.py            # Resend email delivery
│   └── main.py                # Watcher orchestration
├── tests/                     # Unit and regression tests
├── state.json                 # Last-known availability (updated by workflow)
├── requirements.txt
└── README.md
```

The workflow and package paths retain some historical `redbus` naming. That naming does not mean this repository is intended to monitor buses.

## GitHub Actions setup

In the repository, open **Settings → Secrets and variables → Actions** and configure the following.

### Repository variable

- `REDBUS_WATCHES` — a JSON array containing **train watch entries only**. The variable name is retained for compatibility with the existing code; do not put bus watches in it.

### Repository secrets

- `RESEND_API_KEY` — your Resend API key.
- `RESEND_FROM` — a verified sender address configured in Resend.
- `RESEND_TO` — the recipient email address for alerts.

### Run the watcher

The watcher workflow is currently **manual-only**:

1. Open the repository's **Actions** tab.
2. Select **RedRail Train Availability Watcher**.
3. Click **Run workflow** and choose the branch (normally `main`).
4. Start the run and inspect its logs for the run summary or errors.

The workflow uses Python and Playwright to run the train watcher, then commits changes to `state.json`. The separate **Python tests** workflow runs the unit tests on pushes, pull requests targeting `main`, and manual dispatch.

The watcher does **not** currently have a scheduled cron trigger. If periodic polling is desired, add a `schedule:` trigger to the existing watcher workflow deliberately and choose a conservative interval.

## Configure train watches

Set `REDBUS_WATCHES` to valid JSON. Each entry represents a train watch. Use `date` for one travel date or `dates` for multiple travel dates; do not use both in the same entry. Dates use `YYYY-MM-DD`.

### Example

```json
[
  {
    "type": "train",
    "source": "MAS",
    "destination": "CBE",
    "dates": ["2026-12-10", "2026-12-13"],
    "label": "Chennai to Coimbatore",
    "classes": ["SL", "3A", "2A"],
    "train_number": "12671"
  }
]
```

### Supported fields

- `type`: use `"train"`.
- `source`, `destination`: station names or station codes that the scraper can resolve.
- `date` or `dates`: one travel date or a list of dates.
- `label` (optional): human-readable route label used in the email.
- `classes` (optional): class codes such as `"SL"`, `"3A"`, `"2A"` or `"1A"`. If omitted, the watcher considers the classes returned by the search.
- `train_number` (optional): watch a particular train number.
- `train_name` (optional): filter by a train-name substring.

When a watch uses `dates`, configuration expands it into separately tracked watches, one per date. Avoid duplicate entries that describe the same route, date and filters.

## Local development

Requirements: Python 3.12 is recommended, along with Playwright's Chromium browser for live scraping.

Create and activate a virtual environment:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

On Linux/macOS:

```bash
python -m venv .venv
source .venv/bin/activate
```

Install dependencies and Chromium:

```bash
python -m pip install -r requirements.txt
python -m playwright install chromium
```

Set `REDBUS_WATCHES`, `RESEND_API_KEY`, `RESEND_FROM` and `RESEND_TO` in your local environment, then run:

```bash
python -m redbus_watch.main
```

For local testing, use a recipient address you control. Never commit API keys or other secrets.

## Run the tests

```bash
python -m pip install -r requirements.txt
python -m pytest tests/ -v
```

Unit tests use fixtures and fake fetchers where appropriate, so most tests do not require a live RedBus request or a real email send. A passing test suite cannot guarantee that the live website endpoints have not changed.

## Troubleshooting

- **Workflow succeeded but no availability email arrived:** this can be normal if no watched class became newly available. Check the run summary in the Actions logs.
- **Repeated fetch failures:** check the logs and whether the source is temporarily unreachable or its response structure has changed. A failure alert is sent after the configured threshold (`REDBUS_FAIL_THRESHOLD`, default `3`).
- **Email delivery failure:** verify the Resend API key, sender verification and recipient configuration. Inspect the Actions logs.
- **Unexpected alert behaviour:** `state.json` stores last-known results. Since alerting is based on changes, clearing or replacing it changes what the next run considers new. Back it up before editing it manually.
- **Availability or fares differ from the website:** train availability and fares can change quickly. The email reports what the source returned during that run; it does not reserve or purchase tickets.

## Important notes

- RedRail is a **train availability notification tool**, not a booking service. It does not reserve seats or purchase tickets.
- The scraper uses undocumented website endpoints that may change without notice.
- Keep polling conservative and respectful of the source website. Scheduled polling is not enabled in the current watcher workflow.
- Protect Resend credentials. Never store secrets in `REDBUS_WATCHES`, source code, test fixtures or committed logs.
