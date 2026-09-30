import math
from typing import Any, Mapping

import httpx
from django.conf import settings

from .exceptions import (
    RoutingServiceNotConfiguredError,
    RoutingServiceUnavailableError,
)

DIRECTIONS_URL = (
    "https://api.heigit.org/openrouteservice/v2/directions/"
    "driving-hgv/geojson"
)
REQUEST_TIMEOUT = httpx.Timeout(20.0, connect=5.0)
LEG_NAMES = (
    ("current_location", "pickup_location"),
    ("pickup_location", "dropoff_location"),
)


def calculate_route(
    current_location: Mapping[str, Any],
    pickup_location: Mapping[str, Any],
    dropoff_location: Mapping[str, Any],
) -> dict[str, Any]:
    api_key = _get_api_key()
    coordinates = [
        _location_coordinates(current_location),
        _location_coordinates(pickup_location),
        _location_coordinates(dropoff_location),
    ]

    try:
        response = httpx.post(
            DIRECTIONS_URL,
            json={"coordinates": coordinates, "instructions": True},
            headers={"Authorization": api_key},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.TimeoutException, httpx.RequestError, httpx.HTTPStatusError) as exc:
        raise RoutingServiceUnavailableError from exc
    except ValueError as exc:
        raise RoutingServiceUnavailableError from exc

    return _normalize_route(payload)


def _get_api_key() -> str:
    api_key = settings.ORS_API_KEY
    if not isinstance(api_key, str) or not api_key.strip():
        raise RoutingServiceNotConfiguredError

    return api_key


def _location_coordinates(location: Mapping[str, Any]) -> list[float]:
    try:
        longitude = _coordinate_value(
            location["longitude"], minimum=-180, maximum=180
        )
        latitude = _coordinate_value(location["latitude"], minimum=-90, maximum=90)
    except (KeyError, TypeError) as exc:
        raise RoutingServiceUnavailableError from exc

    return [longitude, latitude]


def _normalize_route(payload: Any) -> dict[str, Any]:
    feature = _route_feature(payload)
    geometry = _route_geometry(feature)

    properties = feature.get("properties")
    if not isinstance(properties, dict):
        raise RoutingServiceUnavailableError

    summary = properties.get("summary")
    if not isinstance(summary, dict):
        raise RoutingServiceUnavailableError

    distance = _measure(summary.get("distance"))
    duration = _measure(summary.get("duration"))
    segments = properties.get("segments")
    if not isinstance(segments, list) or len(segments) != len(LEG_NAMES):
        raise RoutingServiceUnavailableError

    legs = [
        _normalize_leg(segment, from_name, to_name)
        for segment, (from_name, to_name) in zip(segments, LEG_NAMES)
    ]

    return {
        "distance_meters": distance,
        "duration_seconds": duration,
        "geometry": geometry,
        "legs": legs,
    }


def _route_feature(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or not isinstance(payload.get("features"), list):
        raise RoutingServiceUnavailableError

    features = payload["features"]
    if not features or not isinstance(features[0], dict):
        raise RoutingServiceUnavailableError

    feature = features[0]
    if feature.get("type") != "Feature":
        raise RoutingServiceUnavailableError

    return feature


def _route_geometry(feature: dict[str, Any]) -> dict[str, Any]:
    geometry = feature.get("geometry")
    if not isinstance(geometry, dict) or geometry.get("type") != "LineString":
        raise RoutingServiceUnavailableError

    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, list) or len(coordinates) < 2:
        raise RoutingServiceUnavailableError

    for coordinate in coordinates:
        if not isinstance(coordinate, (list, tuple)) or len(coordinate) < 2:
            raise RoutingServiceUnavailableError
        _coordinate_value(coordinate[0], minimum=-180, maximum=180)
        _coordinate_value(coordinate[1], minimum=-90, maximum=90)

    return {
        "type": "LineString",
        "coordinates": coordinates,
    }


def _normalize_leg(
    segment: Any, from_name: str, to_name: str
) -> dict[str, Any]:
    if not isinstance(segment, dict):
        raise RoutingServiceUnavailableError

    steps = segment.get("steps")
    if not isinstance(steps, list):
        raise RoutingServiceUnavailableError

    return {
        "from": from_name,
        "to": to_name,
        "distance_meters": _measure(segment.get("distance")),
        "duration_seconds": _measure(segment.get("duration")),
        "steps": [_normalize_step(step) for step in steps],
    }


def _normalize_step(step: Any) -> dict[str, Any]:
    if not isinstance(step, dict):
        raise RoutingServiceUnavailableError

    instruction = step.get("instruction")
    step_type = step.get("type")
    if not isinstance(instruction, str) or not instruction.strip():
        raise RoutingServiceUnavailableError
    if isinstance(step_type, bool) or not isinstance(step_type, int):
        raise RoutingServiceUnavailableError

    return {
        "instruction": instruction,
        "distance_meters": _measure(step.get("distance")),
        "duration_seconds": _measure(step.get("duration")),
        "type": step_type,
    }


def _measure(value: Any) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RoutingServiceUnavailableError

    try:
        normalized = float(value)
    except (OverflowError, ValueError) as exc:
        raise RoutingServiceUnavailableError from exc

    if not math.isfinite(normalized) or value < 0:
        raise RoutingServiceUnavailableError

    return value


def _coordinate_value(value: Any, *, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RoutingServiceUnavailableError

    try:
        normalized = float(value)
    except (OverflowError, ValueError) as exc:
        raise RoutingServiceUnavailableError from exc

    if not math.isfinite(normalized) or not minimum <= normalized <= maximum:
        raise RoutingServiceUnavailableError

    return normalized
