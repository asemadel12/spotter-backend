from __future__ import annotations

from copy import deepcopy
import logging
import math
from typing import Any, Mapping

from trips.services.exceptions import RoutingServiceError
from trips.services.geocoding import reverse_geocode_city_state

logger = logging.getLogger(__name__)

_STOP_EVENT_TYPES = {
    "DRIVING",
    "BREAK",
    "FUEL",
    "SLEEPER",
    "CYCLE_RESTART",
}
_LOCATION_REFS = {
    "current_location",
    "pickup_location",
    "dropoff_location",
}
_EARTH_RADIUS_METERS = 6_371_008.8


def enrich_schedule_event_locations(
    *,
    schedule: Mapping[str, Any],
    route: Mapping[str, Any],
    locations: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Attach a nearest city/state label to route-related duty changes.

    Reverse geocoding is best-effort. The trip remains valid if the upstream
    reverse geocoder cannot resolve a location.
    """
    result = deepcopy(dict(schedule))
    events = result.get("events")
    if not isinstance(events, list):
        return result

    coordinates = _route_coordinates(route)
    total_route_distance = _positive_number(route.get("distance_meters"))
    if coordinates is None or total_route_distance is None:
        return result

    cumulative_distance = 0.0
    reverse_cache: dict[tuple[float, float], str | None] = {}

    for event in events:
        if not isinstance(event, dict):
            continue

        event_type = event.get("type")
        location_ref = event.get("location")

        if isinstance(location_ref, str) and location_ref in _LOCATION_REFS:
            label = _known_location_label(locations, location_ref)
            if label:
                event["location_label"] = label

        if event_type in _STOP_EVENT_TYPES and "location_label" not in event:
            if cumulative_distance <= 0:
                label = _known_location_label(locations, "current_location")
                if label:
                    event["location_label"] = label
            else:
                coordinate = coordinate_along_route(
                    coordinates,
                    total_route_distance=total_route_distance,
                    distance_meters=cumulative_distance,
                )
                if coordinate is not None:
                    longitude, latitude = coordinate
                    cache_key = (round(longitude, 5), round(latitude, 5))
                    if cache_key not in reverse_cache:
                        try:
                            reverse_cache[cache_key] = reverse_geocode_city_state(
                                latitude=latitude,
                                longitude=longitude,
                            )
                        except RoutingServiceError:
                            logger.info(
                                "Reverse geocoding unavailable for ELD remark "
                                "coordinate=%s",
                                coordinate,
                            )
                            reverse_cache[cache_key] = None
                    label = reverse_cache[cache_key]
                    if label:
                        event["location_label"] = label

        if event_type == "DRIVING":
            distance = _non_negative_number(event.get("distance_meters"))
            if distance is not None:
                cumulative_distance = min(
                    total_route_distance,
                    cumulative_distance + distance,
                )

    return result


def coordinate_along_route(
    coordinates: list[list[float]],
    *,
    total_route_distance: float,
    distance_meters: float,
) -> list[float] | None:
    if len(coordinates) < 2 or total_route_distance <= 0:
        return None

    fraction = min(1.0, max(0.0, distance_meters / total_route_distance))
    segment_lengths = [
        _haversine_distance(coordinates[index], coordinates[index + 1])
        for index in range(len(coordinates) - 1)
    ]
    geometry_length = sum(segment_lengths)
    if geometry_length <= 0:
        return coordinates[0]

    target = geometry_length * fraction
    walked = 0.0

    for index, segment_length in enumerate(segment_lengths):
        start = coordinates[index]
        end = coordinates[index + 1]
        if segment_length <= 0:
            continue
        if walked + segment_length >= target:
            local_fraction = (target - walked) / segment_length
            return [
                start[0] + (end[0] - start[0]) * local_fraction,
                start[1] + (end[1] - start[1]) * local_fraction,
            ]
        walked += segment_length

    return coordinates[-1]


def _route_coordinates(route: Mapping[str, Any]) -> list[list[float]] | None:
    geometry = route.get("geometry")
    if not isinstance(geometry, Mapping) or geometry.get("type") != "LineString":
        return None

    raw_coordinates = geometry.get("coordinates")
    if not isinstance(raw_coordinates, list) or len(raw_coordinates) < 2:
        return None

    coordinates: list[list[float]] = []
    for value in raw_coordinates:
        if not isinstance(value, (list, tuple)) or len(value) < 2:
            return None
        longitude = _coordinate(value[0], minimum=-180, maximum=180)
        latitude = _coordinate(value[1], minimum=-90, maximum=90)
        if longitude is None or latitude is None:
            return None
        coordinates.append([longitude, latitude])
    return coordinates


def _known_location_label(
    locations: Mapping[str, Any] | None,
    ref: str,
) -> str | None:
    if not isinstance(locations, Mapping):
        return None
    value = locations.get(ref)
    if not isinstance(value, Mapping):
        return None
    label = value.get("label")
    if isinstance(label, str) and label.strip():
        return label.strip()
    return None


def _coordinate(value: Any, *, minimum: float, maximum: float) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    normalized = float(value)
    if not math.isfinite(normalized) or not minimum <= normalized <= maximum:
        return None
    return normalized


def _positive_number(value: Any) -> float | None:
    normalized = _non_negative_number(value)
    if normalized is None or normalized <= 0:
        return None
    return normalized


def _non_negative_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < 0:
        return None
    return normalized


def _haversine_distance(start: list[float], end: list[float]) -> float:
    lon1, lat1 = map(math.radians, start)
    lon2, lat2 = map(math.radians, end)
    delta_lon = lon2 - lon1
    delta_lat = lat2 - lat1

    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )
    return 2 * _EARTH_RADIUS_METERS * math.asin(min(1.0, math.sqrt(a)))
