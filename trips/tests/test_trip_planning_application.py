from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import call, patch

import pytest

from trips.application.exceptions import TripLocationNotFoundError
from trips.application.planning import plan_trip
from trips.services.exceptions import LocationNotFoundError


@pytest.fixture
def validated_trip():
    return {
        "current_location": "Chicago, IL",
        "pickup_location": "Indianapolis, IN",
        "dropoff_location": "Dallas, TX",
        "current_cycle_used_hours": Decimal("20"),
    }


@pytest.fixture
def locations():
    return {
        "current_location": {
            "input": "Chicago, IL",
            "label": "Chicago, Illinois, USA",
            "latitude": 41.8781,
            "longitude": -87.6298,
        },
        "pickup_location": {
            "input": "Indianapolis, IN",
            "label": "Indianapolis, Indiana, USA",
            "latitude": 39.7684,
            "longitude": -86.1581,
        },
        "dropoff_location": {
            "input": "Dallas, TX",
            "label": "Dallas, Texas, USA",
            "latitude": 32.7767,
            "longitude": -96.797,
        },
    }


@pytest.fixture
def route():
    return {
        "distance_meters": 1500000,
        "duration_seconds": 60000,
        "geometry": {
            "type": "LineString",
            "coordinates": [[-87.6298, 41.8781], [-96.797, 32.7767]],
        },
        "legs": [],
    }


@pytest.fixture
def schedule():
    return {
        "summary": {
            "total_trip_distance_meters": 1500000,
            "route_driving_seconds": 60000,
        },
        "events": [],
    }


@pytest.fixture
def daily_logs():
    return {
        "summary": {
            "log_count": 1,
            "start_date": "2026-01-02",
            "end_date": "2026-01-02",
        },
        "logs": [],
    }


def test_plan_trip_orchestrates_services_in_order(
    validated_trip,
    locations,
    route,
    schedule,
    daily_logs,
):
    start = datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc)

    with patch(
        "trips.application.planning.geocode_location",
        side_effect=list(locations.values()),
    ) as geocode:
        with patch(
            "trips.application.planning.calculate_route",
            return_value=route,
        ) as route_builder:
            with patch(
                "trips.application.planning.build_hos_schedule",
                return_value=schedule,
            ) as scheduler:
                with patch(
                    "trips.application.planning.build_daily_logs",
                    return_value=daily_logs,
                ) as daily_log_builder:
                    result = plan_trip(
                        validated_trip,
                        start_datetime=start,
                    )

    assert geocode.call_args_list == [
        call("Chicago, IL"),
        call("Indianapolis, IN"),
        call("Dallas, TX"),
    ]
    route_builder.assert_called_once_with(*locations.values())
    scheduler.assert_called_once_with(
        route=route,
        current_cycle_used_hours=Decimal("20"),
        start_datetime=start,
    )
    daily_log_builder.assert_called_once_with(
        schedule=schedule,
        locations=locations,
    )
    assert result == {
        "status": "planned",
        "trip": validated_trip,
        "locations": locations,
        "route": route,
        "schedule": schedule,
        "daily_logs": daily_logs,
    }


def test_plan_trip_uses_timezone_aware_now_when_start_is_not_supplied(
    validated_trip,
    locations,
    route,
    schedule,
    daily_logs,
):
    now = datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc)

    with patch(
        "trips.application.planning.geocode_location",
        side_effect=list(locations.values()),
    ):
        with patch(
            "trips.application.planning.calculate_route",
            return_value=route,
        ):
            with patch(
                "trips.application.planning.build_hos_schedule",
                return_value=schedule,
            ) as scheduler:
                with patch(
                    "trips.application.planning.build_daily_logs",
                    return_value=daily_logs,
                ):
                    with patch(
                        "trips.application.planning.timezone.now",
                        return_value=now,
                    ):
                        plan_trip(validated_trip)

    assert scheduler.call_args.kwargs["start_datetime"] == now
    assert scheduler.call_args.kwargs["start_datetime"].utcoffset() is not None


@pytest.mark.parametrize(
    ("failed_field", "successful_calls"),
    [
        ("current_location", 0),
        ("pickup_location", 1),
        ("dropoff_location", 2),
    ],
)
def test_location_resolution_failure_is_promoted_to_application_error(
    failed_field,
    successful_calls,
    validated_trip,
    locations,
):
    resolved = list(locations.values())[:successful_calls]
    side_effects = [*resolved, LocationNotFoundError()]

    with patch(
        "trips.application.planning.geocode_location",
        side_effect=side_effects,
    ):
        with patch("trips.application.planning.calculate_route") as route_builder:
            with pytest.raises(TripLocationNotFoundError) as exc_info:
                plan_trip(validated_trip)

    assert exc_info.value.field == failed_field
    route_builder.assert_not_called()
