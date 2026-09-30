from datetime import datetime, timedelta, timezone

import pytest

from trips.services.daily_logs import build_daily_logs
from trips.tests.factories import make_schedule, make_schedule_event

UTC = timezone.utc


def test_ten_hour_sleeper_crossing_midnight_is_split():
    start = datetime(2026, 1, 1, 22, tzinfo=UTC)
    event = make_schedule_event(
        "SLEEPER", "SLEEPER_BERTH", start, start + timedelta(hours=10)
    )

    result = build_daily_logs(schedule=make_schedule([event]))

    assert result["summary"]["log_count"] == 2
    assert result["logs"][0]["events"][0]["duration_seconds"] == 2 * 3600
    assert result["logs"][1]["events"][0]["duration_seconds"] == 8 * 3600
    assert sum(
        log["totals"]["sleeper_berth_seconds"] for log in result["logs"]
    ) == 10 * 3600


def test_thirty_four_hour_restart_is_split_across_three_dates():
    start = datetime(2026, 1, 1, 20, tzinfo=UTC)
    event = make_schedule_event(
        "CYCLE_RESTART",
        "SLEEPER_BERTH",
        start,
        start + timedelta(hours=34),
    )

    result = build_daily_logs(schedule=make_schedule([event]))

    assert [log["date"] for log in result["logs"]] == [
        "2026-01-01",
        "2026-01-02",
        "2026-01-03",
    ]
    assert [log["events"][0]["duration_seconds"] for log in result["logs"]] == [
        4 * 3600,
        24 * 3600,
        6 * 3600,
    ]


def test_driving_crossing_midnight_splits_distance_proportionally():
    start = datetime(2026, 1, 1, 23, tzinfo=UTC)
    event = make_schedule_event(
        "DRIVING",
        "DRIVING",
        start,
        start + timedelta(hours=2),
        distance_meters=160_000,
        route_progress={
            "leg_index": 0,
            "step_index": 1,
            "route_distance_traveled_meters": 200_000,
            "route_distance_remaining_meters": 300_000,
        },
    )

    result = build_daily_logs(schedule=make_schedule([event]))
    fragments = [log["events"][0] for log in result["logs"]]

    assert [fragment["distance_meters"] for fragment in fragments] == [
        80_000,
        80_000,
    ]
    assert sum(fragment["duration_seconds"] for fragment in fragments) == 7200
    assert sum(fragment["distance_meters"] for fragment in fragments) == 160_000
    assert fragments[0]["route_progress"]["leg_index"] == 0
    assert fragments[0]["route_progress"]["step_index"] == 1
    assert fragments[0]["route_progress"][
        "route_distance_traveled_meters"
    ] == 120_000
    assert fragments[1]["route_progress"][
        "route_distance_traveled_meters"
    ] == 200_000


def test_event_ending_exactly_at_midnight_does_not_create_extra_log():
    start = datetime(2026, 1, 1, 22, tzinfo=UTC)
    event = make_schedule_event(
        "DRIVING",
        "DRIVING",
        start,
        datetime(2026, 1, 2, 0, tzinfo=UTC),
        distance_meters=100,
    )

    result = build_daily_logs(schedule=make_schedule([event]))

    assert result["summary"]["log_count"] == 1
    assert result["summary"]["end_date"] == "2026-01-01"
    assert all(
        event["duration_seconds"] > 0
        for log in result["logs"]
        for event in log["events"]
    )


def test_fractional_seconds_do_not_change_exact_daily_total():
    start = datetime(2026, 1, 1, 23, 59, 59, 250000, tzinfo=UTC)
    event = make_schedule_event(
        "DRIVING",
        "DRIVING",
        start,
        start + timedelta(seconds=1.5),
        distance_meters=3,
    )

    result = build_daily_logs(schedule=make_schedule([event]))

    assert len(result["logs"]) == 2
    assert all(log["totals"]["total_seconds"] == 86_400 for log in result["logs"])
    assert sum(
        sum(segment["duration_seconds"] for segment in log["segments"])
        for log in result["logs"]
    ) == 2 * 86_400
    assert result["summary"]["total_driving_distance_meters"] == pytest.approx(3)
