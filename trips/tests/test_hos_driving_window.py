from datetime import datetime, timedelta, timezone

from trips.services.hos import METERS_PER_MILE, build_hos_schedule
from trips.tests.factories import make_route

START = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)


def build(route):
    return build_hos_schedule(
        route=route,
        current_cycle_used_hours=0,
        start_datetime=START,
    )


def test_pickup_consumes_duty_window_and_shrinks_remaining_time():
    schedule = build(
        make_route(
            leg_durations_seconds=(8 * 3600, 5 * 3600),
            leg_distances_meters=(200_000, 125_000),
        )
    )
    events = schedule["events"]
    pickup = next(event for event in events if event["type"] == "PICKUP")
    sleeper = next(event for event in events if event["type"] == "SLEEPER")

    assert pickup["duration_seconds"] == 3600
    assert datetime.fromisoformat(sleeper["start"]) - START == timedelta(hours=12)


def test_thirty_minute_break_consumes_duty_window():
    schedule = build(
        make_route(
            leg_durations_seconds=(9 * 3600, 4 * 3600),
            leg_distances_meters=(180_000, 80_000),
        )
    )
    events = schedule["events"]
    sleeper = next(event for event in events if event["type"] == "SLEEPER")

    assert any(event["type"] == "BREAK" for event in events)
    assert datetime.fromisoformat(sleeper["start"]) - START == timedelta(
        hours=12, minutes=30
    )


def test_fourteen_hour_window_stops_driving_until_ten_hour_rest():
    meters = float(METERS_PER_MILE)
    schedule = build(
        make_route(
            leg_durations_seconds=(5 * 3600, 5 * 3600),
            leg_distances_meters=(4000 * meters, 4000 * meters),
            steps_per_leg=4,
        )
    )
    events = schedule["events"]
    sleeper_index = next(
        index for index, event in enumerate(events) if event["type"] == "SLEEPER"
    )
    sleeper = events[sleeper_index]

    assert datetime.fromisoformat(sleeper["start"]) - START == timedelta(hours=14)
    assert sleeper["duration_seconds"] == 10 * 3600
    assert any(event["type"] == "DRIVING" for event in events[sleeper_index + 1 :])


def test_no_driving_extends_past_a_daily_fourteen_hour_window():
    meters = float(METERS_PER_MILE)
    schedule = build(
        make_route(
            leg_durations_seconds=(10 * 3600, 10 * 3600),
            leg_distances_meters=(7000 * meters, 7000 * meters),
            steps_per_leg=5,
        )
    )

    duty_start = None
    for event in schedule["events"]:
        start = datetime.fromisoformat(event["start"])
        end = datetime.fromisoformat(event["end"])
        if event["type"] in {"SLEEPER", "CYCLE_RESTART"}:
            duty_start = None
            continue
        if duty_start is None:
            duty_start = start
        if event["type"] == "DRIVING":
            assert end <= duty_start + timedelta(hours=14)
