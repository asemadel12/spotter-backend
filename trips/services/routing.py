import logging
import math
from typing import Any, Mapping

import httpx
from django.conf import settings

from .exceptions import (
    RoutingServiceNotConfiguredError,
    RoutingServiceUnavailableError,
)

logger = logging.getLogger(__name__)

DIRECTIONS_URL = (
    "https://api.heigit.org/openrouteservice/v2/directions/"
    "driving-hgv/geojson"
)
HGV_SNAP_URL = "https://api.heigit.org/openrouteservice/v2/snap/driving-hgv/json"
CAR_SNAP_URL = "https://api.heigit.org/openrouteservice/v2/snap/driving-car/json"
CAR_DIRECTIONS_URL = (
    "https://api.heigit.org/openrouteservice/v2/directions/"
    "driving-car/geojson"
)
SNAP_RADIUS_METERS = 20000
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
    routable_coordinates = _snap_coordinates(
        coordinates,
        api_key,
        snap_url=HGV_SNAP_URL,
    )

    payload = _request_route(
        DIRECTIONS_URL,
        routable_coordinates,
        api_key,
        allow_profile_fallback=True,
    )
    return _normalize_route(payload)


def _request_route(
    url: str,
    coordinates: list[list[float]],
    api_key: str,
    *,
    allow_profile_fallback: bool,
) -> Any:
    try:
        response = httpx.post(
            url,
            json={"coordinates": coordinates, "instructions": True},
            headers={"Authorization": api_key},
            timeout=REQUEST_TIMEOUT,
        )
    except (httpx.TimeoutException, httpx.RequestError) as exc:
        raise RoutingServiceUnavailableError from exc

    if (
        allow_profile_fallback
        and url == DIRECTIONS_URL
        and _is_unroutable_point_response(response)
    ):
        logger.info(
            "ORS HGV route could not snap a point; retrying with driving-car. "
            "status=%s body=%s",
            response.status_code,
            _safe_response_text(response),
        )
        car_coordinates = _snap_coordinates(
            coordinates,
            api_key,
            snap_url=CAR_SNAP_URL,
        )
        return _request_route(
            CAR_DIRECTIONS_URL,
            car_coordinates,
            api_key,
            allow_profile_fallback=False,
        )

    try:
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "ORS directions request failed. url=%s status=%s body=%s",
            url,
            response.status_code,
            _safe_response_text(response),
        )
        raise RoutingServiceUnavailableError from exc
    except ValueError as exc:
        logger.warning(
            "ORS directions returned invalid JSON. url=%s status=%s",
            url,
            response.status_code,
        )
        raise RoutingServiceUnavailableError from exc


def _safe_response_text(response: httpx.Response) -> str:
    text = response.text.replace("\n", " ").replace("\r", " ").strip()
    return text[:500]


def _is_unroutable_point_response(response: httpx.Response) -> bool:
    if response.status_code not in {400, 404}:
        return False

    try:
        payload = response.json()
    except ValueError:
        return False

    if not isinstance(payload, dict):
        return False

    error = payload.get("error")
    if not isinstance(error, dict):
        return False

    if error.get("code") == 2010:
        return True

    message = error.get("message")
    return (
        isinstance(message, str)
        and (
            "Could not find point" in message
            or "Could not find routable point" in message
        )
    )


def _snap_coordinates(
    coordinates: list[list[float]],
    api_key: str,
    *,
    snap_url: str,
) -> list[list[float]]:
    """Best-effort snap geocoded points to the selected road network.

    City/locality geocoders often return a centroid rather than a point on a
    road. A wider snap search turns that centroid into a routable waypoint.
    If snapping fails, directions still receives the original coordinate.
    """
    try:
        response = httpx.post(
            snap_url,
            json={
                "locations": coordinates,
                "radius": SNAP_RADIUS_METERS,
            },
            headers={"Authorization": api_key},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPStatusError:
        logger.warning(
            "ORS snap request failed. url=%s status=%s body=%s",
            snap_url,
            response.status_code,
            _safe_response_text(response),
        )
        return coordinates
    except (httpx.TimeoutException, httpx.RequestError, ValueError):
        return coordinates

    if not isinstance(payload, dict):
        return coordinates

    locations = payload.get("locations")
    if not isinstance(locations, list) or len(locations) != len(coordinates):
        return coordinates

    snapped: list[list[float]] = []
    for index, (original, item) in enumerate(zip(coordinates, locations)):
        if not isinstance(item, dict):
            logger.info(
                "ORS snap found no routable edge. url=%s point_index=%s "
                "coordinate=%s radius=%sm",
                snap_url,
                index,
                original,
                SNAP_RADIUS_METERS,
            )
            snapped.append(original)
            continue

        location = item.get("location")
        if not isinstance(location, (list, tuple)) or len(location) < 2:
            snapped.append(original)
            continue

        try:
            longitude = _coordinate_value(location[0], minimum=-180, maximum=180)
            latitude = _coordinate_value(location[1], minimum=-90, maximum=90)
        except RoutingServiceUnavailableError:
            snapped.append(original)
            continue

        snapped.append([longitude, latitude])

    return snapped


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

    way_points = _step_way_points(step.get("way_points"))

    return {
        "instruction": instruction,
        "distance_meters": _measure(step.get("distance")),
        "duration_seconds": _measure(step.get("duration")),
        "type": step_type,
        "way_points": way_points,
    }


def _step_way_points(value: Any) -> list[int]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise RoutingServiceUnavailableError

    start, end = value
    if (
        isinstance(start, bool)
        or isinstance(end, bool)
        or not isinstance(start, int)
        or not isinstance(end, int)
        or start < 0
        or end < start
    ):
        raise RoutingServiceUnavailableError

    return [start, end]


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
