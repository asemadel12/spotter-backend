from unittest.mock import patch

import httpx
import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from trips.services.exceptions import (
    RoutingServiceNotConfiguredError,
    RoutingServiceUnavailableError,
)
from trips.services.geocoding import (
    GEOCODING_AUTOCOMPLETE_URL,
    autocomplete_locations,
)


def make_response(payload, status_code=200):
    return httpx.Response(
        status_code,
        json=payload,
        request=httpx.Request("GET", GEOCODING_AUTOCOMPLETE_URL),
    )


@pytest.fixture
def autocomplete_payload():
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [-87.6359, 41.8789],
                },
                "properties": {
                    "label": "233 South Wacker Drive, Chicago, IL, USA",
                },
            },
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [-87.6244, 41.8895],
                },
                "properties": {
                    "label": "North Michigan Avenue, Chicago, IL, USA",
                },
            },
        ],
    }


@override_settings(ORS_API_KEY="test-api-key")
def test_autocomplete_returns_normalized_us_suggestions(autocomplete_payload):
    with patch(
        "trips.services.geocoding.httpx.get",
        return_value=make_response(autocomplete_payload),
    ) as get:
        result = autocomplete_locations("233 S Wa")

    assert result == [
        {
            "label": "233 South Wacker Drive, Chicago, IL, USA",
            "latitude": 41.8789,
            "longitude": -87.6359,
        },
        {
            "label": "North Michigan Avenue, Chicago, IL, USA",
            "latitude": 41.8895,
            "longitude": -87.6244,
        },
    ]

    args, kwargs = get.call_args
    assert args == (GEOCODING_AUTOCOMPLETE_URL,)
    assert kwargs["params"] == {
        "text": "233 S Wa",
        "size": 5,
        "boundary.country": "USA",
        "layers": "venue,address,street,locality,borough,neighbourhood",
    }
    assert kwargs["headers"] == {"Authorization": "test-api-key"}
    assert isinstance(kwargs["timeout"], httpx.Timeout)


@override_settings(ORS_API_KEY="test-api-key")
def test_autocomplete_empty_features_are_valid_empty_results():
    with patch(
        "trips.services.geocoding.httpx.get",
        return_value=make_response({"features": []}),
    ):
        assert autocomplete_locations("No matching location") == []


@override_settings(ORS_API_KEY="test-api-key")
def test_autocomplete_skips_malformed_individual_features(autocomplete_payload):
    autocomplete_payload["features"].insert(0, {"type": "NotAFeature"})

    with patch(
        "trips.services.geocoding.httpx.get",
        return_value=make_response(autocomplete_payload),
    ):
        result = autocomplete_locations("Chicago")

    assert len(result) == 2


@pytest.mark.parametrize(
    "side_effect",
    [
        RoutingServiceUnavailableError(),
        RoutingServiceNotConfiguredError(),
    ],
)
def test_autocomplete_api_degrades_to_empty_results(side_effect):
    client = APIClient()

    with patch(
        "trips.api.views.autocomplete_locations",
        side_effect=side_effect,
    ):
        response = client.get(
            "/api/locations/autocomplete/",
            {"q": "233 S Wa"},
        )

    assert response.status_code == 200
    assert response.json() == {"suggestions": []}


def test_autocomplete_api_returns_service_suggestions():
    client = APIClient()
    suggestions = [
        {
            "label": "233 South Wacker Drive, Chicago, IL, USA",
            "latitude": 41.8789,
            "longitude": -87.6359,
        }
    ]

    with patch(
        "trips.api.views.autocomplete_locations",
        return_value=suggestions,
    ) as autocomplete:
        response = client.get(
            "/api/locations/autocomplete/",
            {"q": "233 S Wa"},
        )

    assert response.status_code == 200
    assert response.json() == {"suggestions": suggestions}
    autocomplete.assert_called_once_with("233 S Wa")


def test_autocomplete_api_validates_short_query_without_service_call():
    client = APIClient()

    with patch("trips.api.views.autocomplete_locations") as autocomplete:
        response = client.get(
            "/api/locations/autocomplete/",
            {"q": "A"},
        )

    assert response.status_code == 400
    autocomplete.assert_not_called()
