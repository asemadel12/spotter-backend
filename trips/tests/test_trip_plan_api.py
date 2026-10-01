from decimal import Decimal
from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from trips.application.exceptions import (
    TripLocationNotFoundError,
    TripLocationTooBroadError,
)
from trips.services.daily_logs import DailyLogBuildError
from trips.services.exceptions import (
    RoutingServiceNotConfiguredError,
    RoutingServiceUnavailableError,
)
from trips.services.hos import HosPlanningError


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def valid_trip_payload():
    return {
        "current_location": "Chicago, IL",
        "pickup_location": "Indianapolis, IN",
        "dropoff_location": "Dallas, TX",
        "current_cycle_used_hours": 20,
    }


@pytest.fixture
def planned_result(valid_trip_payload):
    return {
        "status": "planned",
        "trip": valid_trip_payload,
        "locations": {
            "current_location": {"label": "Chicago, Illinois, USA"},
            "pickup_location": {"label": "Indianapolis, Indiana, USA"},
            "dropoff_location": {"label": "Dallas, Texas, USA"},
        },
        "route": {
            "distance_meters": 1500000,
            "duration_seconds": 60000,
            "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
            "legs": [],
        },
        "schedule": {"summary": {}, "events": []},
        "daily_logs": {"summary": {"log_count": 1}, "logs": []},
    }


def test_valid_trip_returns_application_result(
    api_client,
    valid_trip_payload,
    planned_result,
):
    with patch("trips.api.views.plan_trip", return_value=planned_result) as planner:
        response = api_client.post(
            "/api/trips/plan/",
            valid_trip_payload,
            format="json",
        )

    assert response.status_code == 200
    assert response.json() == planned_result
    planner.assert_called_once()
    validated_data = planner.call_args.args[0]
    assert validated_data == {
        "current_location": "Chicago, IL",
        "pickup_location": "Indianapolis, IN",
        "dropoff_location": "Dallas, TX",
        "current_cycle_used_hours": Decimal("20"),
    }


@pytest.mark.parametrize(
    "field",
    ["current_location", "pickup_location", "dropoff_location"],
)
def test_location_not_found_returns_field_specific_400(
    field,
    api_client,
    valid_trip_payload,
):
    with patch(
        "trips.api.views.plan_trip",
        side_effect=TripLocationNotFoundError(field),
    ):
        response = api_client.post(
            "/api/trips/plan/",
            valid_trip_payload,
            format="json",
        )

    assert response.status_code == 400
    assert response.json() == {
        "error": {
            "code": "location_not_found",
            "field": field,
            "message": (
                "Could not resolve drop-off location."
                if field == "dropoff_location"
                else f"Could not resolve {field.replace('_', ' ')}."
            ),
        }
    }


def test_too_broad_location_returns_field_specific_400(
    api_client,
    valid_trip_payload,
):
    with patch(
        "trips.api.views.plan_trip",
        side_effect=TripLocationTooBroadError("dropoff_location"),
    ):
        response = api_client.post(
            "/api/trips/plan/",
            valid_trip_payload,
            format="json",
        )

    assert response.status_code == 400
    assert response.json() == {
        "error": {
            "code": "location_too_broad",
            "field": "dropoff_location",
            "message": "Use a city, street, or full address for drop-off location.",
        }
    }


def test_routing_upstream_failure_returns_502(api_client, valid_trip_payload):
    with patch(
        "trips.api.views.plan_trip",
        side_effect=RoutingServiceUnavailableError(),
    ):
        response = api_client.post(
            "/api/trips/plan/",
            valid_trip_payload,
            format="json",
        )

    assert response.status_code == 502
    assert response.json() == {
        "error": {
            "code": "routing_service_unavailable",
            "message": "Trip routing service is temporarily unavailable.",
        }
    }


def test_missing_routing_configuration_returns_503(api_client, valid_trip_payload):
    with patch(
        "trips.api.views.plan_trip",
        side_effect=RoutingServiceNotConfiguredError(),
    ):
        response = api_client.post(
            "/api/trips/plan/",
            valid_trip_payload,
            format="json",
        )

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "routing_service_not_configured",
            "message": "Trip routing service is not configured.",
        }
    }


def test_hos_planning_failure_returns_controlled_502(
    api_client,
    valid_trip_payload,
):
    with patch(
        "trips.api.views.plan_trip",
        side_effect=HosPlanningError("private route detail"),
    ):
        response = api_client.post(
            "/api/trips/plan/",
            valid_trip_payload,
            format="json",
        )

    assert response.status_code == 502
    assert response.json() == {
        "error": {
            "code": "trip_planning_failed",
            "message": "Trip schedule could not be generated.",
        }
    }
    assert "private route detail" not in str(response.json())


def test_daily_log_failure_returns_controlled_502(
    api_client,
    valid_trip_payload,
):
    with patch(
        "trips.api.views.plan_trip",
        side_effect=DailyLogBuildError("private schedule detail"),
    ):
        response = api_client.post(
            "/api/trips/plan/",
            valid_trip_payload,
            format="json",
        )

    assert response.status_code == 502
    assert response.json() == {
        "error": {
            "code": "daily_log_generation_failed",
            "message": "Daily log sheets could not be generated.",
        }
    }
    assert "private schedule detail" not in str(response.json())


def test_serializer_errors_return_400_without_calling_application(
    api_client,
    valid_trip_payload,
):
    valid_trip_payload["current_cycle_used_hours"] = 71

    with patch("trips.api.views.plan_trip") as planner:
        response = api_client.post(
            "/api/trips/plan/",
            valid_trip_payload,
            format="json",
        )

    assert response.status_code == 400
    assert "current_cycle_used_hours" in response.json()
    planner.assert_not_called()


def test_get_trip_plan_is_not_allowed(api_client):
    response = api_client.get("/api/trips/plan/")

    assert response.status_code == 405


def test_extra_fields_are_removed_before_application_call(
    api_client,
    valid_trip_payload,
    planned_result,
):
    valid_trip_payload["unexpected_field"] = "must not leak"

    with patch("trips.api.views.plan_trip", return_value=planned_result) as planner:
        response = api_client.post(
            "/api/trips/plan/",
            valid_trip_payload,
            format="json",
        )

    assert response.status_code == 200
    validated_data = planner.call_args.args[0]
    assert "unexpected_field" not in validated_data
