from datetime import datetime, timezone
from decimal import Decimal

import pytest

from trips.services.hos import (
    HosPlanningError,
    RouteProgress,
    build_hos_schedule,
)
from trips.tests.factories import make_route

START = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)


def test_short_route_has_complete_chronological_schedule():
    route = make_route(
        leg_durations_seconds=(3600, 5400),
        leg_distances_meters=(100_000, 150_000),
    )

    schedule = build_hos_schedule(
        route=route,
        current_cycle_used_hours=0,
        start_datetime=START,
    )

    assert schedule["summary"]["route_driving_seconds"] == 9000
    assert schedule["summary"]["driving_seconds"] == 9000
    assert schedule["summary"]["total_trip_distance_meters"] == 250_000
    assert schedule["summary"]["breaks"] == 0

    events = schedule["events"]
    for previous, current in zip(events, events[1:]):
        assert datetime.fromisoformat(previous["end"]) <= datetime.fromisoformat(
            current["start"]
        )
    assert all(
        datetime.fromisoformat(event["start"]).utcoffset() is not None
        for event in events
    )


def test_partial_route_progress_interpolates_distance_and_preserves_metadata():
    route = make_route(
        leg_durations_seconds=(14_400, 3600),
        leg_distances_meters=(400_000, 100_000),
        steps_per_leg=2,
    )
    progress = RouteProgress(route)

    chunk = progress.consume_time(Decimal("3600"))

    assert chunk.duration_seconds == Decimal("3600")
    assert chunk.distance_meters == Decimal("100000")
    assert progress.remaining_current_leg_duration_seconds == Decimal("10800")
    assert progress.remaining_distance_meters == Decimal("400000")
    assert chunk.metadata["leg_index"] == 0
    assert chunk.metadata["step_index"] == 0
    assert chunk.metadata["start_way_point_index"] == 0
    assert chunk.metadata["end_way_point_index"] == 1
    assert chunk.metadata["route_distance_traveled_meters"] == 100_000


def test_progress_can_cross_steps_but_not_a_leg_boundary():
    route = make_route(
        leg_durations_seconds=(7200, 3600),
        leg_distances_meters=(200_000, 100_000),
        steps_per_leg=2,
    )
    progress = RouteProgress(route)

    chunk = progress.consume_time(Decimal("5400"))

    assert chunk.metadata["step_index"] == 0
    assert chunk.metadata["end_step_index"] == 1
    assert chunk.distance_meters == Decimal("150000")
    with pytest.raises(HosPlanningError):
        progress.consume_time(Decimal("3600"))


def test_zero_duration_step_is_skipped_without_stalling():
    route = make_route(
        leg_durations_seconds=(3600, 3600),
        include_zero_step=True,
    )

    schedule = build_hos_schedule(
        route=route,
        current_cycle_used_hours=0,
        start_datetime=START,
    )

    driving_events = [
        event for event in schedule["events"] if event["type"] == "DRIVING"
    ]
    assert sum(event["duration_seconds"] for event in driving_events) == 7200
    assert all(event["duration_seconds"] > 0 for event in driving_events)


def test_zero_distance_and_duration_route_still_schedules_service_stops():
    route = make_route(
        leg_durations_seconds=(0, 0),
        leg_distances_meters=(0, 0),
    )

    schedule = build_hos_schedule(
        route=route,
        current_cycle_used_hours=0,
        start_datetime=START,
    )

    assert [event["type"] for event in schedule["events"]] == [
        "PICKUP",
        "DROPOFF",
    ]
    assert schedule["summary"]["driving_seconds"] == 0
    assert schedule["summary"]["total_trip_distance_meters"] == 0


def test_timezone_aware_start_is_accepted_and_naive_start_is_rejected():
    route = make_route()

    build_hos_schedule(
        route=route,
        current_cycle_used_hours=0,
        start_datetime=START,
    )

    with pytest.raises(HosPlanningError, match="timezone-aware"):
        build_hos_schedule(
            route=route,
            current_cycle_used_hours=0,
            start_datetime=START.replace(tzinfo=None),
        )


def test_summary_totals_are_derived_from_events_without_negative_rounding():
    route = make_route(
        leg_durations_seconds=(10_000.1, 12_000.2),
        leg_distances_meters=(123_456.7, 234_567.8),
        steps_per_leg=3,
    )
    schedule = build_hos_schedule(
        route=route,
        current_cycle_used_hours=3.25,
        start_datetime=START,
    )

    events = schedule["events"]
    assert all(event["duration_seconds"] >= 0 for event in events)
    assert all(event["distance_meters"] >= 0 for event in events)
    assert schedule["summary"]["driving_seconds"] == pytest.approx(
        sum(
            event["duration_seconds"]
            for event in events
            if event["status"] == "DRIVING"
        )
    )
    assert schedule["summary"]["on_duty_not_driving_seconds"] == pytest.approx(
        sum(
            event["duration_seconds"]
            for event in events
            if event["status"] == "ON_DUTY_NOT_DRIVING"
        )
    )
    assert schedule["summary"]["sleeper_seconds"] == pytest.approx(
        sum(
            event["duration_seconds"]
            for event in events
            if event["status"] == "SLEEPER_BERTH"
        )
    )
    assert schedule["summary"]["total_trip_distance_meters"] == pytest.approx(
        sum(event["distance_meters"] for event in events)
    )
    assert schedule["summary"]["scheduled_elapsed_seconds"] == pytest.approx(
        sum(event["duration_seconds"] for event in events)
    )
