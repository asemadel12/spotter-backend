from datetime import datetime, timezone

import pytest

from trips.services.hos import METERS_PER_MILE, build_hos_schedule
from trips.tests.factories import make_route

START = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)
FUEL_DISTANCE = 1000 * float(METERS_PER_MILE)


def build_for_miles(first_leg_miles, second_leg_miles, hours=(2, 2)):
    return build_hos_schedule(
        route=make_route(
            leg_durations_seconds=tuple(hour * 3600 for hour in hours),
            leg_distances_meters=(
                first_leg_miles * float(METERS_PER_MILE),
                second_leg_miles * float(METERS_PER_MILE),
            ),
            steps_per_leg=4,
        ),
        current_cycle_used_hours=0,
        start_datetime=START,
    )


def driving_distances_between_fuel_stops(events):
    intervals = []
    distance = 0
    for event in events:
        if event["type"] == "DRIVING":
            distance += event["distance_meters"]
        elif event["type"] == "FUEL":
            intervals.append(distance)
            distance = 0
    intervals.append(distance)
    return intervals


def test_route_under_one_thousand_miles_needs_no_fuel():
    schedule = build_for_miles(400, 599)

    assert schedule["summary"]["fuel_stops"] == 0
    assert not any(event["type"] == "FUEL" for event in schedule["events"])


def test_fuel_is_scheduled_before_exceeding_one_thousand_miles():
    schedule = build_for_miles(600, 600)
    fuel = next(event for event in schedule["events"] if event["type"] == "FUEL")
    fuel_index = schedule["events"].index(fuel)
    distance_before_fuel = sum(
        event["distance_meters"]
        for event in schedule["events"][:fuel_index]
        if event["type"] == "DRIVING"
    )

    assert distance_before_fuel == pytest.approx(FUEL_DISTANCE, abs=0.01)
    assert fuel["duration_seconds"] == 1800
    assert fuel["status"] == "ON_DUTY_NOT_DRIVING"


def test_very_long_route_schedules_multiple_fuel_stops():
    schedule = build_for_miles(1250, 1250, hours=(4, 4))

    assert schedule["summary"]["fuel_stops"] == 2
    assert [
        event["duration_seconds"]
        for event in schedule["events"]
        if event["type"] == "FUEL"
    ] == [1800, 1800]


def test_distance_between_fuel_resets_never_exceeds_limit():
    schedule = build_for_miles(1800, 1800, hours=(5, 5))

    intervals = driving_distances_between_fuel_stops(schedule["events"])
    assert len(intervals) == 4
    assert all(distance <= FUEL_DISTANCE + 0.01 for distance in intervals)


def test_fuel_consumes_cycle_hours_and_resets_break_clock():
    schedule = build_for_miles(600, 600, hours=(4, 4))

    assert schedule["summary"]["fuel_stops"] == 1
    assert schedule["summary"]["breaks"] == 0
    assert schedule["summary"]["ending_cycle_used_hours"] == 10.5


def test_no_fuel_is_added_when_trip_finishes_at_threshold():
    schedule = build_for_miles(500, 500)

    assert schedule["summary"]["fuel_stops"] == 0
    assert schedule["events"][-1]["type"] == "DROPOFF"
