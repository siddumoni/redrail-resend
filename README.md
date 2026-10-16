# RedRail — Bus & Train Availability Alerts

RedRail is a Python-based availability watcher for **RedBus buses and trains**. It checks configured routes and travel dates, tracks availability between runs, and sends an HTML email through **Resend** when a watched option becomes newly available.

The project runs in GitHub Actions and stores its previous availability snapshot in `state.json`, which the workflow commits back to the repository so later runs can detect changes.

## Features

- **Bus availability:** operator, bus type, departure/arrival time, journey duration, seat counts, and fare.
- **Train availability:** train name/number, departure and arrival times, duration, per-class availability, quota, and fare when supplied by RedBus.
- **Configurable watches:** monitor one or more routes, dates, bus operators, train classes, or a specific train.
- **Change detection:** sends an alert when a watched option becomes newly available; unchanged availability does not repeatedly trigger a digest.
- **Combined HTML digest:** multiple classes for the same train are shown in one train card, with one class per line. Each line displays class, status, and fare.
- **Status-aware styling:** distinct colours for Available, RAC, waiting list, quota-related and unavailable statuses.
- **Responsive email layout:** designed for desktop and mobile email clients.
- **Failure alerts:** sends an email after repeated consecutive fetch failures for a watch.
- **Automated tests:** unit tests cover configuration, state transitions, scraping/parsing, email rendering, and orchestration.

RedRail reads availability from RedBus website endpoints through a Playwright browser session. These are website implementation details, not a public API contract; RedBus may change them, so live runs can occasionally need maintenance.

## How a run works

1. Load and validate the `REDBUS_WATCHES` configuration.
2. Load the previous snapshot from `state.json`.
3. Fetch current bus/train availability for each configured watch.
4. Compare current results with the saved snapshot.
5. If an item is newly available, send one combined Resend email containing the current results for the affected watch(es), with a `NEW` badge on newly available items.
6. Track fetch failures and send a failure alert after the configured threshold.
7. Save the updated snapshot to `state.json`.

**No change usually means no availability digest email.** A successful GitHub Actions run does not necessarily send an email: the watcher only sends a digest when it detects newly available results. Repeated-fetch-failure alerts are a separate case.

## Repository layout

```text
.
├── .github/
│   └── workflows/
│       ├── redbus-watch.yml   # Manual availability watcher
│       └── tests.yml          # Unit tests on pushes, PRs and manual dispatch
├── redbus_watch/
│   ├── config.py              # REDBUS_WATCHES parsing and validation
│   ├── scraper_bus.py         # Bus search and normalization
│   ├── scraper_train.py       # Train search and normalization
│   ├── state.py               # Snapshot persistence and availability diffing
│   ├── email_template.py      # Responsive HTML digest and failure alert
│   ├── notifier.py            # Resend email delivery
│   └── main.py                # Watcher orchestration
├── tests/                     # Unit and regression tests
├── state.json                 # Last-known availability (updated by workflow)
├── requirements.txt
└── README.md
```

## GitHub Actions setup

In the repository, open **Settings → Secrets and variables → Actions** and configure:

### Repository variable

- `REDBUS_WATCHES` — a JSON array describing the routes and dates to monitor. This is a **variable**, not a secret.

### Repository secrets

- `RESEND_API_KEY` — your Resend API key.
- `RESEND_FROM` — verified sender address configured in Resend.
- `RESEND_TO` — destination email address for alerts.

The watcher workflow is currently **manual-only**. To run it:

1. Open the repository's **Actions** tab.
2. Select **RedRail Train Availability Watcher**.
3. Click **Run workflow** and choose the branch (normally `main`).
4. Start the run and inspect its logs for the run summary or errors.

The workflow uses Python 3.12, installs dependencies, launches Chromium using Playwright (with a virtual display for headed mode), runs the watcher, and commits changes to `state.json`.

The separate **Python tests** workflow runs `pytest` on pushes, pull requests targeting `main`, and manual dispatch. The watcher itself does **not** currently have a scheduled cron trigger. If you want periodic polling, add a `schedule:` trigger to `.github/workflows/redbus-watch.yml` deliberately and choose a conservative interval.

## Configure watches

Set `REDBUS_WATCHES` to valid JSON. Each entry is one bus or train watch. Use `date` for one travel date or `dates` for multiple dates; do not use both in the same entry. Dates use `YYYY-MM-DD`.

### Bus example

```json
[
  {
    "type": "bus",
    "source": "Chennai",
    "destination": "Coimbatore",
    "dates": ["2026-12-10", "2026-12-11"],
    "label": "Chennai to Coimbatore",
    "seat_type": "any",
    "operators": ["SRS", "KPN"]
  }
]
```

Bus fields:

- `type`: must be `"bus"`.
- `source`, `destination`: city names understood by RedBus.
- `date` or `dates`: one date or a list of dates.
- `label` (optional): human-readable route label for the email.
- `seat_type` (optional): `"any"`, `"seater"`, `"sleeper"`, `"ac"`, or `"non_ac"`. Defaults to `"any"`.
- `operators` (optional): list of operator-name substrings, matched case-insensitively. Omit it to watch all matching operators.

### Train example

```json
[
  {
    "type": "train",
    "source": "MAS",
    "destination": "CBE",
    "date": "2026-12-13",
    "label": "Chennai to Coimbatore",
    "classes": ["SL", "3A", "2A"],
    "train_number": "12671"
  }
]
```

Train fields:

- `type`: must be `"train"`.
- `source`, `destination`: station names or station codes that RedBus can resolve.
- `date` or `dates`: one date or a list of dates.
- `label` (optional): human-readable route label.
- `classes` (optional): list of class codes such as `"SL"`, `"3A"`, `"2A"`, or `"1A"`. If omitted, all classes returned by the search are considered.
- `train_number` (optional): only watch a particular train number.
- `train_name` (optional): filter by a train-name substring.

When a watch uses `dates`, the configuration expands it into separately tracked watches, one for each date. Avoid duplicate entries that describe the same route, date, and filters.

## Local development

Requirements: Python 3.12 recommended, plus Playwright's Chromium browser for live scraping.

```bash
python -m venv .venv
```

Activate the environment:

**Windows PowerShell**
```powershell
.venv\\Scripts\\Activate.ps1
```

**Linux/macOS**
```bash
source .venv/bin/activate
```

Install dependencies:

```bash
python -m pip install -r requirements.txt
python -m playwright install chromium
```

Set `REDBUS_WATCHES`, `RESEND_API_KEY`, `RESEND_FROM`, and `RESEND_TO` in your local environment, then run:

```bash
python -m redbus_watch.main
```

For a local test, use a test email destination and a watch that you intend to query. Do not commit API keys or other secrets to Git.

## Run the tests

```bash
python -m pip install -r requirements.txt
python -m pytest tests/ -v
```

Unit tests use fixtures and fake fetchers where appropriate, so most tests do not require a live RedBus request or a real email send. A passing test suite does not guarantee that RedBus's live website endpoints have not changed.

## Troubleshooting

- **Workflow succeeded but no email arrived:** this can be normal if no watched option became newly available. Check the `Run summary` in the Actions logs.
- **Repeated fetch failures:** check the run logs and whether RedBus has changed its response schema or is temporarily unreachable. A failure alert is sent after the configured threshold (`REDBUS_FAIL_THRESHOLD`, default `3`).
- **Email delivery failure:** verify the Resend API key, sender verification, and recipient configuration. Inspect the Actions logs.
- **State-related behaviour:** `state.json` records the last-known results. Since alerting is based on changes, clearing or replacing it changes what the next run considers new. Back it up before making manual edits.
- **Train/bus results look different from the website:** availability and fares can change quickly; the watcher reports what the source returned during that run and does not reserve or purchase tickets.

## Important notes

- RedRail is an availability notification tool, **not a booking service**. It does not reserve seats or purchase tickets.
- RedBus endpoints used by the scrapers are undocumented and may change without notice.
- Keep polling conservative and respectful of the website. Automatic scheduled polling is not enabled in the current watcher workflow.
- Protect Resend credentials and never store secrets in `REDBUS_WATCHES`, source code, test fixtures, or committed logs.
