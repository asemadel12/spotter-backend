from decimal import Decimal

from rest_framework import serializers


class LocationField(serializers.CharField):
    default_error_messages = {
        "invalid": "Not a valid string.",
    }

    def to_internal_value(self, data):
        if not isinstance(data, str):
            self.fail("invalid")

        return super().to_internal_value(data)


class TripPlanSerializer(serializers.Serializer):
    current_location = LocationField(
        max_length=255,
        trim_whitespace=True,
    )
    pickup_location = LocationField(
        max_length=255,
        trim_whitespace=True,
    )
    dropoff_location = LocationField(
        max_length=255,
        trim_whitespace=True,
    )
    current_cycle_used_hours = serializers.DecimalField(
        max_digits=None,
        decimal_places=None,
        min_value=Decimal("0"),
        max_value=Decimal("70"),
        coerce_to_string=False,
    )


class LocationAutocompleteQuerySerializer(serializers.Serializer):
    q = serializers.CharField(
        min_length=2,
        max_length=255,
        trim_whitespace=True,
    )
