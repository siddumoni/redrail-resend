"""RedBus train availability scraper using the observed Rails API schema.

Observed endpoints:
  GET  /rails/api/solarSearch?search=<station>
  POST /rails/api/searchResults

The POST body matches the sanitized browser capture supplied by the user.
Network calls are made in the page context so the request uses the browser's
normal RedBus session/cookies. No session values are read, stored, or logged.
"""
from __future__ import annotations

import re
import socket
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
BROWSER_LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-features=AsyncDns",
]

IN_PAGE_FETCH_SCRIPT = r"""
async ({ url, method, body }) => {
  try {
    const opts = { method: method || 'GET', credentials: 'include' };
    if ((method || 'GET') === 'POST') {
      opts.headers = { 'Content-Type': 'application/json' };
      opts.body = JSON.stringify(body || {});
    }
    const resp = await fetch(url, opts);
    const text = await resp.text();
    let parsed = null;
    let parseError = null;
    try { parsed = JSON.parse(text); } catch (e) { parseError = String(e); }
    return { ok: resp.ok, status: resp.status, parsed, parseError };
  } catch (e) {
    return { ok: false, status: 0, parsed: null, fetchError: String(e) };
  }
}
"""


class ScrapeError(RuntimeError):
    """Raised when availability could not be established reliably."""


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _first(obj: dict, *keys: str) -> Any:
    for key in keys:
        value = obj.get(key)
        if value not in (None, ""):
            return value
    lowered = {str(k).lower(): v for k, v in obj.items()}
    for key in keys:
        value = lowered.get(key.lower())
        if value not in (None, ""):
            return value
    return None


def _unwrap_capture(payload: Any) -> Any:
    if isinstance(payload, dict):
        if isinstance(payload.get("body"), (dict, list)):
            return payload["body"]
        result = payload.get("result")
        if isinstance(result, dict):
            if isinstance(result.get("parsed"), (dict, list)):
                return result["parsed"]
            if isinstance(result.get("body"), (dict, list)):
                return result["body"]
    return payload


def _target_redbus_date(date_str: str) -> str:
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").strftime("%d-%m-%Y")
    except (TypeError, ValueError) as exc:
        raise ScrapeError(f"Invalid travel date {date_str!r}; expected YYYY-MM-DD.") from exc


def _date_for_request(date_str: str) -> str:
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").strftime("%Y%m%d")
    except (TypeError, ValueError) as exc:
        raise ScrapeError(f"Invalid travel date {date_str!r}; expected YYYY-MM-DD.") from exc


def _parse_count(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    match = re.search(r"\d+", str(value).replace(",", ""))
    return int(match.group(0)) if match else None


def _normalized_status(status: Any, count: Optional[int]) -> tuple[str, int]:
    raw = str(status or "").strip()
    upper = raw.upper()
    if upper == "AVAILABLE" or upper.startswith("AVAILABLE "):
        number = count if count is not None else 1
        if number <= 0:
            return "NOT AVAILABLE", 0
        return (f"Available {number}" if count is not None else "Available"), number
    if upper == "RAC" or upper.startswith("RAC "):
        return (f"RAC {count}" if count is not None else "RAC"), 1
    if count is not None and raw:
        return f"{raw} {count}", 0
    return raw or "Unknown", 0


def _iter_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _iter_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_dicts(child)


def _parse_legacy_fixture(payload: Any, classes_filter: Optional[List[str]]) -> Dict[str, dict]:
    """Backward-compatible parser for the older generic test/fixture schema.

    Live fetching always uses the confirmed trainBtwnStnsList schema. This
    fallback keeps callers and historical tests that use explicit `trains`
    arrays working without weakening the live response validation.
    """
    unwrapped = _unwrap_capture(payload)
    if isinstance(unwrapped, dict) and isinstance(unwrapped.get("data"), dict):
        if isinstance(unwrapped["data"].get("trains"), list):
            rows = unwrapped["data"]["trains"]
        else:
            rows = unwrapped.get("trains")
    else:
        rows = unwrapped.get("trains") if isinstance(unwrapped, dict) else None
    if not isinstance(rows, list):
        raise ScrapeError("Response does not contain trainBtwnStnsList. No recognizable train inventory with an explicit availability field was found.")
    if not rows:
        raise ScrapeError("Train response contained an empty trains list; refusing to assume zero availability.")

    wanted = {str(v).strip().upper() for v in classes_filter or []}
    snapshots: Dict[str, dict] = {}
    for item in rows:
        if not isinstance(item, dict):
            continue
        train_no = str(_first(item, "train_no", "trainNo", "trainNumber", "train_number", "number") or "").strip()
        train_name = str(_first(item, "train_name", "trainName", "train_name_en", "name") or "").strip()
        class_code = str(_first(item, "class", "classCode", "class_code", "coachClass", "travelClass") or "UNKNOWN").strip().upper()
        status = _first(item, "status_text", "statusText", "availabilityStatus", "availability_status", "availability", "currentStatus", "current_status", "bookingStatus", "booking_status", "status")
        if isinstance(status, dict):
            status = _first(status, "status", "text", "message", "availability")
        status_text = str(status or "").strip()
        if not (train_no or train_name) or not status_text:
            continue
        if wanted and class_code not in wanted:
            continue
        identity = train_no or _norm(train_name)
        upper = status_text.upper()
        count_match = re.search(r"\b(?:AVAILABLE|AVAILABILITY)\D{0,8}(\d+)\b", upper)
        available = int(count_match.group(1)) if count_match else (1 if upper.startswith(("AVAILABLE", "RAC")) else (int(upper) if upper.isdigit() else 0))
        key = f"{identity}_{class_code}".lower().replace(" ", "_")
        snapshots[key] = {
            "train_name": train_name or f"Train {identity}",
            "train_no": train_no or identity,
            "class": class_code,
            "available": available,
            "status_text": status_text,
            "departure_time": str(_first(item, "departure_time", "departureTime", "departure", "departureTimeText") or ""),
            "arrival_time": str(_first(item, "arrival_time", "arrivalTime", "arrival", "arrivalTimeText") or ""),
        }
    if not snapshots:
        raise ScrapeError("Response does not contain trainBtwnStnsList. No recognizable train inventory with an explicit availability field was found.")
    return snapshots


def parse_train_search_response(
    payload: Any,
    classes_filter: Optional[List[str]] = None,
    travel_date: Optional[str] = None,
) -> Dict[str, dict]:
    """Normalize observed RedBus train JSON to the watcher's snapshot format."""
    payload = _unwrap_capture(payload)
    if not isinstance(payload, dict):
        raise ScrapeError("Train search response is not a JSON object.")
    if "trainBtwnStnsList" not in payload:
        return _parse_legacy_fixture(payload, classes_filter)
    train_rows = payload.get("trainBtwnStnsList")
    if not isinstance(train_rows, list):
        raise ScrapeError("trainBtwnStnsList is not a list.")

    wanted = {str(v).strip().upper() for v in (classes_filter or []) if str(v).strip()}
    target_date = _target_redbus_date(travel_date) if travel_date else None
    snapshots: Dict[str, dict] = {}
    availability_rows_seen = 0
    matching_date_rows_seen = 0

    for train in train_rows:
        if not isinstance(train, dict):
            continue
        train_no = str(_first(train, "trainNumber") or "").strip()
        train_name = str(_first(train, "trainName") or "").strip()
        if not train_no and not train_name:
            continue
        availability_rows = train.get("tbsAvailability")
        if not isinstance(availability_rows, list):
            continue

        for availability in availability_rows:
            if not isinstance(availability, dict):
                continue
            availability_rows_seen += 1
            row_date = str(_first(availability, "availablityDate") or "").strip()
            if target_date and row_date != target_date:
                continue
            matching_date_rows_seen += 1
            class_code = str(_first(availability, "classType", "className") or "").strip().upper()
            if not class_code or (wanted and class_code not in wanted):
                continue
            raw_status = _first(availability, "availablityStatus")
            count = _parse_count(_first(availability, "availablityNumber"))
            status_text, available = _normalized_status(raw_status, count)
            from_code = str(_first(train, "fromStnCode", "srcStationCode") or "").strip().upper()
            to_code = str(_first(train, "toStnCode", "dstStationCode") or "").strip().upper()
            quota = str(_first(availability, "quota") or "GN").strip().upper()
            identity = train_no or _norm(train_name)
            parts = [identity, from_code, to_code, class_code, quota]
            key = "_".join(p.lower().replace(" ", "_") for p in parts if p)
            snapshots[key] = {
                "train_name": train_name or f"Train {identity}",
                "train_no": train_no or identity,
                "class": class_code,
                "available": available,
                "status_text": status_text,
                "departure_time": str(_first(train, "departureTime") or ""),
                "arrival_time": str(_first(train, "arrivalTime") or ""),
                "price": _first(availability, "totalFare"),
                "quota": quota,
                "from_station": from_code,
                "to_station": to_code,
                "duration": str(_first(train, "duration") or ""),
                "availability_date": row_date,
                "last_updated": str(_first(availability, "lastUpdatedOn") or ""),
            }

    if target_date and availability_rows_seen and not matching_date_rows_seen:
        raise ScrapeError(f"Response had availability rows, but none matched {target_date}.")
    if train_rows and availability_rows_seen == 0:
        raise ScrapeError(
            "Train results were present, but no tbsAvailability rows were found; "
            "refusing to treat an incomplete response as no availability."
        )
    return snapshots


def _check_response(response: dict, label: str) -> Any:
    if not isinstance(response, dict) or not response.get("ok"):
        status = response.get("status") if isinstance(response, dict) else "unknown"
        detail = response.get("fetchError") if isinstance(response, dict) else None
        raise ScrapeError(f"{label} request failed (HTTP/status {status})" + (f": {detail}" if detail else ""))
    parsed = response.get("parsed")
    if not isinstance(parsed, (dict, list)):
        raise ScrapeError(f"{label} returned invalid JSON: {response.get('parseError', 'empty response')}")
    return parsed


def _resolve_station_code(response: dict, query: str) -> str:
    parsed = _check_response(response, f"Station lookup for {query!r}")
    docs = ((parsed.get("response") or {}).get("docs") or []) if isinstance(parsed, dict) else []
    if not docs:
        raise ScrapeError(f"No train station matched {query!r}. Try a station name or code.")

    q = _norm(query)
    # Prefer a literal station-code match, then exact station/city/alias name,
    # then the API's highest-ranked suggestion (first row).
    for doc in docs:
        if _norm(doc.get("stationCode")) == q:
            return str(doc["stationCode"]).strip().upper()
    for doc in docs:
        names = [doc.get("stationName"), doc.get("cityName"), doc.get("alias1"), doc.get("alias2"), doc.get("alias3")]
        if any(_norm(name) == q for name in names if name):
            code = doc.get("stationCode")
            if code:
                return str(code).strip().upper()
    code = docs[0].get("stationCode")
    if not code:
        raise ScrapeError(f"Top station suggestion for {query!r} had no stationCode.")
    return str(code).strip().upper()


def _launch_args() -> List[str]:
    args = list(BROWSER_LAUNCH_ARGS)
    if __import__("os").environ.get("REDBUS_DISABLE_HTTP2", "").strip().lower() == "true":
        args.append("--disable-http2")
    try:
        ip = socket.gethostbyname("www.redbus.in")
        args.append(f"--host-resolver-rules=MAP www.redbus.in {ip}")
    except socket.gaierror:
        pass
    return args


def fetch_train_availability(
    source: str,
    destination: str,
    date: str,
    classes_filter: Optional[List[str]] = None,
    train_number: Optional[str] = None,
    train_name: Optional[str] = None,    
) -> Dict[str, dict]:
    """Resolve stations and fetch live train availability through RedBus's UI session."""
    if not source or not destination:
        raise ScrapeError("Both source and destination stations are required.")
    request_date = _date_for_request(date)
    # Validate date formatting now, before making any network requests.
    _target_redbus_date(date)

    import os
    launch_args = _launch_args()
    try:
        with sync_playwright() as p:
            headless = os.environ.get("REDBUS_HEADLESS", "true").strip().lower() != "false"
            browser = p.chromium.launch(headless=headless, args=launch_args)
            try:
                context = browser.new_context(user_agent=USER_AGENT)
                page = context.new_page()
                navigated = False
                try:
                    page.goto("https://www.redbus.in", wait_until="networkidle", timeout=20000)
                    navigated = True
                except PWTimeoutError:
                    pass
                if not navigated:
                    last_error = None
                    for attempt in range(3):
                        try:
                            if attempt:
                                time.sleep(2 * attempt)
                            page.goto("https://www.redbus.in", wait_until="domcontentloaded", timeout=30000)
                            page.wait_for_timeout(2500)
                            last_error = None
                            break
                        except Exception as exc:
                            last_error = exc
                    if last_error is not None:
                        raise ScrapeError(f"Could not load redbus.in: {last_error}") from last_error

                def in_page_fetch(url: str, method: str = "GET", body: Optional[dict] = None) -> dict:
                    return page.evaluate(IN_PAGE_FETCH_SCRIPT, {"url": url, "method": method, "body": body})

                source_url = f"https://www.redbus.in/rails/api/solarSearch?search={quote(source)}"
                dest_url = f"https://www.redbus.in/rails/api/solarSearch?search={quote(destination)}"
                source_code = _resolve_station_code(in_page_fetch(source_url), source)
                dest_code = _resolve_station_code(in_page_fetch(dest_url), destination)

                request_body = {
                    "src": source_code,
                    "dst": dest_code,
                    "doj": request_date,
                    "filter": {},
                    "sort": {},
                    "allowedQuotaList": [],
                    "enableRecaptcha": False,
                    "showConnectingTrains": True,
                }
                response = in_page_fetch("https://www.redbus.in/rails/api/searchResults", "POST", request_body)
                parsed = _check_response(response, "Train search")
                if not isinstance(parsed, dict) or "trainBtwnStnsList" not in parsed:
                    raise ScrapeError("Train search response schema was not recognized; no availability alert will be generated.")
                snapshots = parse_train_search_response(
                    parsed,
                    classes_filter=classes_filter,
                    travel_date=date,
                )

                # Filter by train number and/or train name before state tracking.
                if train_number or train_name:
                    wanted_number = str(train_number or "").strip()
                    wanted_name = _norm(train_name) if train_name else ""
                
                    snapshots = {
                        key: item
                        for key, item in snapshots.items()
                        if (
                            not wanted_number
                            or str(item.get("train_no", "")).strip() == wanted_number
                        )
                        and (
                            not wanted_name
                            or wanted_name in _norm(item.get("train_name", ""))
                        )
                    }
                
                return snapshots
            finally:
                browser.close()
    except ScrapeError:
        raise
    except Exception as exc:
        raise ScrapeError(f"Train availability fetch failed: {type(exc).__name__}: {exc}") from exc
