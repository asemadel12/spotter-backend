from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from enum import Enum
from typing import Any, Mapping

SECONDS_PER_HOUR = Decimal("3600")
DRIVING_LIMIT_SECONDS = Decimal("11") * SECONDS_PER_HOUR
DUTY_WINDOW_SECONDS = Decimal("14") * SECONDS_PER_HOUR
BREAK_DRIVING_LIMIT_SECONDS = Decimal("8") * SECONDS_PER_HOUR
BREAK_DURATION_SECONDS = Decimal("1800")
DAILY_REST_SECONDS = Decimal("10") * SECONDS_PER_HOUR
CYCLE_LIMIT_SECONDS = Decimal("70") * SECONDS_PER_HOUR
CYCLE_RESTART_SECONDS = Decimal("34") * SECONDS_PER_HOUR
SERVICE_STOP_SECONDS = Decimal("3600")
METERS_PER_MILE = Decimal("1609.344")
FUEL_INTERVAL_METERS = Decimal("1000") * METERS_PER_MILE
FUEL_DURATION_SECONDS = Decimal("1800")

_EPSILON = Decimal("0.000001")
_MAX_SCHEDULING_ITERATIONS = 100_000
_EXPECTED_LEGS = (
    ("current_location", "pickup_location"),
    ("pickup_location", "dropoff_location"),
)


class HosPlanningError(ValueError):
    """Raised when normalized route data cannot produce a safe HOS schedule."""


class DutyStatus(str, Enum):
    OFF_DUTY = "OFF_DUTY"
    SLEEPER_BERTH = "SLEEPER_BERTH"
    DRIVING = "DRIVING"
    ON_DUTY_NOT_DRIVING = "ON_DUTY_NOT_DRIVING"


class EventType(str, Enum):
    DRIVING = "DRIVING"
    PICKUP = "PICKUP"
    DROPOFF = "DROPOFF"
    BREAK = "BREAK"
    FUEL = "FUEL"
    SLEEPER = "SLEEPER"
    CYCLE_RESTART = "CYCLE_RESTART"


@dataclass
class _StepProgress:
    leg_index: int
    step_index: int
    duration_seconds: Decimal
    distance_meters: Decimal
    way_points: tuple[int, int]
    consumed_duration_seconds: Decimal = Decimal("0")
    consumed_distance_meters: Decimal = Decimal("0")

    @property
    def remaining_duration_seconds(self) -> Decimal:
        return max(
            Decimal("0"),
            self.duration_seconds - self.consumed_duration_seconds,
        )

    @property
    def remaining_distance_meters(self) -> Decimal:
        return max(
            Decimal("0"),
            self.distance_meters - self.consumed_distance_meters,
        )


@dataclass
class _LegProgress:
    index: int
    from_name: str
    to_name: str
    duration_seconds: Decimal
    distance_meters: Decimal
    steps: list[_StepProgress]
    step_cursor: int = 0
    consumed_duration_seconds: Decimal = Decimal("0")
    consumed_distance_meters: Decimal = Decimal("0")

    @property
    def remaining_duration_seconds(self) -> Decimal:
        return max(
            Decimal("0"),
            self.duration_seconds - self.consumed_duration_seconds,
        )

    @property
    def remaining_distance_meters(self) -> Decimal:
        return max(
            Decimal("0"),
            self.distance_meters - self.consumed_distance_meters,
        )

    @property
    def complete(self) -> bool:
        return self.remaining_duration_seconds <= _EPSILON


@dataclass(frozen=True)
class RouteChunk:
    duration_seconds: Decimal
    distance_meters: Decimal
    metadata: dict[str, Any]


class RouteProgress:
    """Consumes a normalized route by driving time without assuming a speed."""

    def __init__(self, route: Mapping[str, Any]):
        self._total_duration_seconds = _measure(
            route.get("duration_seconds"), "route duration"
        )
        self._total_distance_meters = _measure(
            route.get("distance_meters"), "route distance"
        )
        self._legs = _build_legs(
            route.get("legs"),
            self._total_duration_seconds,
            self._total_distance_meters,
        )
        self._leg_cursor = 0
        self._consumed_duration_seconds = Decimal("0")
        self._consumed_distance_meters = Decimal("0")

    @property
    def total_duration_seconds(self) -> Decimal:
        return self._total_duration_seconds

    @property
    def total_distance_meters(self) -> Decimal:
        return self._total_distance_meters

    @property
    def consumed_duration_seconds(self) -> Decimal:
        return self._consumed_duration_seconds

    @property
    def consumed_distance_meters(self) -> Decimal:
        return self._consumed_distance_meters

    @property
    def remaining_duration_seconds(self) -> Decimal:
        return max(
            Decimal("0"),
            self._total_duration_seconds - self._consumed_duration_seconds,
        )

    @property
    def remaining_distance_meters(self) -> Decimal:
        return max(
            Decimal("0"),
            self._total_distance_meters - self._consumed_distance_meters,
        )

    @property
    def complete(self) -> bool:
        return self._leg_cursor >= len(self._legs)

    @property
    def current_leg_index(self) -> int:
        if self.complete:
            raise HosPlanningError("Route progression is already complete.")
        return self._leg_cursor

    @property
    def current_leg(self) -> _LegProgress:
        if self.complete:
            raise HosPlanningError("Route progression is already complete.")
        return self._legs[self._leg_cursor]

    @property
    def current_leg_complete(self) -> bool:
        return self.current_leg.complete

    @property
    def remaining_current_leg_duration_seconds(self) -> Decimal:
        return self.current_leg.remaining_duration_seconds

    def advance_leg(self) -> None:
        if not self.current_leg.complete:
            raise HosPlanningError("Cannot advance before completing the route leg.")
        self._leg_cursor += 1

    def time_until_distance(self, distance_meters: Decimal) -> Decimal:
        """Return driving time to a distance within the current route leg."""

        target = max(Decimal("0"), distance_meters)
        if target <= _EPSILON:
            return Decimal("0")

        leg = self.current_leg
        elapsed = Decimal("0")
        for index in range(leg.step_cursor, len(leg.steps)):
            step = leg.steps[index]
            duration = step.remaining_duration_seconds
            distance = step.remaining_distance_meters

            if distance <= _EPSILON:
                elapsed += duration
                continue

            if distance <= target + _EPSILON:
                elapsed += duration
                target -= distance
                if target <= _EPSILON:
                    return min(elapsed, leg.remaining_duration_seconds)
                continue

            return min(
                elapsed + (duration * target / distance),
                leg.remaining_duration_seconds,
            )

        return leg.remaining_duration_seconds

    def consume_time(self, duration_seconds: Decimal) -> RouteChunk:
        requested = _seconds(duration_seconds)
        leg = self.current_leg
        if requested <= _EPSILON:
            raise HosPlanningError("Driving chunks must have a positive duration.")
        if requested > leg.remaining_duration_seconds + _EPSILON:
            raise HosPlanningError("Driving chunk exceeds the current route leg.")

        requested = min(requested, leg.remaining_duration_seconds)
        remaining = requested
        distance = Decimal("0")
        first_step: _StepProgress | None = None
        last_step: _StepProgress | None = None

        while remaining > _EPSILON:
            _skip_completed_steps(leg)
            if leg.step_cursor >= len(leg.steps):
                raise HosPlanningError("Route steps ended before the route leg.")

            step = leg.steps[leg.step_cursor]
            step_remaining_time = step.remaining_duration_seconds
            take = min(remaining, step_remaining_time)
            if first_step is None:
                first_step = step
            last_step = step

            if take >= step_remaining_time - _EPSILON:
                step_distance = step.remaining_distance_meters
            else:
                step_distance = (
                    step.remaining_distance_meters * take / step_remaining_time
                )

            step.consumed_duration_seconds += take
            step.consumed_distance_meters += step_distance
            leg.consumed_duration_seconds += take
            leg.consumed_distance_meters += step_distance
            self._consumed_duration_seconds += take
            self._consumed_distance_meters += step_distance
            distance += step_distance
            remaining -= take

            if step.remaining_duration_seconds <= _EPSILON:
                step.consumed_duration_seconds = step.duration_seconds
                step.consumed_distance_meters = step.distance_meters
                leg.step_cursor += 1

        if leg.remaining_duration_seconds <= _EPSILON:
            distance_correction = leg.distance_meters - leg.consumed_distance_meters
            leg.consumed_duration_seconds = leg.duration_seconds
            leg.consumed_distance_meters = leg.distance_meters
            self._consumed_duration_seconds = min(
                self._total_duration_seconds,
                self._consumed_duration_seconds,
            )
            self._consumed_distance_meters += distance_correction
            distance += distance_correction

        if first_step is None or last_step is None:
            raise HosPlanningError("Driving did not advance route progress.")

        metadata = {
            "leg_index": leg.index,
            "step_index": first_step.step_index,
            "end_step_index": last_step.step_index,
            "start_way_point_index": first_step.way_points[0],
            "end_way_point_index": last_step.way_points[1],
            "route_distance_traveled_meters": _number(
                self._consumed_distance_meters
            ),
            "route_distance_remaining_meters": _number(
                self.remaining_distance_meters
            ),
            "leg_distance_remaining_meters": _number(
                leg.remaining_distance_meters
            ),
            "leg_duration_remaining_seconds": _number(
                leg.remaining_duration_seconds
            ),
        }
        return RouteChunk(requested, max(Decimal("0"), distance), metadata)


@dataclass
class _ScheduledEvent:
    event_type: EventType
    status: DutyStatus
    start: datetime
    end: datetime
    duration_seconds: Decimal
    distance_meters: Decimal
    location: str
    reason: str
    route_progress: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        data = {
            "type": self.event_type.value,
            "status": self.status.value,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "duration_seconds": _number(self.duration_seconds),
            "distance_meters": _number(self.distance_meters),
            "location": self.location,
            "reason": self.reason,
        }
        if self.route_progress is not None:
            data["route_progress"] = self.route_progress
        return data


@dataclass
class _Scheduler:
    progress: RouteProgress
    now: datetime
    cycle_used_seconds: Decimal
    start_datetime: datetime = field(init=False)
    duty_window_start: datetime | None = None
    daily_driving_seconds: Decimal = Decimal("0")
    driving_since_break_seconds: Decimal = Decimal("0")
    distance_since_fuel_meters: Decimal = Decimal("0")
    events: list[_ScheduledEvent] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.start_datetime = self.now

    def build(self) -> dict[str, Any]:
        iterations = 0
        while not self.progress.complete:
            iterations += 1
            if iterations > _MAX_SCHEDULING_ITERATIONS:
                raise HosPlanningError("Scheduling did not converge.")

            if self.progress.current_leg_complete:
                self._complete_leg()
                continue

            self._prepare_for_driving()
            self._drive_next_chunk()

        return self._result()

    @property
    def cycle_remaining_seconds(self) -> Decimal:
        return max(Decimal("0"), CYCLE_LIMIT_SECONDS - self.cycle_used_seconds)

    @property
    def daily_driving_remaining_seconds(self) -> Decimal:
        return max(
            Decimal("0"), DRIVING_LIMIT_SECONDS - self.daily_driving_seconds
        )

    @property
    def break_driving_remaining_seconds(self) -> Decimal:
        return max(
            Decimal("0"),
            BREAK_DRIVING_LIMIT_SECONDS - self.driving_since_break_seconds,
        )

    @property
    def duty_window_remaining_seconds(self) -> Decimal:
        if self.duty_window_start is None:
            return DUTY_WINDOW_SECONDS
        elapsed = _timedelta_seconds(self.now - self.duty_window_start)
        return max(Decimal("0"), DUTY_WINDOW_SECONDS - elapsed)

    def _complete_leg(self) -> None:
        leg_index = self.progress.current_leg_index
        if leg_index == 0:
            self._schedule_on_duty(
                EventType.PICKUP,
                SERVICE_STOP_SECONDS,
                "pickup_location",
                "one_hour_pickup_service",
            )
        elif leg_index == 1:
            self._schedule_on_duty(
                EventType.DROPOFF,
                SERVICE_STOP_SECONDS,
                "dropoff_location",
                "one_hour_dropoff_service",
            )
        else:
            raise HosPlanningError("Unexpected route leg index.")
        self.progress.advance_leg()

    def _prepare_for_driving(self) -> None:
        for _ in range(10):
            if self.cycle_remaining_seconds <= _EPSILON:
                self._schedule_cycle_restart()
                continue
            if (
                self.daily_driving_remaining_seconds <= _EPSILON
                or self.duty_window_remaining_seconds <= _EPSILON
            ):
                self._schedule_daily_rest()
                continue
            fuel_distance_remaining = max(
                Decimal("0"),
                FUEL_INTERVAL_METERS - self.distance_since_fuel_meters,
            )
            fuel_is_due = fuel_distance_remaining <= _EPSILON or (
                self.progress.time_until_distance(fuel_distance_remaining)
                <= _EPSILON
            )
            if fuel_is_due:
                if self.cycle_remaining_seconds < FUEL_DURATION_SECONDS - _EPSILON:
                    self._schedule_cycle_restart()
                else:
                    self._schedule_fuel()
                continue
            if self.break_driving_remaining_seconds <= _EPSILON:
                if self.cycle_remaining_seconds < BREAK_DURATION_SECONDS - _EPSILON:
                    self._schedule_cycle_restart()
                else:
                    self._schedule_break()
                continue
            return
        raise HosPlanningError("Unable to clear simultaneous HOS constraints.")

    def _drive_next_chunk(self) -> None:
        if self.duty_window_start is None:
            self.duty_window_start = self.now

        fuel_distance_remaining = max(
            Decimal("0"),
            FUEL_INTERVAL_METERS - self.distance_since_fuel_meters,
        )
        fuel_time_remaining = self.progress.time_until_distance(
            fuel_distance_remaining
        )
        duration = min(
            self.progress.remaining_current_leg_duration_seconds,
            self.daily_driving_remaining_seconds,
            self.duty_window_remaining_seconds,
            self.break_driving_remaining_seconds,
            self.cycle_remaining_seconds,
            fuel_time_remaining,
        )
        if duration <= _EPSILON:
            raise HosPlanningError("No positive driving interval is available.")

        leg = self.progress.current_leg
        chunk = self.progress.consume_time(duration)
        self._append_event(
            EventType.DRIVING,
            DutyStatus.DRIVING,
            chunk.duration_seconds,
            chunk.distance_meters,
            f"{leg.from_name}_to_{leg.to_name}",
            "route_progress",
            chunk.metadata,
        )
        self.daily_driving_seconds += chunk.duration_seconds
        self.driving_since_break_seconds += chunk.duration_seconds
        self.cycle_used_seconds += chunk.duration_seconds
        self.distance_since_fuel_meters += chunk.distance_meters

    def _schedule_on_duty(
        self,
        event_type: EventType,
        duration_seconds: Decimal,
        location: str,
        reason: str,
    ) -> None:
        remaining = duration_seconds
        while remaining > _EPSILON:
            if self.cycle_remaining_seconds <= _EPSILON:
                self._schedule_cycle_restart()

            take = min(remaining, self.cycle_remaining_seconds)
            if self.duty_window_start is None:
                self.duty_window_start = self.now
            self._append_event(
                event_type,
                DutyStatus.ON_DUTY_NOT_DRIVING,
                take,
                Decimal("0"),
                location,
                reason,
            )
            self.cycle_used_seconds += take
            if take >= BREAK_DURATION_SECONDS - _EPSILON:
                self.driving_since_break_seconds = Decimal("0")
            remaining -= take

    def _schedule_break(self) -> None:
        self._schedule_on_duty(
            EventType.BREAK,
            BREAK_DURATION_SECONDS,
            "en_route",
            "eight_hour_driving_break",
        )

    def _schedule_fuel(self) -> None:
        self._schedule_on_duty(
            EventType.FUEL,
            FUEL_DURATION_SECONDS,
            "en_route",
            "one_thousand_mile_fuel_interval",
        )
        self.distance_since_fuel_meters = Decimal("0")

    def _schedule_daily_rest(self) -> None:
        self._append_event(
            EventType.SLEEPER,
            DutyStatus.SLEEPER_BERTH,
            DAILY_REST_SECONDS,
            Decimal("0"),
            "en_route",
            "daily_driving_or_duty_limit",
        )
        self.daily_driving_seconds = Decimal("0")
        self.driving_since_break_seconds = Decimal("0")
        self.duty_window_start = None

    def _schedule_cycle_restart(self) -> None:
        self._append_event(
            EventType.CYCLE_RESTART,
            DutyStatus.SLEEPER_BERTH,
            CYCLE_RESTART_SECONDS,
            Decimal("0"),
            "en_route",
            "seventy_hour_cycle_exhausted",
        )
        self.cycle_used_seconds = Decimal("0")
        self.daily_driving_seconds = Decimal("0")
        self.driving_since_break_seconds = Decimal("0")
        self.duty_window_start = None

    def _append_event(
        self,
        event_type: EventType,
        status: DutyStatus,
        duration_seconds: Decimal,
        distance_meters: Decimal,
        location: str,
        reason: str,
        route_progress: dict[str, Any] | None = None,
    ) -> None:
        duration = _seconds(duration_seconds)
        start = self.now
        end = start + _seconds_timedelta(duration)
        self.events.append(
            _ScheduledEvent(
                event_type,
                status,
                start,
                end,
                duration,
                max(Decimal("0"), distance_meters),
                location,
                reason,
                route_progress,
            )
        )
        self.now = end

    def _result(self) -> dict[str, Any]:
        driving = _sum_event_duration(self.events, DutyStatus.DRIVING)
        on_duty = _sum_event_duration(
            self.events, DutyStatus.ON_DUTY_NOT_DRIVING
        )
        sleeper = _sum_event_duration(self.events, DutyStatus.SLEEPER_BERTH)
        distance = sum(
            (event.distance_meters for event in self.events), Decimal("0")
        )
        if abs(driving - self.progress.total_duration_seconds) > _EPSILON:
            raise HosPlanningError("Scheduled driving does not match route duration.")
        if abs(distance - self.progress.total_distance_meters) > Decimal("0.01"):
            raise HosPlanningError("Scheduled distance does not match route distance.")

        return {
            "summary": {
                "total_trip_distance_meters": _number(
                    self.progress.total_distance_meters
                ),
                "route_driving_seconds": _number(
                    self.progress.total_duration_seconds
                ),
                "scheduled_elapsed_seconds": _number(
                    _timedelta_seconds(self.now - self.start_datetime)
                ),
                "driving_seconds": _number(driving),
                "on_duty_not_driving_seconds": _number(on_duty),
                "sleeper_seconds": _number(sleeper),
                "fuel_stops": _count_events(self.events, EventType.FUEL),
                "breaks": _count_events(self.events, EventType.BREAK),
                "daily_rests": _count_events(self.events, EventType.SLEEPER),
                "cycle_restarts": _count_events(
                    self.events, EventType.CYCLE_RESTART
                ),
                "ending_cycle_used_hours": _number(
                    self.cycle_used_seconds / SECONDS_PER_HOUR
                ),
            },
            "events": [event.as_dict() for event in self.events],
        }


def build_hos_schedule(
    *,
    route: Mapping[str, Any],
    current_cycle_used_hours: int | float | Decimal,
    start_datetime: datetime,
) -> dict[str, Any]:
    """Build a deterministic schedule using the assessment's HOS assumptions.

    Only a current 70-hour-cycle total is available, so natural rolling
    eight-day recovery cannot be inferred. When that budget is exhausted,
    this planner uses a 34-hour restart so a long trip can be completed.
    """

    if start_datetime.tzinfo is None or start_datetime.utcoffset() is None:
        raise HosPlanningError("start_datetime must be timezone-aware.")

    cycle_hours = _measure(current_cycle_used_hours, "current cycle hours")
    if cycle_hours > Decimal("70"):
        raise HosPlanningError("Current cycle hours must be between 0 and 70.")

    scheduler = _Scheduler(
        progress=RouteProgress(route),
        now=start_datetime,
        cycle_used_seconds=cycle_hours * SECONDS_PER_HOUR,
    )
    return scheduler.build()


def _build_legs(
    value: Any,
    route_duration: Decimal,
    route_distance: Decimal,
) -> list[_LegProgress]:
    if not isinstance(value, list) or len(value) != len(_EXPECTED_LEGS):
        raise HosPlanningError("Route must contain exactly two legs.")

    raw_legs: list[tuple[Mapping[str, Any], Decimal, Decimal]] = []
    for index, leg in enumerate(value):
        if not isinstance(leg, Mapping):
            raise HosPlanningError("Route leg is malformed.")
        expected_from, expected_to = _EXPECTED_LEGS[index]
        if leg.get("from") != expected_from or leg.get("to") != expected_to:
            raise HosPlanningError("Route legs are not in the expected order.")
        raw_legs.append(
            (
                leg,
                _measure(leg.get("duration_seconds"), "leg duration"),
                _measure(leg.get("distance_meters"), "leg distance"),
            )
        )

    raw_duration_total = sum((item[1] for item in raw_legs), Decimal("0"))
    raw_distance_total = sum((item[2] for item in raw_legs), Decimal("0"))
    _validate_total(route_duration, raw_duration_total, "route duration")
    _validate_total(route_distance, raw_distance_total, "route distance")

    duration_scale = _scale(route_duration, raw_duration_total)
    distance_scale = _scale(route_distance, raw_distance_total)
    legs: list[_LegProgress] = []
    allocated_duration = Decimal("0")
    allocated_distance = Decimal("0")

    for index, (raw_leg, raw_duration, raw_distance) in enumerate(raw_legs):
        if index == len(raw_legs) - 1:
            leg_duration = route_duration - allocated_duration
            leg_distance = route_distance - allocated_distance
        else:
            leg_duration = raw_duration * duration_scale
            leg_distance = raw_distance * distance_scale
            allocated_duration += leg_duration
            allocated_distance += leg_distance

        steps = _build_steps(index, raw_leg.get("steps"), leg_duration, leg_distance)
        legs.append(
            _LegProgress(
                index=index,
                from_name=_EXPECTED_LEGS[index][0],
                to_name=_EXPECTED_LEGS[index][1],
                duration_seconds=leg_duration,
                distance_meters=leg_distance,
                steps=steps,
            )
        )

    return legs


def _build_steps(
    leg_index: int,
    value: Any,
    leg_duration: Decimal,
    leg_distance: Decimal,
) -> list[_StepProgress]:
    if not isinstance(value, list):
        raise HosPlanningError("Route steps are malformed.")

    parsed: list[tuple[int, Decimal, Decimal, tuple[int, int]]] = []
    for step_index, step in enumerate(value):
        if not isinstance(step, Mapping):
            raise HosPlanningError("Route step is malformed.")
        duration = _measure(step.get("duration_seconds"), "step duration")
        distance = _measure(step.get("distance_meters"), "step distance")
        way_points = _way_points(step.get("way_points"))
        if duration > _EPSILON:
            parsed.append((step_index, duration, distance, way_points))

    if leg_duration <= _EPSILON:
        if leg_distance > Decimal("0.01"):
            raise HosPlanningError("A zero-duration leg cannot have distance.")
        return []
    if not parsed:
        raise HosPlanningError("A driving leg must contain a timed route step.")

    raw_duration_total = sum((item[1] for item in parsed), Decimal("0"))
    positive_distance_total = sum((item[2] for item in parsed), Decimal("0"))
    duration_scale = leg_duration / raw_duration_total
    steps: list[_StepProgress] = []
    allocated_duration = Decimal("0")
    allocated_distance = Decimal("0")

    for position, (step_index, duration, distance, way_points) in enumerate(parsed):
        if position == len(parsed) - 1:
            normalized_duration = leg_duration - allocated_duration
            normalized_distance = leg_distance - allocated_distance
        else:
            normalized_duration = duration * duration_scale
            if positive_distance_total > _EPSILON:
                normalized_distance = leg_distance * distance / positive_distance_total
            else:
                normalized_distance = (
                    leg_distance * normalized_duration / leg_duration
                )
            allocated_duration += normalized_duration
            allocated_distance += normalized_distance

        steps.append(
            _StepProgress(
                leg_index=leg_index,
                step_index=step_index,
                duration_seconds=normalized_duration,
                distance_meters=normalized_distance,
                way_points=way_points,
            )
        )

    return steps


def _skip_completed_steps(leg: _LegProgress) -> None:
    while (
        leg.step_cursor < len(leg.steps)
        and leg.steps[leg.step_cursor].remaining_duration_seconds <= _EPSILON
    ):
        leg.step_cursor += 1


def _way_points(value: Any) -> tuple[int, int]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise HosPlanningError("Route step way_points are malformed.")
    start, end = value
    if (
        isinstance(start, bool)
        or isinstance(end, bool)
        or not isinstance(start, int)
        or not isinstance(end, int)
        or start < 0
        or end < start
    ):
        raise HosPlanningError("Route step way_points are malformed.")
    return start, end


def _measure(value: Any, name: str) -> Decimal:
    if isinstance(value, bool):
        raise HosPlanningError(f"{name} is malformed.")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise HosPlanningError(f"{name} is malformed.") from exc
    if not result.is_finite() or result < 0:
        raise HosPlanningError(f"{name} is malformed.")
    return result


def _seconds(value: Any) -> Decimal:
    return _measure(value, "duration").quantize(
        Decimal("0.000001"), rounding=ROUND_HALF_UP
    )


def _scale(expected: Decimal, actual: Decimal) -> Decimal:
    if actual <= _EPSILON:
        if expected <= _EPSILON:
            return Decimal("0")
        raise HosPlanningError("Route totals cannot be reconciled.")
    return expected / actual


def _validate_total(expected: Decimal, actual: Decimal, name: str) -> None:
    tolerance = max(Decimal("5"), expected * Decimal("0.001"))
    if abs(expected - actual) > tolerance:
        raise HosPlanningError(f"{name} does not match its legs.")


def _seconds_timedelta(seconds: Decimal) -> timedelta:
    microseconds = int(
        (seconds * Decimal("1000000")).to_integral_value(rounding=ROUND_HALF_UP)
    )
    return timedelta(microseconds=microseconds)


def _timedelta_seconds(value: timedelta) -> Decimal:
    return (
        Decimal(value.days * 86400 + value.seconds)
        + Decimal(value.microseconds) / Decimal("1000000")
    )


def _number(value: Decimal) -> int | float:
    if value == value.to_integral_value():
        return int(value)
    return float(value)


def _sum_event_duration(
    events: list[_ScheduledEvent], status: DutyStatus
) -> Decimal:
    return sum(
        (event.duration_seconds for event in events if event.status == status),
        Decimal("0"),
    )


def _count_events(events: list[_ScheduledEvent], event_type: EventType) -> int:
    return sum(event.event_type == event_type for event in events)
