"""The single Jinja2 environment.

One instance, imported by every router. `app_name` is exposed globally so
templates do not each have to be handed it; per-request data (the request, the
current user) is still passed explicitly in each route's context.
"""

from datetime import UTC, datetime

from fastapi.templating import Jinja2Templates

from app.settings import settings

templates = Jinja2Templates(directory="templates")
templates.env.globals["app_name"] = settings.app_name
# `now()` is used by the layout (year in the footer). UTC keeps the
# rendered year deterministic regardless of where the server lives.
templates.env.globals["now"] = lambda: datetime.now(UTC)


def _relative_time(value: datetime | None) -> str:
    """Coarse "5 minutes ago" rendering for the sessions list.

    No `humanize` dependency - the buckets here are big enough that the
    naive arithmetic reads correctly without grammar gymnastics. SQLite
    stores tz-aware columns as naive, so we normalise on the way in."""
    if value is None:
        return ""
    when = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    delta = datetime.now(UTC) - when
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return "just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = hours // 24
    if days < 30:
        return f"{days} day{'s' if days != 1 else ''} ago"
    months = days // 30
    if months < 12:
        return f"{months} month{'s' if months != 1 else ''} ago"
    years = days // 365
    return f"{years} year{'s' if years != 1 else ''} ago"


def _short_user_agent(ua: str | None) -> str:
    """A friendly "Chrome on macOS"-style label.

    Real UA parsing belongs in a library if we ever need accuracy. This is
    a guesstimate good enough for the sessions list to be scannable. The
    full UA is still on the row in a title attribute for the curious."""
    if not ua:
        return "Unknown device"
    s = ua.lower()
    if "edg/" in s:
        browser = "Edge"
    elif "firefox" in s:
        browser = "Firefox"
    elif "chrome" in s and "chromium" not in s:
        browser = "Chrome"
    elif "safari" in s:
        browser = "Safari"
    else:
        browser = "Browser"
    if "iphone" in s:
        platform = "iPhone"
    elif "ipad" in s:
        platform = "iPad"
    elif "android" in s:
        platform = "Android"
    elif "mac os" in s or "macintosh" in s:
        platform = "macOS"
    elif "windows" in s:
        platform = "Windows"
    elif "linux" in s:
        platform = "Linux"
    else:
        platform = "device"
    return f"{browser} on {platform}"


templates.env.filters["relative_time"] = _relative_time
templates.env.filters["short_user_agent"] = _short_user_agent
