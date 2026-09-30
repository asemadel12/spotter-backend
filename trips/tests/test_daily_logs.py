from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from trips.services.daily_logs import DailyLogBuildError, build_daily_logs
from trips.tests.factories import make_schedule, make_schedule_event

UTC = timezone.utc


def test_single_day_log_has_complete_coverage_and_merges_adjacent_statuses():
    start = datetime(2026, 1, 1, 8, tzinfo=UTC)
    events = [
        make_schedule_event(
            "DRIVING", "DRIVING", start, start + timedelta(hours=1), distance_meters=100
        ),
        make_schedule_event(
            "DRIVING",
            "DRIVING",
            start + timedelta(hours=1),
            start + timedelta(hours=2),
            distance_meters=100,
        ),
        make_schedule_event(
            "PICKUP",
            "ON_DUTY_NOT_DRIVING",
            start + timedelta(hours=2),
            start + timedelta(hours=3),
            location="pickup_location",
        ),
    ]

    result = build_daily_logs(schedule=make_schedule(events))

    assert result["summary"]["log_count"] == 1
    log = result["logs"][0]
    assert log["segments"] == [
        {
            "status": "OFF_DUTY",
            "start_second": 0,
            "end_second": 8 * 3600,
            "duration_seconds": 8 * 3600,
        },
        {
            "status": "DRIVING",
            "start_second": 8 * 3600,
            "end_second": 10 * 3600,
            "duration_seconds": 2 * 3600,
        },
        {
            "status": "ON_DUTY_NOT_DRIVING",
            "start_second": 10 * 3600,
            "end_second": 11 * 3600,
            "duration_seconds": 3600,
        },
        {
            "status": "OFF_DUTY",
            "start_second": 11 * 3600,
            "end_second": 86_400,
            "duration_seconds": 13 * 3600,
        },
    ]
    assert log["segments"][0]["start_second"] == 0
    assert log["segments"][-1]["end_second"] == 86_400


def test_internal_gap_is_explicitly_filled_as_off_duty():
    start = datetime(2026, 1, 1, 8, tzinfo=UTC)
    events = [
        make_schedule_event(
            "DRIVING", "DRIVING", start, start + timedelta(hours=1), distance_meters=10
        ),
        make_schedule_event(
            "DRIVING",
            "DRIVING",
            start + timedelta(hours=2),
            start + timedelta(hours=3),
            distance_meters=10,
        ),
    ]

    log = build_daily_logs(schedule=make_schedule(events))["logs"][0]

    gap = next(
        segment
        for segment in log["segments"]
        if segment["start_second"] == 9 * 3600
    )
    assert gap == {
        "status": "OFF_DUTY",
        "start_second": 9 * 3600,
        "end_second": 10 * 3600,
        "duration_seconds": 3600,
    }


def test_builder_does_not_modify_original_schedule():
    start = datetime(2026, 1, 1, 8, tzinfo=UTC)
    schedule = make_schedule(
        [
            make_schedule_event(
                "DRIVING",
                "DRIVING",
                start,
                start + timedelta(hours=1),
                distance_meters=10,
                route_progress={"leg_index": 0},
            )
        ]
    )
    original = deepcopy(schedule)

    build_daily_logs(schedule=schedule)

    assert schedule == original


def test_non_utc_timezone_is_preserved():
    local_timezone = timezone(timedelta(hours=5, minutes=30))
    start = datetime(2026, 1, 1, 8, tzinfo=local_timezone)
    schedule = make_schedule(
        [
            make_schedule_event(
                "DRIVING", "DRIVING", start, start + timedelta(hours=1), distance_meters=1
            )
        ]
    )

    log = build_daily_logs(schedule=schedule)["logs"][0]

    assert log["timezone"] == "+05:30"
    assert log["segments"][1]["start_second"] == 8 * 3600


@pytest.mark.parametrize(
    "schedule",
    [
        {},
        {"events": None},
        {"events": []},
        {"events": [None]},
    ],
)
def test_empty_or_malformed_event_list_is_rejected(schedule):
    with pytest.raises(DailyLogBuildError):
        build_daily_logs(schedule=schedule)


def valid_event():
    start = datetime(2026, 1, 1, 8, tzinfo=UTC)
    return make_schedule_event(
        "DRIVING", "DRIVING", start, start + timedelta(hours=1), distance_meters=10
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "malformed_start",
        "naive_start",
        "end_before_start",
        "unknown_status",
        "negative_distance",
        "duration_mismatch",
    ],
)
def test_malformed_event_fields_are_rejected(mutation):
    event = valid_event()
    if mutation == "malformed_start":
        event["start"] = "not-a-date"
    elif mutation == "naive_start":
        event["start"] = "2026-01-01T08:00:00"
    elif mutation == "end_before_start":
        event["end"] = event["start"]
    elif mutation == "unknown_status":
        event["status"] = "UNKNOWN"
    elif mutation == "negative_distance":
        event["distance_meters"] = -1
    else:
        event["duration_seconds"] = 10

    with pytest.raises(DailyLogBuildError):
        build_daily_logs(schedule={"events": [event]})


def test_overlapping_events_are_rejected():
    start = datetime(2026, 1, 1, 8, tzinfo=UTC)
    events = [
        make_schedule_event(
            "DRIVING", "DRIVING", start, start + timedelta(hours=2), distance_meters=10
        ),
        make_schedule_event(
            "BREAK",
            "ON_DUTY_NOT_DRIVING",
            start + timedelta(hours=1),
            start + timedelta(hours=3),
        ),
    ]

    with pytest.raises(DailyLogBuildError):
        build_daily_logs(schedule=make_schedule(events))


def test_unsorted_events_are_rejected():
    start = datetime(2026, 1, 1, 8, tzinfo=UTC)
    later = make_schedule_event(
        "DRIVING",
        "DRIVING",
        start + timedelta(hours=2),
        start + timedelta(hours=3),
        distance_meters=10,
    )
    earlier = make_schedule_event(
        "DRIVING", "DRIVING", start, start + timedelta(hours=1), distance_meters=10
    )

    with pytest.raises(DailyLogBuildError):
        build_daily_logs(schedule=make_schedule([later, earlier]))
