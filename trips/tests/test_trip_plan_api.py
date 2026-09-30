import pytest
from rest_framework.test import APIClient


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


def test_trip_plan_returns_200_with_expected_contract(api_client, valid_trip_payload):
    response = api_client.post("/api/trips/plan/", valid_trip_payload, format="json")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "trip": valid_trip_payload,
    }


def test_invalid_trip_plan_returns_400(api_client, valid_trip_payload):
    valid_trip_payload["current_cycle_used_hours"] = 71

    response = api_client.post("/api/trips/plan/", valid_trip_payload, format="json")

    assert response.status_code == 400
    assert "current_cycle_used_hours" in response.json()


def test_get_trip_plan_is_not_allowed(api_client):
    response = api_client.get("/api/trips/plan/")

    assert response.status_code == 405


def test_extra_fields_are_not_returned(api_client, valid_trip_payload):
    valid_trip_payload["unexpected_field"] = "must not leak"

    response = api_client.post("/api/trips/plan/", valid_trip_payload, format="json")

    assert response.status_code == 200
    assert "unexpected_field" not in response.json()["trip"]
