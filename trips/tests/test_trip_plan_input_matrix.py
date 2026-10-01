from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from trips.api.serializers import (
    LocationAutocompleteQuerySerializer,
    TripPlanSerializer,
)


BASE_TRIP = {
    "current_location": "Chicago, IL",
    "pickup_location": "St. Louis, MO",
    "dropoff_location": "Dallas, TX",
    "current_cycle_used_hours": 20,
}

LOCATION_FIELDS = (
    "current_location",
    "pickup_location",
    "dropoff_location",
)


@pytest.mark.parametrize(
    "value",
    [
        "Chicago, IL",
        "233 S Wacker Dr, Chicago, IL",
        "New York Engine Company 233, New York, NY",
        "O'Fallon-Saint Clair, IL",
        "San José, CA",
        "a" * 255,
    ],
)
@pytest.mark.parametrize("field", LOCATION_FIELDS)
def test_supported_location_text_is_accepted(field, value):
    payload = {**BASE_TRIP, field: value}
    serializer = TripPlanSerializer(data=payload)

    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data[field] == value


@pytest.mark.parametrize(
    "value",
    [
        "",
        "   ",
        "\t\n",
        "a" * 256,
        None,
        123,
        True,
        [],
        {},
    ],
)
@pytest.mark.parametrize("field", LOCATION_FIELDS)
def test_invalid_location_values_are_rejected(field, value):
    payload = {**BASE_TRIP, field: value}
    serializer = TripPlanSerializer(data=payload)

    assert not serializer.is_valid()
    assert field in serializer.errors


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0, Decimal("0")),
        (0.1, Decimal("0.1")),
        (1, Decimal("1")),
        (20.5, Decimal("20.5")),
        (69.999, Decimal("69.999")),
        (70, Decimal("70")),
        ("0", Decimal("0")),
        ("20.5", Decimal("20.5")),
        ("70", Decimal("70")),
    ],
)
def test_supported_cycle_values_are_accepted(value, expected):
    serializer = TripPlanSerializer(
        data={**BASE_TRIP, "current_cycle_used_hours": value}
    )

    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["current_cycle_used_hours"] == expected


@pytest.mark.parametrize(
    "value",
    [
        -0.001,
        -1,
        70.001,
        71,
        None,
        "",
        " ",
        "not-a-number",
        "NaN",
        "Infinity",
        "-Infinity",
        True,
        False,
        [],
        {},
    ],
)
def test_invalid_cycle_values_are_rejected(value):
    serializer = TripPlanSerializer(
        data={**BASE_TRIP, "current_cycle_used_hours": value}
    )

    assert not serializer.is_valid()
    assert "current_cycle_used_hours" in serializer.errors


def test_multiple_invalid_fields_are_reported_together():
    serializer = TripPlanSerializer(
        data={
            "current_location": " ",
            "pickup_location": None,
            "dropoff_location": "a" * 256,
            "current_cycle_used_hours": 71,
        }
    )

    assert not serializer.is_valid()
    assert set(serializer.errors) == {
        "current_location",
        "pickup_location",
        "dropoff_location",
        "current_cycle_used_hours",
    }


def test_surrounding_whitespace_is_trimmed_but_internal_text_is_preserved():
    serializer = TripPlanSerializer(
        data={
            "current_location": "  233 S Wacker Dr, Chicago, IL  ",
            "pickup_location": "\tSt. Louis, MO\n",
            "dropoff_location": "  Texas City, TX, USA ",
            "current_cycle_used_hours": 20,
        }
    )

    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["current_location"] == (
        "233 S Wacker Dr, Chicago, IL"
    )
    assert serializer.validated_data["pickup_location"] == "St. Louis, MO"
    assert serializer.validated_data["dropoff_location"] == "Texas City, TX, USA"


def test_equal_current_and_pickup_locations_are_not_rejected_by_input_validation():
    serializer = TripPlanSerializer(
        data={
            **BASE_TRIP,
            "current_location": "Dallas, TX",
            "pickup_location": "Dallas, TX",
        }
    )

    assert serializer.is_valid(), serializer.errors


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("Da", "Da"),
        ("Dallas", "Dallas"),
        ("  Texas City  ", "Texas City"),
        ("a" * 255, "a" * 255),
    ],
)
def test_autocomplete_query_valid_boundaries(query, expected):
    serializer = LocationAutocompleteQuerySerializer(data={"q": query})

    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["q"] == expected


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"q": ""},
        {"q": " "},
        {"q": "A"},
        {"q": "a" * 256},
        {"q": None},
    ],
)
def test_autocomplete_query_invalid_boundaries(data):
    serializer = LocationAutocompleteQuerySerializer(data=data)

    assert not serializer.is_valid()
    assert "q" in serializer.errors


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("current_location", ""),
        ("pickup_location", " "),
        ("dropoff_location", "a" * 256),
        ("current_cycle_used_hours", None),
        ("current_cycle_used_hours", -0.1),
        ("current_cycle_used_hours", 70.1),
    ],
)
def test_api_rejects_invalid_user_input_before_planning(field, value):
    payload = {**BASE_TRIP, field: value}
    response = APIClient().post("/api/trips/plan/", payload, format="json")

    assert response.status_code == 400
    assert field in response.json()
