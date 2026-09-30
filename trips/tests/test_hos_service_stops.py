from datetime import datetime, timezone

from trips.services.hos import build_hos_schedule
from trips.tests.factories import make_route

START = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)


def test_pickup_and_dropoff_are_ordered_on_duty_service_events():
    schedule = build_hos_schedule(
        route=make_route(
            leg_durations_seconds=(2 * 3600, 3 * 3600),
            leg_distances_meters=(100_000, 150_000),
        ),
        current_cycle_used_hours=0,
        start_datetime=START,
    )
    events = schedule["events"]
    pickup_index = next(
        index for index, event in enumerate(events) if event["type"] == "PICKUP"
    )
    dropoff_index = next(
        index for index, event in enumerate(events) if event["type"] == "DROPOFF"
    )

    assert events[pickup_index - 1]["type"] == "DRIVING"
    assert events[pickup_index - 1]["route_progress"][
        "leg_duration_remaining_seconds"
    ] == 0
    assert events[pickup_index + 1]["type"] == "DRIVING"
    assert events[pickup_index + 1]["route_progress"]["leg_index"] == 1
    assert dropoff_index == len(events) - 1
    assert events[dropoff_index - 1]["route_progress"][
        "leg_duration_remaining_seconds"
    ] == 0

    for event_type in ("PICKUP", "DROPOFF"):
        event = next(event for event in events if event["type"] == event_type)
        assert event["duration_seconds"] == 3600
        assert event["status"] == "ON_DUTY_NOT_DRIVING"
        assert event["distance_meters"] == 0


def test_pickup_and_dropoff_consume_cycle_but_not_driving_time():
    schedule = build_hos_schedule(
        route=make_route(
            leg_durations_seconds=(2 * 3600, 2 * 3600),
            leg_distances_meters=(50_000, 50_000),
        ),
        current_cycle_used_hours=10,
        start_datetime=START,
    )

    assert schedule["summary"]["driving_seconds"] == 4 * 3600
    assert schedule["summary"]["on_duty_not_driving_seconds"] == 2 * 3600
    assert schedule["summary"]["ending_cycle_used_hours"] == 16


def test_service_event_can_finish_at_duty_window_but_no_more_driving_starts():
    schedule = build_hos_schedule(
        route=make_route(
            leg_durations_seconds=(11 * 3600, 3600),
            leg_distances_meters=(200_000, 20_000),
        ),
        current_cycle_used_hours=0,
        start_datetime=START,
    )
    events = schedule["events"]
    pickup_index = next(
        index for index, event in enumerate(events) if event["type"] == "PICKUP"
    )
    next_driving_index = next(
        index
        for index, event in enumerate(events[pickup_index + 1 :], pickup_index + 1)
        if event["type"] == "DRIVING"
    )

    assert any(
        event["type"] == "SLEEPER"
        for event in events[pickup_index + 1 : next_driving_index]
    )
