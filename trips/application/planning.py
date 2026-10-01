from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from django.utils import timezone

from trips.application.exceptions import (
    TripLocationNotFoundError,
    TripLocationTooBroadError,
)
from trips.services.daily_logs import build_daily_logs
from trips.services.exceptions import LocationNotFoundError, LocationTooBroadError
from trips.services.geocoding import geocode_location
from trips.services.hos import build_hos_schedule
from trips.services.routing import calculate_route

LOCATION_FIELDS = (
    "current_location",
    "pickup_location",
    "dropoff_location",
)


def plan_trip(
    validated_data: Mapping[str, Any],
    *,
    start_datetime: datetime | None = None,
) -> dict[str, Any]:
    """Execute the trip-planning use case from normalized request data."""
    locations = _resolve_locations(validated_data)
    route = calculate_route(
        locations["current_location"],
        locations["pickup_location"],
        locations["dropoff_location"],
    )
    schedule = build_hos_schedule(
        route=route,
        current_cycle_used_hours=validated_data["current_cycle_used_hours"],
        start_datetime=start_datetime or timezone.now(),
    )
    daily_logs = build_daily_logs(
        schedule=schedule,
        locations=locations,
    )

    return {
        "status": "planned",
        "trip": dict(validated_data),
        "locations": locations,
        "route": route,
        "schedule": schedule,
        "daily_logs": daily_logs,
    }


def _resolve_locations(
    validated_data: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    locations: dict[str, dict[str, Any]] = {}

    for field in LOCATION_FIELDS:
        try:
            locations[field] = geocode_location(validated_data[field])
        except LocationTooBroadError as exc:
            raise TripLocationTooBroadError(field) from exc
        except LocationNotFoundError as exc:
            raise TripLocationNotFoundError(field) from exc

    return locations
