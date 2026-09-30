from datetime import datetime, timezone

from trips.services.hos import METERS_PER_MILE, build_hos_schedule
from trips.tests.factories import make_route

START = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)
EIGHT_HOURS = 8 * 3600


def schedule_for(route):
    return build_hos_schedule(
        route=route,
        current_cycle_used_hours=0,
        start_datetime=START,
    )


def assert_never_drives_over_eight_hours_without_qualifying_stop(events):
    driving_since_break = 0
    for event in events:
        if event["status"] == "DRIVING":
            driving_since_break += event["duration_seconds"]
            assert driving_since_break <= EIGHT_HOURS
        elif event["duration_seconds"] >= 1800:
            driving_since_break = 0


def test_route_below_eight_driving_hours_has_no_mandatory_break():
    schedule = schedule_for(
        make_route(leg_durations_seconds=(3 * 3600, 4 * 3600))
    )

    assert schedule["summary"]["breaks"] == 0


def test_route_over_eight_hours_inserts_exact_thirty_minute_break():
    schedule = schedule_for(
        make_route(leg_durations_seconds=(9 * 3600, 3600))
    )
    breaks = [event for event in schedule["events"] if event["type"] == "BREAK"]

    assert breaks
    assert all(event["duration_seconds"] == 1800 for event in breaks)
    assert all(event["status"] == "ON_DUTY_NOT_DRIVING" for event in breaks)
    assert_never_drives_over_eight_hours_without_qualifying_stop(schedule["events"])


def test_break_resets_driving_since_break_clock():
    schedule = schedule_for(
        make_route(leg_durations_seconds=(10 * 3600, 3600))
    )
    break_index = next(
        index
        for index, event in enumerate(schedule["events"])
        if event["type"] == "BREAK"
    )
    driving_before = sum(
        event["duration_seconds"]
        for event in schedule["events"][:break_index]
        if event["type"] == "DRIVING"
    )
    first_drive_after = next(
        event
        for event in schedule["events"][break_index + 1 :]
        if event["type"] == "DRIVING"
    )

    assert driving_before == EIGHT_HOURS
    assert first_drive_after["duration_seconds"] > 0
    assert_never_drives_over_eight_hours_without_qualifying_stop(schedule["events"])


def test_one_hour_pickup_satisfies_break_at_eight_hour_boundary():
    schedule = schedule_for(
        make_route(leg_durations_seconds=(8 * 3600, 3600))
    )

    event_types = [event["type"] for event in schedule["events"]]
    assert "BREAK" not in event_types
    assert event_types[:3] == ["DRIVING", "PICKUP", "DRIVING"]
    assert_never_drives_over_eight_hours_without_qualifying_stop(schedule["events"])


def test_dropoff_satisfies_break_when_trip_finishes_at_eight_hours():
    schedule = schedule_for(
        make_route(leg_durations_seconds=(3600, 8 * 3600))
    )

    assert schedule["events"][-1]["type"] == "DROPOFF"
    assert schedule["events"][-1]["duration_seconds"] == 3600
    assert not any(event["type"] == "BREAK" for event in schedule["events"])
    assert_never_drives_over_eight_hours_without_qualifying_stop(schedule["events"])


def test_fuel_stop_resets_break_clock_and_avoids_redundant_break():
    miles = float(METERS_PER_MILE)
    schedule = schedule_for(
        make_route(
            leg_durations_seconds=(9 * 3600, 1800),
            leg_distances_meters=(1125 * miles, 10 * miles),
            steps_per_leg=3,
        )
    )

    fuel_index = next(
        index
        for index, event in enumerate(schedule["events"])
        if event["type"] == "FUEL"
    )
    assert schedule["events"][fuel_index]["duration_seconds"] == 1800
    assert not any(event["type"] == "BREAK" for event in schedule["events"])
    assert_never_drives_over_eight_hours_without_qualifying_stop(schedule["events"])
    adjacent_types = {
        schedule["events"][index]["type"]
        for index in (fuel_index - 1, fuel_index + 1)
    }
    assert "BREAK" not in adjacent_types
