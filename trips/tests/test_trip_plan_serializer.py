from decimal import Decimal

import pytest

from trips.api.serializers import TripPlanSerializer


@pytest.fixture
def valid_trip_data():
    return {
        "current_location": "Chicago, IL",
        "pickup_location": "Indianapolis, IN",
        "dropoff_location": "Dallas, TX",
        "current_cycle_used_hours": 20,
    }


def test_valid_request(valid_trip_data):
    serializer = TripPlanSerializer(data=valid_trip_data)

    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data == {
        "current_location": "Chicago, IL",
        "pickup_location": "Indianapolis, IN",
        "dropoff_location": "Dallas, TX",
        "current_cycle_used_hours": Decimal("20"),
    }


def test_decimal_cycle_hours_are_accepted(valid_trip_data):
    valid_trip_data["current_cycle_used_hours"] = 20.5
    serializer = TripPlanSerializer(data=valid_trip_data)

    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["current_cycle_used_hours"] == Decimal("20.5")


@pytest.mark.parametrize("cycle_hours", [0, 70])
def test_cycle_hour_boundaries_are_accepted(valid_trip_data, cycle_hours):
    valid_trip_data["current_cycle_used_hours"] = cycle_hours
    serializer = TripPlanSerializer(data=valid_trip_data)

    assert serializer.is_valid(), serializer.errors


@pytest.mark.parametrize("cycle_hours", [-0.1, 70.1])
def test_cycle_hours_outside_allowed_range_are_rejected(
    valid_trip_data, cycle_hours
):
    valid_trip_data["current_cycle_used_hours"] = cycle_hours
    serializer = TripPlanSerializer(data=valid_trip_data)

    assert not serializer.is_valid()
    assert "current_cycle_used_hours" in serializer.errors


@pytest.mark.parametrize(
    "missing_field",
    [
        "current_location",
        "pickup_location",
        "dropoff_location",
        "current_cycle_used_hours",
    ],
)
def test_required_fields_are_rejected_when_missing(valid_trip_data, missing_field):
    valid_trip_data.pop(missing_field)
    serializer = TripPlanSerializer(data=valid_trip_data)

    assert not serializer.is_valid()
    assert missing_field in serializer.errors


@pytest.mark.parametrize(
    ("location_field", "location_value"),
    [
        ("current_location", ""),
        ("pickup_location", ""),
        ("dropoff_location", ""),
        ("current_location", "   "),
        ("pickup_location", "\t\n"),
        ("dropoff_location", "   "),
    ],
)
def test_blank_and_whitespace_only_locations_are_rejected(
    valid_trip_data, location_field, location_value
):
    valid_trip_data[location_field] = location_value
    serializer = TripPlanSerializer(data=valid_trip_data)

    assert not serializer.is_valid()
    assert location_field in serializer.errors


def test_surrounding_location_whitespace_is_trimmed(valid_trip_data):
    valid_trip_data.update(
        {
            "current_location": "  Chicago, IL  ",
            "pickup_location": "\tIndianapolis, IN\n",
            "dropoff_location": " Dallas, TX ",
        }
    )
    serializer = TripPlanSerializer(data=valid_trip_data)

    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["current_location"] == "Chicago, IL"
    assert serializer.validated_data["pickup_location"] == "Indianapolis, IN"
    assert serializer.validated_data["dropoff_location"] == "Dallas, TX"


@pytest.mark.parametrize(
    "location_field",
    ["current_location", "pickup_location", "dropoff_location"],
)
def test_locations_must_be_strings(valid_trip_data, location_field):
    valid_trip_data[location_field] = 123
    serializer = TripPlanSerializer(data=valid_trip_data)

    assert not serializer.is_valid()
    assert location_field in serializer.errors


def test_location_at_max_length_is_accepted(valid_trip_data):
    valid_trip_data["current_location"] = "a" * 255
    serializer = TripPlanSerializer(data=valid_trip_data)

    assert serializer.is_valid(), serializer.errors


@pytest.mark.parametrize(
    "location_field",
    ["current_location", "pickup_location", "dropoff_location"],
)
def test_locations_above_max_length_are_rejected(valid_trip_data, location_field):
    valid_trip_data[location_field] = "a" * 256
    serializer = TripPlanSerializer(data=valid_trip_data)

    assert not serializer.is_valid()
    assert location_field in serializer.errors


def test_non_numeric_cycle_hours_are_rejected(valid_trip_data):
    valid_trip_data["current_cycle_used_hours"] = "not-a-number"
    serializer = TripPlanSerializer(data=valid_trip_data)

    assert not serializer.is_valid()
    assert "current_cycle_used_hours" in serializer.errors
