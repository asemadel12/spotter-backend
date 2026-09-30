from datetime import datetime, timezone

from trips.services.hos import build_hos_schedule
from trips.tests.factories import make_route

START = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)
ELEVEN_HOURS = 11 * 3600


def build_long_schedule(hours_by_leg=(10, 4)):
    return build_hos_schedule(
        route=make_route(
            leg_durations_seconds=tuple(hours * 3600 for hours in hours_by_leg),
            leg_distances_meters=(300_000, 120_000),
            steps_per_leg=2,
        ),
        current_cycle_used_hours=0,
        start_datetime=START,
    )


def driving_totals_by_daily_period(events):
    totals = []
    current = 0
    for event in events:
        if event["type"] == "DRIVING":
            current += event["duration_seconds"]
        elif event["type"] in {"SLEEPER", "CYCLE_RESTART"}:
            totals.append(current)
            current = 0
    totals.append(current)
    return totals


def test_more_than_eleven_hours_requires_ten_hour_sleeper_rest():
    schedule = build_long_schedule()
    sleepers = [
        event for event in schedule["events"] if event["type"] == "SLEEPER"
    ]

    assert sleepers
    assert all(event["duration_seconds"] == 10 * 3600 for event in sleepers)
    assert all(event["status"] == "SLEEPER_BERTH" for event in sleepers)


def test_driver_never_exceeds_eleven_hours_in_a_daily_period():
    schedule = build_long_schedule((20, 20))

    totals = driving_totals_by_daily_period(schedule["events"])
    assert max(totals) <= ELEVEN_HOURS
    assert sum(totals) == 40 * 3600


def test_driving_clock_resets_after_qualifying_sleeper_rest():
    schedule = build_long_schedule()
    events = schedule["events"]
    sleeper_index = next(
        index for index, event in enumerate(events) if event["type"] == "SLEEPER"
    )

    driving_before = sum(
        event["duration_seconds"]
        for event in events[:sleeper_index]
        if event["type"] == "DRIVING"
    )
    driving_after = sum(
        event["duration_seconds"]
        for event in events[sleeper_index + 1 :]
        if event["type"] == "DRIVING"
    )
    assert driving_before == ELEVEN_HOURS
    assert driving_after == 3 * 3600


def test_pickup_and_dropoff_do_not_consume_driving_allowance():
    schedule = build_long_schedule((6, 5))

    assert schedule["summary"]["driving_seconds"] == ELEVEN_HOURS
    assert schedule["summary"]["daily_rests"] == 0
    assert sum(
        event["duration_seconds"]
        for event in schedule["events"]
        if event["type"] in {"PICKUP", "DROPOFF"}
    ) == 2 * 3600
