import math
from typing import Any

import httpx
from django.conf import settings

from .exceptions import (
    LocationNotFoundError,
    LocationTooBroadError,
    RoutingServiceNotConfiguredError,
    RoutingServiceUnavailableError,
)

GEOCODING_URL = "https://api.heigit.org/pelias/v1/search"
GEOCODING_AUTOCOMPLETE_URL = "https://api.heigit.org/pelias/v1/autocomplete"
GEOCODING_REVERSE_URL = "https://api.heigit.org/pelias/v1/reverse"
REQUEST_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
REVERSE_REQUEST_TIMEOUT = httpx.Timeout(4.0, connect=2.0)
TRIP_AUTOCOMPLETE_LAYERS = (
    "venue,address,street,locality,borough,neighbourhood"
)
TOO_BROAD_LAYERS = {
    "country",
    "macroregion",
    "region",
    "macrocounty",
    "county",
}


def geocode_location(location: str) -> dict[str, str | float]:
    api_key = _get_api_key()

    try:
        response = httpx.get(
            GEOCODING_URL,
            params={"text": location, "size": 1},
            headers={"Authorization": api_key},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.TimeoutException, httpx.RequestError, httpx.HTTPStatusError) as exc:
        raise RoutingServiceUnavailableError from exc
    except ValueError as exc:
        raise RoutingServiceUnavailableError from exc

    feature = _first_feature(payload)
    _ensure_trip_location_is_specific(feature)
    label = _feature_label(feature)
    longitude, latitude = _feature_coordinates(feature)

    return {
        "input": location,
        "label": label,
        "latitude": latitude,
        "longitude": longitude,
    }


def autocomplete_locations(
    query: str,
    *,
    size: int = 5,
    country: str = "USA",
) -> list[dict[str, str | float]]:
    api_key = _get_api_key()

    try:
        response = httpx.get(
            GEOCODING_AUTOCOMPLETE_URL,
            params={
                "text": query,
                "size": size,
                "boundary.country": country,
                "layers": TRIP_AUTOCOMPLETE_LAYERS,
            },
            headers={"Authorization": api_key},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.TimeoutException, httpx.RequestError, httpx.HTTPStatusError) as exc:
        raise RoutingServiceUnavailableError from exc
    except ValueError as exc:
        raise RoutingServiceUnavailableError from exc

    if not isinstance(payload, dict) or not isinstance(payload.get("features"), list):
        raise RoutingServiceUnavailableError

    suggestions: list[dict[str, str | float]] = []
    for feature in payload["features"]:
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            continue
        try:
            label = _feature_label(feature)
            longitude, latitude = _feature_coordinates(feature)
        except RoutingServiceUnavailableError:
            continue
        suggestions.append(
            {
                "label": label,
                "latitude": latitude,
                "longitude": longitude,
            }
        )

    return suggestions


def reverse_geocode_city_state(
    *,
    latitude: float,
    longitude: float,
) -> str | None:
    """Resolve a route coordinate to the nearest city/town and state.

    This is used only to enrich ELD duty-status remarks. A missing locality is
    not treated as a trip-planning failure.
    """
    api_key = _get_api_key()

    try:
        response = httpx.get(
            GEOCODING_REVERSE_URL,
            params={
                "point.lat": latitude,
                "point.lon": longitude,
                "size": 1,
                "layers": "locality,borough,localadmin",
            },
            headers={"Authorization": api_key},
            timeout=REVERSE_REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.TimeoutException, httpx.RequestError, httpx.HTTPStatusError) as exc:
        raise RoutingServiceUnavailableError from exc
    except ValueError as exc:
        raise RoutingServiceUnavailableError from exc

    if not isinstance(payload, dict) or not isinstance(payload.get("features"), list):
        raise RoutingServiceUnavailableError

    for feature in payload["features"]:
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            continue
        properties = feature.get("properties")
        if not isinstance(properties, dict):
            continue

        city = _first_non_blank(
            properties.get("locality"),
            properties.get("localadmin"),
            properties.get("borough"),
            properties.get("name"),
        )
        state = _first_non_blank(
            properties.get("region_a"),
            properties.get("region"),
        )
        if city and state:
            return f"{city}, {state}"
        if city:
            return city

        label = properties.get("label")
        if isinstance(label, str) and label.strip():
            return label.strip()

    return None


def _first_non_blank(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _ensure_trip_location_is_specific(feature: dict[str, Any]) -> None:
    properties = feature.get("properties")
    if not isinstance(properties, dict):
        raise RoutingServiceUnavailableError

    layer = properties.get("layer")
    if isinstance(layer, str) and layer in TOO_BROAD_LAYERS:
        raise LocationTooBroadError


def _get_api_key() -> str:
    api_key = settings.ORS_API_KEY
    if not isinstance(api_key, str) or not api_key.strip():
        raise RoutingServiceNotConfiguredError

    return api_key


def _first_feature(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or not isinstance(payload.get("features"), list):
        raise RoutingServiceUnavailableError

    features = payload["features"]
    if not features:
        raise LocationNotFoundError

    feature = features[0]
    if not isinstance(feature, dict) or feature.get("type") != "Feature":
        raise RoutingServiceUnavailableError

    return feature


def _feature_label(feature: dict[str, Any]) -> str:
    properties = feature.get("properties")
    if not isinstance(properties, dict):
        raise RoutingServiceUnavailableError

    label = properties.get("label")
    if not isinstance(label, str) or not label.strip():
        raise RoutingServiceUnavailableError

    return label


def _feature_coordinates(feature: dict[str, Any]) -> tuple[float, float]:
    geometry = feature.get("geometry")
    if not isinstance(geometry, dict) or geometry.get("type") != "Point":
        raise RoutingServiceUnavailableError

    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, (list, tuple)) or len(coordinates) < 2:
        raise RoutingServiceUnavailableError

    longitude = _coordinate_value(coordinates[0], minimum=-180, maximum=180)
    latitude = _coordinate_value(coordinates[1], minimum=-90, maximum=90)
    return longitude, latitude


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
