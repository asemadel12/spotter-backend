from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, tzinfo
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

METERS_PER_MILE = Decimal("1609.344")
SECONDS_PER_DAY = 86_400
MICROSECONDS_PER_SECOND = 1_000_000
MICROSECONDS_PER_DAY = SECONDS_PER_DAY * MICROSECONDS_PER_SECOND
VALID_STATUSES = {
    "OFF_DUTY",
    "SLEEPER_BERTH",
    "DRIVING",
    "ON_DUTY_NOT_DRIVING",
}


class DailyLogBuildError(ValueError):
    """Raised when schedule data cannot produce a valid daily log."""


@dataclass(frozen=True)
class _SourceEvent:
    event_type: str
    status: str
    start: datetime
    end: datetime
    duration_microseconds: int
    distance_meters: Decimal
    location: str
    reason: str
    route_progress: Mapping[str, Any] | None


@dataclass(frozen=True)
class _EventFragment:
    event_type: str
    status: str
    start: datetime
    end: datetime
    duration_microseconds: int
    distance_meters: Decimal
    location: str
    reason: str
    route_progress: dict[str, Any] | None

    def as_dict(self) -> dict[str, Any]:
        result = {
            "type": self.event_type,
            "status": self.status,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "duration_seconds": _seconds_number(self.duration_microseconds),
            "distance_meters": _decimal_number(self.distance_meters),
            "location": self.location,
            "reason": self.reason,
        }
        if self.route_progress is not None:
            result["route_progress"] = deepcopy(self.route_progress)
        return result


@dataclass
class _DayData:
    day: date
    start: datetime
    fragments: list[_EventFragment] = field(default_factory=list)
    remarks: list[dict[str, Any]] = field(default_factory=list)


def build_daily_logs(
    *,
    schedule: Mapping[str, Any],
    locations: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Convert a normalized HOS schedule into complete 24-hour log data.

    Gaps between otherwise valid source events are explicitly represented as
    OFF_DUTY. The timezone/UTC offset from the schedule is used consistently;
    the service never infers timezone changes along the route.
    """

    source_events, schedule_timezone = _parse_schedule(schedule)
    days = _initialize_days(source_events, schedule_timezone)

    last_route_distance: Decimal | None = None
    for source_event in source_events:
        for fragment in _split_event(source_event, schedule_timezone):
            day_data = days[fragment.start.date()]
            day_data.fragments.append(fragment)
            remark, last_route_distance = _build_remark(
                fragment,
                locations,
                last_route_distance,
                day_data.start,
            )
            day_data.remarks.append(remark)

    total_distance = sum(
        (
            fragment.distance_meters
            for day_data in days.values()
            for fragment in day_data.fragments
            if fragment.status == "DRIVING"
        ),
        Decimal("0"),
    )
    _validate_schedule_distance(schedule, total_distance)
    logs = [_build_day_log(day_data) for day_data in days.values()]

    return {
        "summary": {
            "log_count": len(logs),
            "start_date": logs[0]["date"],
            "end_date": logs[-1]["date"],
            "total_driving_distance_meters": _decimal_number(total_distance),
            "total_driving_distance_miles": _decimal_number(
                total_distance / METERS_PER_MILE
            ),
        },
        "logs": logs,
    }


def _parse_schedule(
    schedule: Mapping[str, Any],
) -> tuple[list[_SourceEvent], tzinfo]:
    if not isinstance(schedule, Mapping):
        raise DailyLogBuildError("Schedule must be a mapping.")
    raw_events = schedule.get("events")
    if not isinstance(raw_events, list) or not raw_events:
        raise DailyLogBuildError("Schedule events must be a non-empty list.")

    events: list[_SourceEvent] = []
    schedule_timezone: tzinfo | None = None
    schedule_offset = None
    previous_start: datetime | None = None
    previous_end: datetime | None = None

    for raw_event in raw_events:
        if not isinstance(raw_event, Mapping):
            raise DailyLogBuildError("Schedule event is malformed.")

        start = _parse_datetime(raw_event.get("start"))
        end = _parse_datetime(raw_event.get("end"))
        if end <= start:
            raise DailyLogBuildError("Schedule event must have a positive duration.")

        if schedule_timezone is None:
            schedule_timezone = start.tzinfo
            schedule_offset = start.utcoffset()
        if start.utcoffset() != schedule_offset or end.utcoffset() != schedule_offset:
            raise DailyLogBuildError("Schedule events must use one timezone offset.")

        start = start.astimezone(schedule_timezone)
        end = end.astimezone(schedule_timezone)
        if previous_start is not None and start < previous_start:
            raise DailyLogBuildError("Schedule events are not chronological.")
        if previous_end is not None and start < previous_end:
            raise DailyLogBuildError("Schedule events overlap.")

        status = raw_event.get("status")
        if status not in VALID_STATUSES:
            raise DailyLogBuildError("Schedule event has an unknown duty status.")
        event_type = raw_event.get("type")
        if not isinstance(event_type, str) or not event_type:
            raise DailyLogBuildError("Schedule event type is malformed.")

        duration_microseconds = _timedelta_microseconds(end - start)
        reported_duration = _decimal(
            raw_event.get("duration_seconds"), "event duration"
        )
        actual_duration = Decimal(duration_microseconds) / MICROSECONDS_PER_SECOND
        if abs(reported_duration - actual_duration) > Decimal("0.000001"):
            raise DailyLogBuildError("Event duration does not match its timestamps.")

        distance = _decimal(raw_event.get("distance_meters", 0), "event distance")
        if distance < 0:
            raise DailyLogBuildError("Event distance cannot be negative.")
        if status != "DRIVING" and distance != 0:
            raise DailyLogBuildError("Only driving events may contain distance.")

        location = raw_event.get("location", "en_route")
        reason = raw_event.get("reason", "")
        if not isinstance(location, str) or not isinstance(reason, str):
            raise DailyLogBuildError("Event location or reason is malformed.")
        route_progress = raw_event.get("route_progress")
        if route_progress is not None and not isinstance(route_progress, Mapping):
            raise DailyLogBuildError("Event route progress is malformed.")

        events.append(
            _SourceEvent(
                event_type=event_type,
                status=status,
                start=start,
                end=end,
                duration_microseconds=duration_microseconds,
                distance_meters=distance,
                location=location,
                reason=reason,
                route_progress=route_progress,
            )
        )
        previous_start = start
        previous_end = end

    if schedule_timezone is None:
        raise DailyLogBuildError("Schedule timezone is missing.")
    return events, schedule_timezone


def _initialize_days(
    events: list[_SourceEvent], schedule_timezone: tzinfo
) -> dict[date, _DayData]:
    first_date = events[0].start.date()
    last_end = events[-1].end
    last_date = last_end.date()
    if last_end.time() == time.min:
        last_date -= timedelta(days=1)

    days: dict[date, _DayData] = {}
    current_date = first_date
    while current_date <= last_date:
        day_start = datetime.combine(current_date, time.min, schedule_timezone)
        days[current_date] = _DayData(day=current_date, start=day_start)
        current_date += timedelta(days=1)
    return days


def _split_event(
    event: _SourceEvent, schedule_timezone: tzinfo
) -> list[_EventFragment]:
    fragments: list[_EventFragment] = []
    cursor = event.start
    allocated_distance = Decimal("0")
    allocated_duration = 0

    while cursor < event.end:
        next_midnight = datetime.combine(
            cursor.date() + timedelta(days=1),
            time.min,
            schedule_timezone,
        )
        fragment_end = min(event.end, next_midnight)
        duration_microseconds = _timedelta_microseconds(fragment_end - cursor)
        if duration_microseconds <= 0:
            raise DailyLogBuildError("Midnight split produced an invalid fragment.")

        allocated_duration += duration_microseconds
        if event.status != "DRIVING":
            distance = Decimal("0")
        elif allocated_duration == event.duration_microseconds:
            distance = event.distance_meters - allocated_distance
        else:
            distance = (
                event.distance_meters
                * Decimal(duration_microseconds)
                / Decimal(event.duration_microseconds)
            )
            allocated_distance += distance

        route_progress = _fragment_route_progress(
            event,
            allocated_distance + distance
            if allocated_duration == event.duration_microseconds
            else allocated_distance,
        )
        fragments.append(
            _EventFragment(
                event_type=event.event_type,
                status=event.status,
                start=cursor,
                end=fragment_end,
                duration_microseconds=duration_microseconds,
                distance_meters=distance,
                location=event.location,
                reason=event.reason,
                route_progress=route_progress,
            )
        )
        cursor = fragment_end

    return fragments


def _fragment_route_progress(
    event: _SourceEvent, cumulative_fragment_distance: Decimal
) -> dict[str, Any] | None:
    if event.route_progress is None:
        return None

    result = deepcopy(dict(event.route_progress))
    end_distance_value = result.get("route_distance_traveled_meters")
    remaining_distance_value = result.get("route_distance_remaining_meters")
    if event.status == "DRIVING" and end_distance_value is not None:
        source_end_distance = _decimal(
            end_distance_value, "route progress distance"
        )
        source_start_distance = source_end_distance - event.distance_meters
        fragment_end_distance = source_start_distance + cumulative_fragment_distance
        result["route_distance_traveled_meters"] = _decimal_number(
            fragment_end_distance
        )
        if remaining_distance_value is not None:
            source_remaining = _decimal(
                remaining_distance_value, "route remaining distance"
            )
            result["route_distance_remaining_meters"] = _decimal_number(
                source_remaining + event.distance_meters - cumulative_fragment_distance
            )
    return result


def _build_day_log(day_data: _DayData) -> dict[str, Any]:
    segments = _build_segments(day_data)
    totals_microseconds = {status: 0 for status in VALID_STATUSES}
    for segment in segments:
        totals_microseconds[segment["status"]] += segment.pop(
            "_duration_microseconds"
        )

    total_microseconds = sum(totals_microseconds.values())
    if total_microseconds != MICROSECONDS_PER_DAY:
        raise DailyLogBuildError("Daily duty-status totals do not cover 24 hours.")

    driving_distance = sum(
        (
            fragment.distance_meters
            for fragment in day_data.fragments
            if fragment.status == "DRIVING"
        ),
        Decimal("0"),
    )
    return {
        "date": day_data.day.isoformat(),
        "timezone": _format_offset(day_data.start.utcoffset()),
        "driving_distance_meters": _decimal_number(driving_distance),
        "driving_distance_miles": _decimal_number(
            driving_distance / METERS_PER_MILE
        ),
        "totals": {
            "off_duty_seconds": _seconds_number(
                totals_microseconds["OFF_DUTY"]
            ),
            "sleeper_berth_seconds": _seconds_number(
                totals_microseconds["SLEEPER_BERTH"]
            ),
            "driving_seconds": _seconds_number(
                totals_microseconds["DRIVING"]
            ),
            "on_duty_not_driving_seconds": _seconds_number(
                totals_microseconds["ON_DUTY_NOT_DRIVING"]
            ),
            "total_seconds": SECONDS_PER_DAY,
        },
        "segments": segments,
        "events": [fragment.as_dict() for fragment in day_data.fragments],
        "remarks": day_data.remarks,
    }


def _build_segments(day_data: _DayData) -> list[dict[str, Any]]:
    raw_segments: list[tuple[str, int, int]] = []
    cursor = 0
    for fragment in day_data.fragments:
        start = _timedelta_microseconds(fragment.start - day_data.start)
        end = _timedelta_microseconds(fragment.end - day_data.start)
        if not 0 <= start < end <= MICROSECONDS_PER_DAY:
            raise DailyLogBuildError("Daily event fragment is outside its log day.")
        if start < cursor:
            raise DailyLogBuildError("Daily event fragments overlap.")
        if start > cursor:
            raw_segments.append(("OFF_DUTY", cursor, start))
        raw_segments.append((fragment.status, start, end))
        cursor = end

    if cursor < MICROSECONDS_PER_DAY:
        raw_segments.append(("OFF_DUTY", cursor, MICROSECONDS_PER_DAY))

    merged: list[tuple[str, int, int]] = []
    for status, start, end in raw_segments:
        if merged and merged[-1][0] == status and merged[-1][2] == start:
            previous_status, previous_start, _ = merged[-1]
            merged[-1] = (previous_status, previous_start, end)
        else:
            merged.append((status, start, end))

    segments = []
    for status, start, end in merged:
        duration = end - start
        if duration <= 0:
            raise DailyLogBuildError("Daily segment has no duration.")
        segments.append(
            {
                "status": status,
                "start_second": _seconds_number(start),
                "end_second": _seconds_number(end),
                "duration_seconds": _seconds_number(duration),
                "_duration_microseconds": duration,
            }
        )

    if not segments or segments[0]["start_second"] != 0:
        raise DailyLogBuildError("Daily segments do not start at midnight.")
    if segments[-1]["end_second"] != SECONDS_PER_DAY:
        raise DailyLogBuildError("Daily segments do not end at midnight.")
    return segments


def _build_remark(
    fragment: _EventFragment,
    locations: Mapping[str, Any] | None,
    last_route_distance: Decimal | None,
    day_start: datetime,
) -> tuple[dict[str, Any], Decimal | None]:
    route_distance = last_route_distance
    if fragment.status == "DRIVING" and fragment.route_progress is not None:
        end_value = fragment.route_progress.get("route_distance_traveled_meters")
        if end_value is not None:
            end_distance = _decimal(end_value, "remark route distance")
            route_distance = end_distance - fragment.distance_meters

    second_of_day = _timedelta_microseconds(fragment.start - day_start)
    remark = {
        "second_of_day": _seconds_number(second_of_day),
        "time": fragment.start.strftime("%H:%M"),
        "event_type": fragment.event_type,
        "status": fragment.status,
        "location": _remark_location(fragment, locations, route_distance),
        "reason": fragment.reason,
    }
    if route_distance is not None:
        remark["route_distance_traveled_meters"] = _decimal_number(route_distance)

    if fragment.status == "DRIVING" and fragment.route_progress is not None:
        end_value = fragment.route_progress.get("route_distance_traveled_meters")
        if end_value is not None:
            route_distance = _decimal(end_value, "remark route distance")
    return remark, route_distance


def _remark_location(
    fragment: _EventFragment,
    locations: Mapping[str, Any] | None,
    route_distance: Decimal | None,
) -> dict[str, str]:
    location_ref = fragment.location
    if fragment.status == "DRIVING":
        if route_distance is not None and route_distance == 0:
            location_ref = "current_location"
        else:
            location_ref = "en_route"

    if location_ref in {"current_location", "pickup_location", "dropoff_location"}:
        label = _location_label(locations, location_ref)
        if label is not None:
            return {"ref": location_ref, "label": label}
    if location_ref == "en_route" or fragment.status == "DRIVING":
        return {"ref": "en_route", "label": "En route"}
    return {"ref": location_ref, "label": location_ref.replace("_", " ").title()}


def _location_label(
    locations: Mapping[str, Any] | None, location_ref: str
) -> str | None:
    if not isinstance(locations, Mapping):
        return None
    location = locations.get(location_ref)
    if not isinstance(location, Mapping):
        return None
    label = location.get("label")
    if isinstance(label, str) and label.strip():
        return label
    return None


def _validate_schedule_distance(
    schedule: Mapping[str, Any], event_distance: Decimal
) -> None:
    summary = schedule.get("summary")
    if not isinstance(summary, Mapping):
        return
    expected_value = summary.get("total_trip_distance_meters")
    if expected_value is None:
        return
    expected = _decimal(expected_value, "schedule distance")
    if abs(expected - event_distance) > Decimal("0.01"):
        raise DailyLogBuildError("Schedule distance does not match driving events.")


def _parse_datetime(value: Any) -> datetime:
    if not isinstance(value, str):
        raise DailyLogBuildError("Schedule timestamp is malformed.")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise DailyLogBuildError("Schedule timestamp is malformed.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise DailyLogBuildError("Schedule timestamp must be timezone-aware.")
    return parsed


def _decimal(value: Any, name: str) -> Decimal:
    if isinstance(value, bool):
        raise DailyLogBuildError(f"{name} is malformed.")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise DailyLogBuildError(f"{name} is malformed.") from exc
    if not result.is_finite():
        raise DailyLogBuildError(f"{name} is malformed.")
    return result


def _timedelta_microseconds(value: timedelta) -> int:
    return (
        (value.days * SECONDS_PER_DAY + value.seconds) * MICROSECONDS_PER_SECOND
        + value.microseconds
    )


def _seconds_number(microseconds: int) -> int | float:
    if microseconds % MICROSECONDS_PER_SECOND == 0:
        return microseconds // MICROSECONDS_PER_SECOND
    return float(Decimal(microseconds) / MICROSECONDS_PER_SECOND)


def _decimal_number(value: Decimal) -> int | float:
    if value == value.to_integral_value():
        return int(value)
    return float(value)


def _format_offset(offset: timedelta | None) -> str:
    if offset is None:
        raise DailyLogBuildError("Daily log timezone is missing.")
    total_minutes = int(offset.total_seconds() // 60)
    sign = "+" if total_minutes >= 0 else "-"
    total_minutes = abs(total_minutes)
    hours, minutes = divmod(total_minutes, 60)
    return f"{sign}{hours:02d}:{minutes:02d}"
