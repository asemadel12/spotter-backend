from unittest.mock import call, patch

import pytest
from rest_framework.test import APIClient

from trips.services.exceptions import (
    LocationNotFoundError,
    RoutingServiceNotConfiguredError,
    RoutingServiceUnavailableError,
)


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
def normalized_locations():
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
def normalized_route():
    return {
        "distance_meters": 1500000,
        "duration_seconds": 60000,
        "geometry": {
            "type": "LineString",
            "coordinates": [[-87.6298, 41.8781], [-96.797, 32.7767]],
        },
        "legs": [
            {
                "from": "current_location",
                "to": "pickup_location",
                "distance_meters": 300000,
                "duration_seconds": 12000,
                "steps": [],
            },
            {
                "from": "pickup_location",
                "to": "dropoff_location",
                "distance_meters": 1200000,
                "duration_seconds": 48000,
                "steps": [],
            },
        ],
    }


def test_valid_trip_returns_planned_contract_and_orchestrates_services(
    api_client, valid_trip_payload, normalized_locations, normalized_route
):
    geocoded = list(normalized_locations.values())
    with patch(
        "trips.api.views.geocode_location", side_effect=geocoded
    ) as geocode:
        with patch(
            "trips.api.views.calculate_route", return_value=normalized_route
        ) as route:
            response = api_client.post(
                "/api/trips/plan/", valid_trip_payload, format="json"
            )

    assert response.status_code == 200
    assert response.json() == {
        "status": "planned",
        "trip": valid_trip_payload,
        "locations": normalized_locations,
        "route": normalized_route,
    }
    assert geocode.call_args_list == [
        call("Chicago, IL"),
        call("Indianapolis, IN"),
        call("Dallas, TX"),
    ]
    route.assert_called_once_with(*geocoded)


@pytest.mark.parametrize(
    ("failed_field", "successful_calls"),
    [
        ("current_location", 0),
        ("pickup_location", 1),
        ("dropoff_location", 2),
    ],
)
def test_location_not_found_identifies_failed_field(
    failed_field,
    successful_calls,
    api_client,
    valid_trip_payload,
    normalized_locations,
):
    resolved = list(normalized_locations.values())[:successful_calls]
    side_effects = [*resolved, LocationNotFoundError()]

    with patch("trips.api.views.geocode_location", side_effect=side_effects):
        with patch("trips.api.views.calculate_route") as route:
            response = api_client.post(
                "/api/trips/plan/", valid_trip_payload, format="json"
            )

    assert response.status_code == 400
    assert response.json() == {
        "error": {
            "code": "location_not_found",
            "field": failed_field,
            "message": f"Could not resolve {failed_field.replace('_', ' ')}.",
        }
    }
    route.assert_not_called()


def test_routing_upstream_failure_returns_502(
    api_client, valid_trip_payload, normalized_locations
):
    with patch(
        "trips.api.views.geocode_location",
        side_effect=list(normalized_locations.values()),
    ):
        with patch(
            "trips.api.views.calculate_route",
            side_effect=RoutingServiceUnavailableError(),
        ):
            response = api_client.post(
                "/api/trips/plan/", valid_trip_payload, format="json"
            )

    assert response.status_code == 502
    assert response.json() == {
        "error": {
            "code": "routing_service_unavailable",
            "message": "Trip routing service is temporarily unavailable.",
        }
    }


def test_geocoding_upstream_failure_returns_502(api_client, valid_trip_payload):
    with patch(
        "trips.api.views.geocode_location",
        side_effect=RoutingServiceUnavailableError(),
    ):
        response = api_client.post(
            "/api/trips/plan/", valid_trip_payload, format="json"
        )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "routing_service_unavailable"


def test_missing_routing_configuration_returns_503(api_client, valid_trip_payload):
    with patch(
        "trips.api.views.geocode_location",
        side_effect=RoutingServiceNotConfiguredError(),
    ):
        response = api_client.post(
            "/api/trips/plan/", valid_trip_payload, format="json"
        )

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "routing_service_not_configured",
            "message": "Trip routing service is not configured.",
        }
    }


def test_serializer_errors_still_return_400_without_calling_services(
    api_client, valid_trip_payload
):
    valid_trip_payload["current_cycle_used_hours"] = 71

    with patch("trips.api.views.geocode_location") as geocode:
        response = api_client.post(
            "/api/trips/plan/", valid_trip_payload, format="json"
        )

    assert response.status_code == 400
    assert "current_cycle_used_hours" in response.json()
    geocode.assert_not_called()


def test_get_trip_plan_is_not_allowed(api_client):
    response = api_client.get("/api/trips/plan/")

    assert response.status_code == 405


def test_extra_fields_are_not_returned(
    api_client,
    valid_trip_payload,
    normalized_locations,
    normalized_route,
):
    valid_trip_payload["unexpected_field"] = "must not leak"

    with patch(
        "trips.api.views.geocode_location",
        side_effect=list(normalized_locations.values()),
    ):
        with patch(
            "trips.api.views.calculate_route", return_value=normalized_route
        ):
            response = api_client.post(
                "/api/trips/plan/", valid_trip_payload, format="json"
            )

    assert response.status_code == 200
    assert "unexpected_field" not in response.json()["trip"]
