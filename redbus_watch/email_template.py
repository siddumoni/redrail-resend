"""
Builds the HTML email body, styled consistently with the bms-resend
template: gradient header banner, chip-style availability badges,
chronological grouping, clickable links, IST timestamps.

This module is pure string-building with no external dependencies, so it's
fully unit-testable without touching RedBus or Resend at all.
"""

from datetime import datetime, timezone, timedelta
from html import escape
from typing import List, Dict

IST = timezone(timedelta(hours=5, minutes=30))

# Chip colors: green = plenty available, amber = limited (e.g. RAC or <5 seats), grey = fallback
CHIP_GREEN = "#1b8a4c"
CHIP_GREEN_BG = "#e6f7ed"
CHIP_AMBER = "#b3760a"
CHIP_AMBER_BG = "#fdf1de"
CHIP_GREY = "#5a6472"
CHIP_GREY_BG = "#eef0f2"

# NEW badge - distinct from availability chips, marks items that flipped
# to available since the last check (vs. items that were already known).
NEW_BADGE_COLOR = "#b3261e"
NEW_BADGE_BG = "#fee2e2"


def _now_ist_str() -> str:
    return datetime.now(IST).strftime("%d %b %Y, %I:%M %p IST")


def _new_badge() -> str:
    return (
        f'<span style="display:inline-block;padding:3px 8px;margin:0 6px 0 0;'
        f"border-radius:4px;font-size:11px;font-weight:700;letter-spacing:0.03em;"
        f'color:{NEW_BADGE_COLOR};background:{NEW_BADGE_BG};">'
        f"NEW</span>"
    )


def _rating_badge(rating, reviews) -> str:
    """RedBus-style rating badge: colored box with score + star, review
    count alongside. Returns empty string if rating data isn't available
    (older/partial data), rather than showing a broken "None" badge."""
    if rating is None:
        return ""
    try:
        rating_val = float(rating)
    except (TypeError, ValueError):
        return ""

    if rating_val >= 4.0:
        color = CHIP_GREEN
    elif rating_val >= 3.0:
        color = CHIP_AMBER
    else:
        color = CHIP_GREY

    reviews_html = f'<span style="font-size:11px;color:#8a94a3;margin-left:4px;">({reviews})</span>' if reviews else ""
    return (
        f'<span style="display:inline-block;padding:2px 7px;border-radius:4px;'
        f'font-size:12px;font-weight:700;color:#fff;background:{color};">'
        f"{rating_val:.1f} &#9733;</span>{reviews_html}"
    )


def _format_duration(value) -> str:
    """Format numeric minutes or API duration strings such as 05:45 / 5h 45m."""
    if value is None or value == "":
        return ""
    if isinstance(value, str):
        raw = value.strip()
        match = __import__("re").fullmatch(r"(\d{1,3}):(\d{2})", raw)
        if match:
            hours, minutes = int(match.group(1)), int(match.group(2))
            return f"{hours}h" if minutes == 0 else (f"{hours}h {minutes}m" if hours else f"{minutes}m")
        match = __import__("re").fullmatch(r"(?:(\d+)\s*h)?\s*(?:(\d+)\s*m)?", raw.lower())
        if match and (match.group(1) or match.group(2)):
            hours, minutes = int(match.group(1) or 0), int(match.group(2) or 0)
            return f"{hours}h" if minutes == 0 and hours else (f"{hours}h {minutes}m" if hours else f"{minutes}m")
    try:
        total_minutes = int(value)
    except (TypeError, ValueError):
        return ""
    if total_minutes < 0:
        return ""
    hours, minutes = divmod(total_minutes, 60)
    return f"{hours}h" if minutes == 0 else (f"{hours}h {minutes}m" if hours else f"{minutes}m")


def _chip(text: str, level: str) -> str:
    if level == "high":
        color, bg = CHIP_GREEN, CHIP_GREEN_BG
    elif level == "limited":
        color, bg = CHIP_AMBER, CHIP_AMBER_BG
    else:
        color, bg = CHIP_GREY, CHIP_GREY_BG
    return (
        f'<span style="display:inline-block;padding:4px 10px;margin:3px 6px 3px 0;'
        f"border-radius:999px;font-size:12px;font-weight:600;"
        f'color:{color};background:{bg};border:1px solid {color}22;">'
        f"{escape(text)}</span>"
    )


def _chip_level_for_count(available: int) -> str:
    if available >= 5:
        return "high"
    if available > 0:
        return "limited"
    return "none"


def _chip_level_for_status(status_text: str) -> str:
    s = status_text.strip().upper()
    if s.startswith("AVAILABLE"):
        return "high"
    if s.startswith("RAC"):
        return "limited"
    return "none"


def _bus_item_html(item: dict, booking_url: str) -> str:
    operator = escape(item.get("operator", "Unknown operator"))
    bus_type = escape(item.get("bus_type", ""))
    available = item.get("available", 0)
    total_seats = item.get("total_seats")
    single_seats = item.get("single_seats")
    price = item.get("price")
    departure = escape(item.get("departure_time", ""))
    arrival = escape(item.get("arrival_time", ""))
    new_badge = _new_badge() if item.get("is_new") else ""
    rating_html = _rating_badge(item.get("rating"), item.get("reviews"))
    duration_str = _format_duration(item.get("duration_min"))

    seats_label = f"{total_seats} Seats" if total_seats else f"{available} seats left"
    if single_seats:
        seats_label += f" ({single_seats} Single)"
    meta_line = duration_str
    if meta_line:
        meta_line += f" &middot; {seats_label}"
    else:
        meta_line = seats_label

    timing_html = f"{departure}"
    if arrival:
        timing_html += f' <span style="color:#c2c7cf;font-weight:400;">&mdash;</span> {arrival}'

    price_html = f"\u20b9{price:,.0f}" if price else ""

    return f"""
    <tr>
      <td style="padding:16px 18px;border-bottom:1px solid #eceef1;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
          <tr>
            <td style="font-size:18px;font-weight:700;color:#1a1d23;">{new_badge}{operator}</td>
            <td style="text-align:right;white-space:nowrap;">{rating_html}</td>
          </tr>
          <tr>
            <td colspan="2" style="font-size:13px;color:#5a6472;padding-top:1px;">{bus_type}</td>
          </tr>
          <tr>
            <td style="font-size:15px;font-weight:600;color:#1a1d23;padding-top:10px;">{timing_html}</td>
            <td style="font-size:15px;font-weight:600;color:#1a1d23;text-align:right;padding-top:10px;white-space:nowrap;">{price_html}</td>
          </tr>
          <tr>
            <td style="font-size:13px;color:#8a94a3;padding-top:2px;">{meta_line}</td>
            <td style="font-size:13px;color:#8a94a3;padding-top:2px;text-align:right;">{"Onwards" if price else ""}</td>
          </tr>
        </table>
      </td>
    </tr>"""


def _train_status_style(status_text: str):
    """Return semantic colors for railway availability statuses."""
    status = str(status_text or "").strip().upper()
    if status.startswith("AVAILABLE"):
        return "#16834a", "#e8f6ed", "#cfead8"
    if status.startswith("RAC"):
        return "#c45100", "#fff0e2", "#ffdfc2"
    if status.startswith("WL") or "WAITING" in status:
        return "#c62828", "#ffeaed", "#ffd1d8"
    if status.startswith("PQ") or status.startswith("REGRET") or status.startswith("NOT AVAILABLE"):
        return "#566171", "#eef0f3", "#dfe3e8"
    return "#566171", "#f2f3f5", "#e1e4e8"


def _format_train_fare(value):
    if value in (None, ""):
        return ""
    try:
        amount = float(str(value).replace(",", "").replace("₹", "").strip())
        return f"₹{amount:,.0f}"
    except (TypeError, ValueError):
        return f"₹{escape(str(value))}"


def _train_item_html(item: dict, booking_url: str) -> str:
    train_name = escape(str(item.get("train_name", "")))
    train_no = escape(str(item.get("train_no", "")))
    departure = escape(str(item.get("departure_time", "")))
    arrival = escape(str(item.get("arrival_time", "")))
    duration = _format_duration(item.get("duration"))
    if not duration:
        duration = _format_duration(item.get("duration_min"))
    new_badge = _new_badge() if item.get("is_new") else ""

    classes = item.get("classes")
    if not isinstance(classes, list):
        classes = [item]

    class_rows = []
    for class_item in classes:
        class_code = escape(str(class_item.get("class", "—") or "—"))
        status_text = str(class_item.get("status_text") or "Availability unknown")
        quota = str(class_item.get("quota") or "").strip()
        if quota and quota.upper() != "GN":
            status_text = f"{status_text} ({quota})"
        status_color, status_bg, status_border = _train_status_style(status_text)
        fare_html = escape(_format_train_fare(class_item.get("price")))
        class_rows.append(f"""
          <tr>
            <td width="72" style="width:72px;padding:2px 6px 2px 0;vertical-align:middle;">
              <div style="box-sizing:border-box;width:72px;text-align:center;padding:7px 4px;border-radius:8px;background:#eef0f2;border:1px solid #e0e3e7;color:#3f4a59;font-size:13px;font-weight:700;">{class_code}</div>
            </td>
            <td width="170" style="width:170px;padding:2px 8px 2px 0;vertical-align:middle;">
              <div style="box-sizing:border-box;width:170px;padding:7px 9px;border-radius:8px;background:{status_bg};border:1px solid {status_border};color:{status_color};font-size:13px;font-weight:600;white-space:nowrap;">
                {escape(status_text)}
              </div>
            </td>
            <td width="104" style="width:104px;padding:2px 0;vertical-align:middle;">
              <div style="box-sizing:border-box;width:104px;text-align:center;padding:7px 6px;border-radius:8px;background:#fff4cc;border:1px solid #ffe69a;color:#8b4513;font-size:13px;font-weight:700;white-space:nowrap;">{fare_html or "—"}</div>
            </td>
          </tr>""")

    details = []
    if departure:
        details.append(f"Departs {departure}")
    if arrival:
        details.append(f"Arrives {arrival}")
    if duration:
        details.append(f"Duration {duration}")
    details_html = " &middot; ".join(escape(part) for part in details)

    return f"""
    <tr>
      <td style="padding:12px 14px;border-bottom:1px solid #eceef1;">
        <div style="font-size:15px;font-weight:700;color:#1a1d23;">{new_badge}{train_name} ({train_no})</div>
        <div style="font-size:13px;color:#5a6472;margin-top:4px;">{details_html}</div>
        <table role="presentation" cellpadding="0" cellspacing="0" style="margin-top:7px;border-collapse:collapse;width:auto;">
          {''.join(class_rows)}
        </table>
      </td>
    </tr>"""


def _group_train_items(items: List[dict]) -> List[dict]:
    """Combine class-level snapshots into one email row per train instance."""
    grouped = {}
    ordered_keys = []
    for item in items:
        identity = (
            str(item.get("train_no") or item.get("train_name") or "").strip().lower(),
            str(item.get("from_station") or "").strip().upper(),
            str(item.get("to_station") or "").strip().upper(),
            str(item.get("availability_date") or "").strip(),
        )
        if identity not in grouped:
            grouped[identity] = {**item, "classes": [item], "is_new": bool(item.get("is_new"))}
            ordered_keys.append(identity)
        else:
            grouped[identity]["classes"].append(item)
            grouped[identity]["is_new"] = grouped[identity]["is_new"] or bool(item.get("is_new"))
            for field in ("departure_time", "arrival_time", "duration"):
                if not grouped[identity].get(field) and item.get(field):
                    grouped[identity][field] = item[field]
    return [grouped[key] for key in ordered_keys]


def _watch_section_html(watch_label: str, watch_url: str, items_html: str) -> str:
    return f"""
  <tr>
    <td style="padding:22px 0 6px 0;">
      <a href="{escape(watch_url)}" style="font-size:16px;font-weight:700;color:#0f62d6;text-decoration:none;">
        {escape(watch_label)} &rarr;
      </a>
    </td>
  </tr>
  <tr>
    <td>
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
             style="background:#ffffff;border:1px solid #eceef1;border-radius:10px;overflow:hidden;">
        {items_html}
      </table>
    </td>
  </tr>"""


def build_digest_email(sections: List[Dict]) -> str:
    """
    sections: list of dicts, each:
      {
        "watch_label": str,
        "watch_url": str,
        "type": "bus" | "train",
        "items": [ {...bus or train fields...} ]
      }
    Returns full HTML document string.
    """
    body_sections = []
    for section in sections:
        if section["type"] == "bus":
            items_html = "".join(_bus_item_html(i, section["watch_url"]) for i in section["items"])
        else:
            train_items = _group_train_items(section["items"])
            items_html = "".join(_train_item_html(i, section["watch_url"]) for i in train_items)
        body_sections.append(
            _watch_section_html(section["watch_label"], section["watch_url"], items_html)
        )

    sections_html = "".join(body_sections)
    timestamp = _now_ist_str()

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f4f5f7;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f4f5f7;padding:24px 0;">
    <tr>
      <td align="center">
        <table role="presentation" width="600" cellpadding="0" cellspacing="0"
               style="background:#ffffff;border-radius:14px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.06);">
          <tr>
            <td style="background:linear-gradient(135deg,#0f62d6 0%,#7c3aed 100%);padding:28px 24px;">
              <div style="font-size:20px;font-weight:700;color:#ffffff;">Seats just opened up \U0001F68C\U0001F686</div>
              <div style="font-size:13px;color:#e4e9ff;margin-top:4px;">RedRail availability alert &middot; {timestamp}</div>
            </td>
          </tr>
          <tr>
            <td style="padding:6px 24px 24px 24px;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                {sections_html}
              </table>
            </td>
          </tr>
          <tr>
            <td style="padding:16px 24px;background:#f9fafb;border-top:1px solid #eceef1;">
              <div style="font-size:12px;color:#8a94a3;">
                You're receiving this because this route/date is in your RedRail watch list. Availability can change fast &mdash; book quickly once you get this.
              </div>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def build_failure_alert_email(watch_label: str, consecutive_failures: int, threshold: int) -> str:
    """Mirrors the BMS consecutive-failure alert - lets you know the watcher itself is broken."""
    timestamp = _now_ist_str()
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f4f5f7;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f4f5f7;padding:24px 0;">
    <tr>
      <td align="center">
        <table role="presentation" width="560" cellpadding="0" cellspacing="0"
               style="background:#ffffff;border-radius:14px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.06);">
          <tr>
            <td style="background:#b3261e;padding:22px 24px;">
              <div style="font-size:18px;font-weight:700;color:#ffffff;">Watcher fetch failing repeatedly</div>
              <div style="font-size:13px;color:#ffd9d6;margin-top:4px;">{timestamp}</div>
            </td>
          </tr>
          <tr>
            <td style="padding:20px 24px;">
              <p style="font-size:14px;color:#1a1d23;line-height:1.5;">
                The watch <strong>{escape(watch_label)}</strong> has failed to fetch
                <strong>{consecutive_failures}</strong> times in a row (threshold: {threshold}).
                RedBus may be blocking requests, or the page structure may have changed.
              </p>
              <p style="font-size:13px;color:#5a6472;">Check the GitHub Actions run logs for details.</p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""
