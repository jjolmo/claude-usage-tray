"""Claude.ai usage API client."""

import json
import ssl
import urllib.request
import urllib.error
from datetime import datetime, timezone


class AuthError(Exception):
    pass


class APIError(Exception):
    pass


def _create_ssl_context():
    ctx = ssl.create_default_context()
    try:
        import certifi
        ctx.load_verify_locations(certifi.where())
    except ImportError:
        pass
    return ctx

SSL_CTX = _create_ssl_context()

ORGS_URL = "https://claude.ai/api/organizations"
USAGE_URL = "https://claude.ai/api/organizations/{org_id}/usage"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
    "Referer": "https://claude.ai/settings/usage",
    "Origin": "https://claude.ai",
    "Sec-Ch-Ua": '"Chromium";v="146", "Not-A.Brand";v="24", "Google Chrome";v="146"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}


def _api_get(url: str, session_cookie: str):
    """Make an authenticated GET request to claude.ai."""
    req = urllib.request.Request(url)
    req.add_header("Cookie", f"sessionKey={session_cookie}")
    for key, val in HEADERS.items():
        req.add_header(key, val)
    try:
        with urllib.request.urlopen(req, timeout=15, context=SSL_CTX) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise AuthError(f"Authentication failed (HTTP {e.code}). Update your session cookie.")
        raise APIError(f"HTTP {e.code}")
    except Exception as e:
        raise APIError(str(e))


def fetch_org_id(session_cookie: str) -> str:
    """Auto-detect the organization ID from the session cookie.

    Returns the UUID of the first organization found.
    Raises AuthError/APIError on failure.
    """
    data = _api_get(ORGS_URL, session_cookie)
    if isinstance(data, list) and len(data) > 0:
        org_id = data[0].get("uuid") or data[0].get("id", "")
        if org_id:
            return org_id
    raise APIError("Could not detect organization ID from your account.")


def fetch_usage(session_cookie: str, org_id: str) -> dict:
    """Fetch usage data from claude.ai.

    Returns the raw JSON response dict.
    Raises AuthError on 401/403, APIError on other failures.
    """
    url = USAGE_URL.format(org_id=org_id)
    return _api_get(url, session_cookie)


def parse_usage(data: dict) -> dict:
    """Parse API response into a friendly dict.

    Returns:
        {
            "session_pct": int,
            "session_reset": str,  # relative time string
            "weekly_pct": int,
            "weekly_reset": str,
            "sonnet_pct": int | None,
            "sonnet_reset": str | None,
        }
    """
    result = {}

    five_hour = data.get("five_hour", {})
    seven_day = data.get("seven_day", {})
    sonnet = data.get("seven_day_sonnet")

    result["session_pct"] = int(five_hour.get("utilization", 0))
    result["session_reset"] = _format_reset(five_hour.get("resets_at", ""))
    result["weekly_pct"] = int(seven_day.get("utilization", 0))
    result["weekly_reset"] = _format_reset(seven_day.get("resets_at", ""))

    if sonnet:
        result["sonnet_pct"] = int(sonnet.get("utilization", 0))
        result["sonnet_reset"] = _format_reset(sonnet.get("resets_at", ""))
    else:
        result["sonnet_pct"] = None
        result["sonnet_reset"] = None

    return result


def _format_reset(iso_str: str) -> str:
    """Format ISO timestamp as relative time string."""
    try:
        reset = datetime.fromisoformat(iso_str)
        now = datetime.now(timezone.utc)
        total_min = int((reset - now).total_seconds() / 60)
        if total_min < 0:
            return "now"
        if total_min < 60:
            return f"{total_min}m"
        hours = total_min // 60
        mins = total_min % 60
        if hours < 24:
            return f"{hours}h{mins}m"
        days = hours // 24
        return f"{days}d {hours % 24}h"
    except Exception:
        return "?"
