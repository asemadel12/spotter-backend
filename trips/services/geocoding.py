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
    city_state = _feature_city_state(feature)
    longitude, latitude = _feature_coordinates(feature)

    result: dict[str, str | float] = {
        "input": location,
        "label": label,
        "latitude": latitude,
        "longitude": longitude,
    }
    if city_state is not None:
        result["city_state"] = city_state
    return result


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

    Prefer locality-like Pelias layers. Rural road points may not have a
    locality-layer feature directly at the coordinate, so a broader reverse
    lookup is used as a fallback and its locality metadata is extracted.
    """
    api_key = _get_api_key()

    primary = _reverse_geocode_payload(
        latitude=latitude,
        longitude=longitude,
        api_key=api_key,
        layers="locality,borough,localadmin",
        size=1,
    )
    label = _city_state_from_reverse_payload(primary)
    if label is not None:
        return label

    fallback = _reverse_geocode_payload(
        latitude=latitude,
        longitude=longitude,
        api_key=api_key,
        layers=None,
        size=5,
    )
    return _city_state_from_reverse_payload(fallback)


def _reverse_geocode_payload(
    *,
    latitude: float,
    longitude: float,
    api_key: str,
    layers: str | None,
    size: int,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "point.lat": latitude,
        "point.lon": longitude,
        "size": size,
    }
    if layers is not None:
        params["layers"] = layers

    try:
        response = httpx.get(
            GEOCODING_REVERSE_URL,
            params=params,
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
    return payload


def _city_state_from_reverse_payload(payload: dict[str, Any]) -> str | None:
    features = payload.get("features")
    if not isinstance(features, list):
        raise RoutingServiceUnavailableError

    for feature in features:
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            continue
        properties = feature.get("properties")
        if not isinstance(properties, dict):
            continue

        layer = properties.get("layer")
        layer_name = (
            properties.get("name")
            if layer in {"locality", "localadmin", "borough"}
            else None
        )
        city = _first_non_blank(
            properties.get("locality"),
            properties.get("localadmin"),
            properties.get("borough"),
            layer_name,
        )
        state = _first_non_blank(
            properties.get("region_a"),
            properties.get("region"),
        )
        if city and state:
            return f"{city}, {state}"
        if city:
            return city

        county = _first_non_blank(
            properties.get("county"),
            properties.get("macrocounty"),
            properties.get("name") if layer in {"county", "macrocounty"} else None,
        )
        if county and state:
            return f"{county}, {state}"
        if county:
            return county

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


def _feature_city_state(feature: dict[str, Any]) -> str | None:
    properties = feature.get("properties")
    if not isinstance(properties, dict):
        raise RoutingServiceUnavailableError

    layer = properties.get("layer")
    layer_name = (
        properties.get("name")
        if layer in {"locality", "localadmin", "borough"}
        else None
    )
    city = _first_non_blank(
        properties.get("locality"),
        properties.get("localadmin"),
        properties.get("borough"),
        layer_name,
    )
    state = _first_non_blank(
        properties.get("region_a"),
        properties.get("region"),
    )
    if city and state:
        return f"{city}, {state}"
    if city:
        return city
    return None


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
