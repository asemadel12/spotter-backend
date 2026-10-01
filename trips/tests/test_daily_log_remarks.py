from datetime import datetime, timedelta, timezone

from trips.services.daily_logs import build_daily_logs
from trips.tests.factories import make_schedule, make_schedule_event

UTC = timezone.utc


def test_meaningful_events_create_location_safe_remarks_with_route_progress():
    start = datetime(2026, 1, 1, 8, tzinfo=UTC)
    cursor = start
    events = []

    def add(
        event_type,
        status,
        duration,
        *,
        distance=0,
        location="en_route",
        route_progress=None,
    ):
        nonlocal cursor
        event = make_schedule_event(
            event_type,
            status,
            cursor,
            cursor + duration,
            distance_meters=distance,
            location=location,
            reason=f"{event_type.lower()}_reason",
            route_progress=route_progress,
        )
        events.append(event)
        cursor += duration

    add(
        "DRIVING",
        "DRIVING",
        timedelta(hours=1),
        distance=100_000,
        location="current_location_to_pickup_location",
        route_progress={
            "route_distance_traveled_meters": 100_000,
            "route_distance_remaining_meters": 100_000,
            "leg_index": 0,
            "step_index": 0,
        },
    )
    add(
        "PICKUP",
        "ON_DUTY_NOT_DRIVING",
        timedelta(hours=1),
        location="pickup_location",
    )
    add(
        "DRIVING",
        "DRIVING",
        timedelta(hours=1),
        distance=100_000,
        route_progress={
            "route_distance_traveled_meters": 200_000,
            "route_distance_remaining_meters": 0,
            "leg_index": 1,
            "step_index": 0,
        },
    )
    add("FUEL", "ON_DUTY_NOT_DRIVING", timedelta(minutes=30))
    add("BREAK", "ON_DUTY_NOT_DRIVING", timedelta(minutes=30))
    add("SLEEPER", "SLEEPER_BERTH", timedelta(hours=10))
    add("CYCLE_RESTART", "SLEEPER_BERTH", timedelta(hours=34))
    add(
        "DROPOFF",
        "ON_DUTY_NOT_DRIVING",
        timedelta(hours=1),
        location="dropoff_location",
    )
    locations = {
        "current_location": {"label": "Chicago, Illinois, USA"},
        "pickup_location": {"label": "Indianapolis, Indiana, USA"},
        "dropoff_location": {"label": "Dallas, Texas, USA"},
    }

    result = build_daily_logs(
        schedule=make_schedule(events),
        locations=locations,
    )
    remarks = [remark for log in result["logs"] for remark in log["remarks"]]
    remarks_by_type = {}
    for remark in remarks:
        remarks_by_type.setdefault(remark["event_type"], []).append(remark)

    for event_type in (
        "DRIVING",
        "PICKUP",
        "DROPOFF",
        "FUEL",
        "BREAK",
        "SLEEPER",
        "CYCLE_RESTART",
    ):
        assert event_type in remarks_by_type

    assert remarks_by_type["DRIVING"][0]["location"] == {
        "ref": "current_location",
        "label": "Chicago, Illinois, USA",
    }
    assert remarks_by_type["PICKUP"][0]["location"] == {
        "ref": "pickup_location",
        "label": "Indianapolis, Indiana, USA",
    }
    assert remarks_by_type["DROPOFF"][0]["location"] == {
        "ref": "dropoff_location",
        "label": "Dallas, Texas, USA",
    }
    assert remarks_by_type["FUEL"][0]["location"] == {
        "ref": "en_route",
        "label": "En route",
    }
    assert remarks_by_type["FUEL"][0]["route_distance_traveled_meters"] == 200_000
    assert remarks_by_type["PICKUP"][0][
        "route_distance_traveled_meters"
    ] == 100_000


def test_missing_location_labels_are_not_invented():
    start = datetime(2026, 1, 1, 8, tzinfo=UTC)
    event = make_schedule_event(
        "FUEL",
        "ON_DUTY_NOT_DRIVING",
        start,
        start + timedelta(minutes=30),
        location="en_route",
    )

    remark = build_daily_logs(schedule=make_schedule([event]))["logs"][0][
        "remarks"
    ][0]

    assert remark["location"] == {"ref": "en_route", "label": "En route"}


def test_first_driving_remark_clamps_tiny_negative_route_progress_to_zero():
    start = datetime(2026, 1, 1, 8, tzinfo=UTC)
    schedule = make_schedule(
        [
            make_schedule_event(
                "DRIVING",
                "DRIVING",
                start,
                start + timedelta(hours=1),
                distance_meters=100,
                location="current_location_to_pickup_location",
                route_progress={
                    "route_distance_traveled_meters": 99.999999999999,
                    "route_distance_remaining_meters": 900,
                },
            )
        ]
    )

    result = build_daily_logs(
        schedule=schedule,
        locations={
            "current_location": {
                "label": "Chicago, Illinois, USA",
            }
        },
    )
    remark = result["logs"][0]["remarks"][0]

    assert remark["route_distance_traveled_meters"] == 0
    assert remark["location"] == {
        "ref": "current_location",
        "label": "Chicago, Illinois, USA",
    }



def test_resolved_route_location_label_is_used_for_fmcsa_remark():
    start = datetime(2026, 1, 1, 8, tzinfo=UTC)
    event = make_schedule_event(
        "BREAK",
        "ON_DUTY_NOT_DRIVING",
        start,
        start + timedelta(minutes=30),
        location="en_route",
    )
    event["location_label"] = "Amarillo, TX"

    result = build_daily_logs(schedule=make_schedule([event]))
    log = result["logs"][0]

    assert log["remarks"][0]["location"] == {
        "ref": "en_route",
        "label": "Amarillo, TX",
    }
    assert log["events"][0]["location_label"] == "Amarillo, TX"



def test_known_location_remarks_prefer_city_state_over_full_label():
    start = datetime(2026, 1, 1, 8, tzinfo=UTC)
    event = make_schedule_event(
        "PICKUP",
        "ON_DUTY_NOT_DRIVING",
        start,
        start + timedelta(hours=1),
        location="pickup_location",
    )

    result = build_daily_logs(
        schedule=make_schedule([event]),
        locations={
            "pickup_location": {
                "label": "Dallas, Dallas County, Texas, USA",
                "city_state": "Dallas, TX",
            }
        },
    )

    assert result["logs"][0]["remarks"][0]["location"] == {
        "ref": "pickup_location",
        "label": "Dallas, TX",
    }
