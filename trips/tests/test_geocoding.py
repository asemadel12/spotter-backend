from unittest.mock import patch

import httpx
import pytest
from django.test import override_settings

from trips.services.exceptions import (
    LocationNotFoundError,
    LocationTooBroadError,
    RoutingServiceNotConfiguredError,
    RoutingServiceUnavailableError,
)
from trips.services.geocoding import GEOCODING_URL, geocode_location


@pytest.fixture
def geocoding_payload():
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [-87.6298, 41.8781],
                },
                "properties": {"label": "Chicago, Cook County, Illinois, USA"},
            }
        ],
    }


def make_response(payload, status_code=200):
    return httpx.Response(
        status_code,
        json=payload,
        request=httpx.Request("GET", GEOCODING_URL),
    )


@override_settings(ORS_API_KEY="test-api-key")
def test_successful_location_lookup_is_normalized(geocoding_payload):
    with patch(
        "trips.services.geocoding.httpx.get",
        return_value=make_response(geocoding_payload),
    ) as get:
        result = geocode_location("Chicago, IL")

    assert result == {
        "input": "Chicago, IL",
        "label": "Chicago, Cook County, Illinois, USA",
        "latitude": 41.8781,
        "longitude": -87.6298,
    }

    args, kwargs = get.call_args
    assert args == (GEOCODING_URL,)
    assert kwargs["params"] == {"text": "Chicago, IL", "size": 1}
    assert kwargs["headers"] == {"Authorization": "test-api-key"}
    assert "test-api-key" not in kwargs["params"].values()
    assert isinstance(kwargs["timeout"], httpx.Timeout)


@override_settings(ORS_API_KEY="test-api-key")
def test_empty_features_raise_location_not_found():
    with patch(
        "trips.services.geocoding.httpx.get",
        return_value=make_response({"features": []}),
    ):
        with pytest.raises(LocationNotFoundError):
            geocode_location("Unknown place")


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"features": "not-a-list"},
        {"features": [None]},
        {"features": [{"type": "NotAFeature"}]},
        {
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [1, 2]},
                }
            ]
        },
        {
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [1, 2]},
                    "properties": {"label": ""},
                }
            ]
        },
    ],
)
@override_settings(ORS_API_KEY="test-api-key")
def test_malformed_feature_raises_controlled_service_error(payload):
    with patch(
        "trips.services.geocoding.httpx.get",
        return_value=make_response(payload),
    ):
        with pytest.raises(RoutingServiceUnavailableError):
            geocode_location("Chicago, IL")


@pytest.mark.parametrize(
    "coordinates",
    [
        None,
        [-87.6298],
        ["-87.6298", 41.8781],
        [-87.6298, "41.8781"],
        [-181, 41.8781],
        [-87.6298, 91],
        [10**1000, 41.8781],
    ],
)
@override_settings(ORS_API_KEY="test-api-key")
def test_malformed_coordinates_raise_controlled_service_error(coordinates):
    payload = {
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": coordinates},
                "properties": {"label": "Chicago"},
            }
        ]
    }

    with patch(
        "trips.services.geocoding.httpx.get",
        return_value=make_response(payload),
    ):
        with pytest.raises(RoutingServiceUnavailableError):
            geocode_location("Chicago, IL")


@override_settings(ORS_API_KEY="test-api-key")
def test_timeout_raises_controlled_upstream_error():
    with patch(
        "trips.services.geocoding.httpx.get",
        side_effect=httpx.TimeoutException("request timed out"),
    ):
        with pytest.raises(RoutingServiceUnavailableError):
            geocode_location("Chicago, IL")


@override_settings(ORS_API_KEY="test-api-key")
def test_network_failure_raises_controlled_upstream_error():
    error = httpx.ConnectError(
        "connection failed",
        request=httpx.Request("GET", GEOCODING_URL),
    )
    with patch("trips.services.geocoding.httpx.get", side_effect=error):
        with pytest.raises(RoutingServiceUnavailableError):
            geocode_location("Chicago, IL")


@override_settings(ORS_API_KEY="test-api-key")
def test_http_error_raises_controlled_upstream_error():
    with patch(
        "trips.services.geocoding.httpx.get",
        return_value=make_response({"error": "failure"}, status_code=500),
    ):
        with pytest.raises(RoutingServiceUnavailableError):
            geocode_location("Chicago, IL")


@override_settings(ORS_API_KEY="test-api-key")
def test_invalid_json_raises_controlled_upstream_error():
    response = make_response({})
    with patch.object(response, "json", side_effect=ValueError("invalid JSON")):
        with patch("trips.services.geocoding.httpx.get", return_value=response):
            with pytest.raises(RoutingServiceUnavailableError):
                geocode_location("Chicago, IL")


@override_settings(ORS_API_KEY="")
def test_missing_api_key_raises_configuration_error_without_http_request():
    with patch("trips.services.geocoding.httpx.get") as get:
        with pytest.raises(RoutingServiceNotConfiguredError):
            geocode_location("Chicago, IL")

    get.assert_not_called()


@override_settings(ORS_API_KEY="test-api-key")
def test_state_level_location_is_rejected_as_too_broad():
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [-99.9018, 31.9686],
                },
                "properties": {
                    "label": "Texas, USA",
                    "layer": "region",
                },
            }
        ],
    }

    with patch(
        "trips.services.geocoding.httpx.get",
        return_value=make_response(payload),
    ):
        with pytest.raises(LocationTooBroadError):
            geocode_location("Texas, USA")
