from datetime import datetime, timezone

import pytest

from trips.services.hos import METERS_PER_MILE, build_hos_schedule
from trips.tests.factories import make_route

START = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)
CYCLE_SECONDS = 70 * 3600


def assert_cycle_never_exceeded(events, initial_hours):
    used = initial_hours * 3600
    for event in events:
        if event["type"] == "CYCLE_RESTART":
            assert used <= CYCLE_SECONDS
            used = 0
        elif event["status"] in {"DRIVING", "ON_DUTY_NOT_DRIVING"}:
            used += event["duration_seconds"]
            assert used <= CYCLE_SECONDS
    return used


def test_zero_current_cycle_usage_works():
    schedule = build_hos_schedule(
        route=make_route(),
        current_cycle_used_hours=0,
        start_datetime=START,
    )

    assert schedule["summary"]["cycle_restarts"] == 0
    assert schedule["summary"]["ending_cycle_used_hours"] == 4


def test_cycle_close_to_seventy_restricts_initial_driving():
    schedule = build_hos_schedule(
        route=make_route(leg_durations_seconds=(2 * 3600, 2 * 3600)),
        current_cycle_used_hours=69.5,
        start_datetime=START,
    )

    assert schedule["events"][0]["type"] == "DRIVING"
    assert schedule["events"][0]["duration_seconds"] == 1800
    assert schedule["events"][1]["type"] == "CYCLE_RESTART"
    assert_cycle_never_exceeded(schedule["events"], 69.5)


def test_cycle_restart_is_scheduled_immediately_when_starting_at_seventy():
    schedule = build_hos_schedule(
        route=make_route(),
        current_cycle_used_hours=70,
        start_datetime=START,
    )

    assert schedule["events"][0]["type"] == "CYCLE_RESTART"
    assert schedule["events"][0]["duration_seconds"] == 34 * 3600
    assert schedule["events"][0]["status"] == "SLEEPER_BERTH"
    assert schedule["summary"]["cycle_restarts"] == 1


def test_pickup_is_split_safely_when_remaining_cycle_is_insufficient():
    schedule = build_hos_schedule(
        route=make_route(
            leg_durations_seconds=(45 * 60, 3600),
            leg_distances_meters=(20_000, 20_000),
        ),
        current_cycle_used_hours=69,
        start_datetime=START,
    )
    events = schedule["events"]
    pickup_events = [event for event in events if event["type"] == "PICKUP"]

    assert [event["duration_seconds"] for event in pickup_events] == [900, 2700]
    assert any(event["type"] == "CYCLE_RESTART" for event in events)
    assert sum(event["duration_seconds"] for event in pickup_events) == 3600
    assert_cycle_never_exceeded(events, 69)


def test_fuel_and_service_events_never_push_cycle_over_seventy():
    meters = float(METERS_PER_MILE)
    schedule = build_hos_schedule(
        route=make_route(
            leg_durations_seconds=(1800, 3600),
            leg_distances_meters=(1000 * meters, 100 * meters),
            steps_per_leg=2,
        ),
        current_cycle_used_hours=69,
        start_datetime=START,
    )

    assert any(event["type"] == "FUEL" for event in schedule["events"])
    assert any(event["type"] == "CYCLE_RESTART" for event in schedule["events"])
    assert_cycle_never_exceeded(schedule["events"], 69)


def test_restart_resets_cycle_and_daily_clocks():
    schedule = build_hos_schedule(
        route=make_route(
            leg_durations_seconds=(2 * 3600, 10 * 3600),
            leg_distances_meters=(20_000, 100_000),
        ),
        current_cycle_used_hours=69,
        start_datetime=START,
    )
    events = schedule["events"]
    restart_index = next(
        index
        for index, event in enumerate(events)
        if event["type"] == "CYCLE_RESTART"
    )
    driving_after_restart = sum(
        event["duration_seconds"]
        for event in events[restart_index + 1 :]
        if event["type"] == "DRIVING"
    )

    assert events[restart_index]["duration_seconds"] == 34 * 3600
    assert driving_after_restart > 8 * 3600
    # Eleven driving hours, pickup/dropoff, and one on-duty break consume cycle.
    assert schedule["summary"]["ending_cycle_used_hours"] == pytest.approx(13.5)


def test_artificially_long_trip_supports_multiple_cycle_restarts():
    schedule = build_hos_schedule(
        route=make_route(
            leg_durations_seconds=(75 * 3600, 75 * 3600),
            leg_distances_meters=(100_000, 100_000),
            steps_per_leg=10,
        ),
        current_cycle_used_hours=0,
        start_datetime=START,
    )

    assert schedule["summary"]["cycle_restarts"] >= 2
    assert schedule["summary"]["driving_seconds"] == 150 * 3600
    assert_cycle_never_exceeded(schedule["events"], 0)
