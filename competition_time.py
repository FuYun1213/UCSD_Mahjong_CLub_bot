"""Club-local event time, stored as UTC; never infer it from upload timestamps."""
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


def site_timezone():
    return os.getenv("SITE_TIMEZONE", "America/Los_Angeles")


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def local_day_utc_bounds(day, zone=None):
    """Return UTC ISO boundaries for one club-local calendar day."""
    local_zone = ZoneInfo(zone or site_timezone())
    start = datetime.strptime(str(day), "%Y-%m-%d").replace(tzinfo=local_zone)
    end = start + timedelta(days=1)
    return (start.astimezone(timezone.utc).isoformat(timespec="seconds"),
            end.astimezone(timezone.utc).isoformat(timespec="seconds"))


def event_time(value, zone=None):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("played_at_required")
    try:
        stamp = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            local_zone = ZoneInfo(zone or site_timezone())
            candidates = {stamp.replace(tzinfo=local_zone, fold=fold).astimezone(timezone.utc)
                          for fold in (0, 1)
                          if stamp.replace(tzinfo=local_zone, fold=fold).astimezone(timezone.utc).astimezone(local_zone).replace(tzinfo=None) == stamp}
            if len(candidates) != 1:
                raise ValueError("ambiguous_or_nonexistent_local_time")
            stamp = candidates.pop()
        return stamp.astimezone(timezone.utc).isoformat(timespec="seconds")
    except (TypeError, OverflowError) as error:
        raise ValueError("invalid_played_at") from error


def in_range(played_at, start_at, end_at):
    return bool(played_at) and event_time(start_at) <= event_time(played_at) < event_time(end_at)


def phase(start_at, end_at, clock=None):
    now = event_time(clock or utc_now())
    return "upcoming" if now < start_at else "ended" if now >= end_at else "live"
