from unittest.mock import patch

import httpx
import pytest
from django.test import override_settings

from trips.services.exceptions import (
    RoutingServiceNotConfiguredError,
    RoutingServiceUnavailableError,
)
from trips.services.routing import (
    DIRECTIONS_URL,
    SNAP_RADIUS_METERS,
    SNAP_URL,
    calculate_route,
)


@pytest.fixture
def resolved_locations():
    return (
        {"latitude": 41.8781, "longitude": -87.6298},
        {"latitude": 39.7684, "longitude": -86.1581},
        {"latitude": 32.7767, "longitude": -96.7970},
    )


@pytest.fixture
def route_payload():
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [-87.6298, 41.8781],
                        [-86.1581, 39.7684],
                        [-96.7970, 32.7767],
                    ],
                },
                "properties": {
                    "summary": {"distance": 1500000.5, "duration": 60000.25},
                    "segments": [
                        {
                            "distance": 300000.5,
                            "duration": 12000.25,
                            "steps": [
                                {
                                    "instruction": "Head southeast",
                                    "distance": 1000.5,
                                    "duration": 60.25,
                                    "type": 11,
                                    "way_points": [0, 1],
                                }
                            ],
                        },
                        {
                            "distance": 1200000,
                            "duration": 48000,
                            "steps": [
                                {
                                    "instruction": "Continue southwest",
                                    "distance": 2000,
                                    "duration": 120,
                                    "type": 6,
                                    "way_points": [1, 2],
                                }
                            ],
                        },
                    ],
                },
            }
        ],
    }


def make_response(payload, status_code=200):
    return httpx.Response(
        status_code,
        json=payload,
        request=httpx.Request("POST", DIRECTIONS_URL),
    )


@override_settings(ORS_API_KEY="test-api-key")
def test_route_request_and_successful_geojson_normalization(
    resolved_locations, route_payload
):
    current, pickup, dropoff = resolved_locations
    with patch(
        "trips.services.routing.httpx.post",
        return_value=make_response(route_payload),
    ) as post:
        result = calculate_route(current, pickup, dropoff)

    args, kwargs = post.call_args
    assert args == (DIRECTIONS_URL,)
    assert DIRECTIONS_URL.endswith("/directions/driving-hgv/geojson")
    assert kwargs["json"] == {
        "coordinates": [
            [-87.6298, 41.8781],
            [-86.1581, 39.7684],
            [-96.797, 32.7767],
        ],
        "instructions": True,
    }
    assert kwargs["headers"] == {"Authorization": "test-api-key"}
    assert isinstance(kwargs["timeout"], httpx.Timeout)

    assert result == {
        "distance_meters": 1500000.5,
        "duration_seconds": 60000.25,
        "geometry": route_payload["features"][0]["geometry"],
        "legs": [
            {
                "from": "current_location",
                "to": "pickup_location",
                "distance_meters": 300000.5,
                "duration_seconds": 12000.25,
                "steps": [
                    {
                        "instruction": "Head southeast",
                        "distance_meters": 1000.5,
                        "duration_seconds": 60.25,
                        "type": 11,
                        "way_points": [0, 1],
                    }
                ],
            },
            {
                "from": "pickup_location",
                "to": "dropoff_location",
                "distance_meters": 1200000,
                "duration_seconds": 48000,
                "steps": [
                    {
                        "instruction": "Continue southwest",
                        "distance_meters": 2000,
                        "duration_seconds": 120,
                        "type": 6,
                        "way_points": [1, 2],
                    }
                ],
            },
        ],
    }


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"features": []},
        {"features": [None]},
        {"features": [{"type": "NotAFeature"}]},
    ],
)
@override_settings(ORS_API_KEY="test-api-key")
def test_malformed_or_missing_feature_raises_service_error(
    payload, resolved_locations
):
    with patch(
        "trips.services.routing.httpx.post",
        return_value=make_response(payload),
    ):
        with pytest.raises(RoutingServiceUnavailableError):
            calculate_route(*resolved_locations)


@override_settings(ORS_API_KEY="test-api-key")
def test_missing_geometry_raises_service_error(resolved_locations, route_payload):
    del route_payload["features"][0]["geometry"]

    with patch(
        "trips.services.routing.httpx.post",
        return_value=make_response(route_payload),
    ):
        with pytest.raises(RoutingServiceUnavailableError):
            calculate_route(*resolved_locations)


@override_settings(ORS_API_KEY="test-api-key")
def test_malformed_geometry_coordinates_raise_service_error(
    resolved_locations, route_payload
):
    route_payload["features"][0]["geometry"]["coordinates"] = [[-87, 41]]

    with patch(
        "trips.services.routing.httpx.post",
        return_value=make_response(route_payload),
    ):
        with pytest.raises(RoutingServiceUnavailableError):
            calculate_route(*resolved_locations)


@override_settings(ORS_API_KEY="test-api-key")
def test_missing_route_summary_raises_service_error(
    resolved_locations, route_payload
):
    del route_payload["features"][0]["properties"]["summary"]

    with patch(
        "trips.services.routing.httpx.post",
        return_value=make_response(route_payload),
    ):
        with pytest.raises(RoutingServiceUnavailableError):
            calculate_route(*resolved_locations)


@override_settings(ORS_API_KEY="test-api-key")
def test_missing_segments_raises_service_error(resolved_locations, route_payload):
    del route_payload["features"][0]["properties"]["segments"]

    with patch(
        "trips.services.routing.httpx.post",
        return_value=make_response(route_payload),
    ):
        with pytest.raises(RoutingServiceUnavailableError):
            calculate_route(*resolved_locations)


@pytest.mark.parametrize("segment_count", [0, 1, 3])
@override_settings(ORS_API_KEY="test-api-key")
def test_unexpected_segment_count_raises_service_error(
    segment_count, resolved_locations, route_payload
):
    segments = route_payload["features"][0]["properties"]["segments"]
    route_payload["features"][0]["properties"]["segments"] = (
        segments * 2
    )[:segment_count]

    with patch(
        "trips.services.routing.httpx.post",
        return_value=make_response(route_payload),
    ):
        with pytest.raises(RoutingServiceUnavailableError):
            calculate_route(*resolved_locations)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("distance", -1),
        ("duration", "unknown"),
        ("distance", 10**1000),
    ],
)
@override_settings(ORS_API_KEY="test-api-key")
def test_unusable_summary_values_raise_service_error(
    field, value, resolved_locations, route_payload
):
    route_payload["features"][0]["properties"]["summary"][field] = value

    with patch(
        "trips.services.routing.httpx.post",
        return_value=make_response(route_payload),
    ):
        with pytest.raises(RoutingServiceUnavailableError):
            calculate_route(*resolved_locations)


@pytest.mark.parametrize("change", ["missing_steps", "malformed_step"])
@override_settings(ORS_API_KEY="test-api-key")
def test_malformed_segment_steps_raise_service_error(
    change, resolved_locations, route_payload
):
    first_segment = route_payload["features"][0]["properties"]["segments"][0]
    if change == "missing_steps":
        del first_segment["steps"]
    else:
        first_segment["steps"] = [{"instruction": "Missing other values"}]

    with patch(
        "trips.services.routing.httpx.post",
        return_value=make_response(route_payload),
    ):
        with pytest.raises(RoutingServiceUnavailableError):
            calculate_route(*resolved_locations)


@pytest.mark.parametrize(
    "way_points",
    [None, [0], [0, 1, 2], ["0", 1], [2, 1], [-1, 1]],
)
@override_settings(ORS_API_KEY="test-api-key")
def test_malformed_step_way_points_raise_service_error(
    way_points, resolved_locations, route_payload
):
    first_step = route_payload["features"][0]["properties"]["segments"][0]["steps"][0]
    first_step["way_points"] = way_points

    with patch(
        "trips.services.routing.httpx.post",
        return_value=make_response(route_payload),
    ):
        with pytest.raises(RoutingServiceUnavailableError):
            calculate_route(*resolved_locations)


@override_settings(ORS_API_KEY="test-api-key")
def test_timeout_raises_controlled_upstream_error(resolved_locations):
    with patch(
        "trips.services.routing.httpx.post",
        side_effect=httpx.TimeoutException("request timed out"),
    ):
        with pytest.raises(RoutingServiceUnavailableError):
            calculate_route(*resolved_locations)


@override_settings(ORS_API_KEY="test-api-key")
def test_network_failure_raises_controlled_upstream_error(resolved_locations):
    error = httpx.ConnectError(
        "connection failed",
        request=httpx.Request("POST", DIRECTIONS_URL),
    )
    with patch("trips.services.routing.httpx.post", side_effect=error):
        with pytest.raises(RoutingServiceUnavailableError):
            calculate_route(*resolved_locations)


@override_settings(ORS_API_KEY="test-api-key")
def test_http_error_raises_controlled_upstream_error(resolved_locations):
    with patch(
        "trips.services.routing.httpx.post",
        return_value=make_response({"error": "failure"}, status_code=500),
    ):
        with pytest.raises(RoutingServiceUnavailableError):
            calculate_route(*resolved_locations)


@override_settings(ORS_API_KEY="test-api-key")
def test_invalid_json_raises_controlled_upstream_error(resolved_locations):
    response = make_response({})
    with patch.object(response, "json", side_effect=ValueError("invalid JSON")):
        with patch("trips.services.routing.httpx.post", return_value=response):
            with pytest.raises(RoutingServiceUnavailableError):
                calculate_route(*resolved_locations)


@override_settings(ORS_API_KEY="")
def test_missing_api_key_raises_configuration_error_without_http_request(
    resolved_locations,
):
    with patch("trips.services.routing.httpx.post") as post:
        with pytest.raises(RoutingServiceNotConfiguredError):
            calculate_route(*resolved_locations)

    post.assert_not_called()


@override_settings(ORS_API_KEY="test-api-key")
def test_route_uses_hgv_snapped_coordinates_when_available(
    resolved_locations,
    route_payload,
):
    current, pickup, dropoff = resolved_locations
    snap_payload = {
        "locations": [
            {"location": [-87.6301, 41.8784], "snapped_distance": 31.2},
            {"location": [-86.1584, 39.7687], "snapped_distance": 18.4},
            {"location": [-96.7973, 32.7770], "snapped_distance": 22.1},
        ]
    }
    snap_response = httpx.Response(
        200,
        json=snap_payload,
        request=httpx.Request("POST", SNAP_URL),
    )
    route_response = make_response(route_payload)

    with patch(
        "trips.services.routing.httpx.post",
        side_effect=[snap_response, route_response],
    ) as post:
        calculate_route(current, pickup, dropoff)

    snap_call, directions_call = post.call_args_list
    assert snap_call.args == (SNAP_URL,)
    assert snap_call.kwargs["json"] == {
        "locations": [
            [-87.6298, 41.8781],
            [-86.1581, 39.7684],
            [-96.797, 32.7767],
        ],
        "radius": SNAP_RADIUS_METERS,
    }
    assert directions_call.args == (DIRECTIONS_URL,)
    assert directions_call.kwargs["json"] == {
        "coordinates": [
            [-87.6301, 41.8784],
            [-86.1584, 39.7687],
            [-96.7973, 32.777],
        ],
        "instructions": True,
    }


@override_settings(ORS_API_KEY="test-api-key")
def test_snap_failure_falls_back_to_original_coordinates(
    resolved_locations,
    route_payload,
):
    current, pickup, dropoff = resolved_locations
    snap_failure = httpx.Response(
        503,
        json={"error": "snap unavailable"},
        request=httpx.Request("POST", SNAP_URL),
    )
    route_response = make_response(route_payload)

    with patch(
        "trips.services.routing.httpx.post",
        side_effect=[snap_failure, route_response],
    ) as post:
        result = calculate_route(current, pickup, dropoff)

    assert result["distance_meters"] == route_payload["features"][0]["properties"]["summary"]["distance"]
    directions_call = post.call_args_list[1]
    assert directions_call.kwargs["json"]["coordinates"] == [
        [-87.6298, 41.8781],
        [-86.1581, 39.7684],
        [-96.797, 32.7767],
    ]
