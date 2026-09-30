from datetime import datetime, timedelta, timezone

import pytest

from trips.services.daily_logs import METERS_PER_MILE, build_daily_logs
from trips.services.hos import build_hos_schedule
from trips.tests.factories import make_route, make_schedule, make_schedule_event

UTC = timezone.utc


def test_daily_totals_equal_segment_derived_totals():
    start = datetime(2026, 1, 1, 6, tzinfo=UTC)
    events = [
        make_schedule_event(
            "DRIVING", "DRIVING", start, start + timedelta(hours=2), distance_meters=100
        ),
        make_schedule_event(
            "BREAK",
            "ON_DUTY_NOT_DRIVING",
            start + timedelta(hours=2),
            start + timedelta(hours=2, minutes=30),
        ),
        make_schedule_event(
            "SLEEPER",
            "SLEEPER_BERTH",
            start + timedelta(hours=2, minutes=30),
            start + timedelta(hours=12, minutes=30),
        ),
    ]

    log = build_daily_logs(schedule=make_schedule(events))["logs"][0]

    key_by_status = {
        "OFF_DUTY": "off_duty_seconds",
        "SLEEPER_BERTH": "sleeper_berth_seconds",
        "DRIVING": "driving_seconds",
        "ON_DUTY_NOT_DRIVING": "on_duty_not_driving_seconds",
    }
    for status, total_key in key_by_status.items():
        assert log["totals"][total_key] == sum(
            segment["duration_seconds"]
            for segment in log["segments"]
            if segment["status"] == status
        )
    assert sum(log["totals"][key] for key in key_by_status.values()) == 86_400
    assert log["totals"]["total_seconds"] == 86_400


def test_daily_distance_uses_only_driving_events_and_converts_to_miles():
    start = datetime(2026, 1, 1, 8, tzinfo=UTC)
    one_hundred_miles = 100 * float(METERS_PER_MILE)
    events = [
        make_schedule_event(
            "DRIVING",
            "DRIVING",
            start,
            start + timedelta(hours=2),
            distance_meters=one_hundred_miles,
        ),
        make_schedule_event(
            "PICKUP",
            "ON_DUTY_NOT_DRIVING",
            start + timedelta(hours=2),
            start + timedelta(hours=3),
            distance_meters=0,
        ),
    ]

    result = build_daily_logs(schedule=make_schedule(events))
    log = result["logs"][0]

    assert log["driving_distance_meters"] == pytest.approx(one_hundred_miles)
    assert log["driving_distance_miles"] == pytest.approx(100)
    assert result["summary"]["total_driving_distance_miles"] == pytest.approx(100)


def test_segments_obey_graph_invariants_and_status_changes():
    start = datetime(2026, 1, 1, 8, tzinfo=UTC)
    events = [
        make_schedule_event(
            "DRIVING", "DRIVING", start, start + timedelta(hours=1), distance_meters=10
        ),
        make_schedule_event(
            "PICKUP",
            "ON_DUTY_NOT_DRIVING",
            start + timedelta(hours=1),
            start + timedelta(hours=2),
        ),
    ]
    segments = build_daily_logs(schedule=make_schedule(events))["logs"][0][
        "segments"
    ]

    assert segments[0]["start_second"] == 0
    assert segments[-1]["end_second"] == 86_400
    assert all(
        0 <= segment["start_second"] < segment["end_second"] <= 86_400
        for segment in segments
    )
    assert all(segment["status"] in {
        "OFF_DUTY",
        "SLEEPER_BERTH",
        "DRIVING",
        "ON_DUTY_NOT_DRIVING",
    } for segment in segments)
    assert all(
        previous["end_second"] == current["start_second"]
        for previous, current in zip(segments, segments[1:])
    )
    assert segments[1]["status"] == "DRIVING"
    assert segments[1]["start_second"] == 8 * 3600
    assert segments[2]["status"] == "ON_DUTY_NOT_DRIVING"
    assert segments[2]["start_second"] == 9 * 3600


def test_real_hos_schedule_generates_consecutive_complete_daily_logs():
    route = make_route(
        leg_durations_seconds=(10 * 3600, 10 * 3600),
        leg_distances_meters=(500_000, 700_000),
        steps_per_leg=3,
    )
    schedule = build_hos_schedule(
        route=route,
        current_cycle_used_hours=0,
        start_datetime=datetime(2026, 1, 1, 20, tzinfo=UTC),
    )

    result = build_daily_logs(schedule=schedule)

    assert result["summary"]["log_count"] > 1
    dates = [datetime.fromisoformat(log["date"]).date() for log in result["logs"]]
    assert all(
        current - previous == timedelta(days=1)
        for previous, current in zip(dates, dates[1:])
    )
    assert all(log["totals"]["total_seconds"] == 86_400 for log in result["logs"])
    assert sum(log["driving_distance_meters"] for log in result["logs"]) == pytest.approx(
        route["distance_meters"], abs=0.01
    )
    hos_statuses = {event["status"] for event in schedule["events"]}
    daily_statuses = {
        event["status"] for log in result["logs"] for event in log["events"]
    }
    assert daily_statuses == hos_statuses
