from unittest.mock import patch

from trips.services.exceptions import RoutingServiceUnavailableError
from trips.services.route_locations import (
    coordinate_along_route,
    enrich_schedule_event_locations,
)


def test_coordinate_along_route_tracks_route_distance_fraction():
    coordinate = coordinate_along_route(
        [[-100.0, 30.0], [-99.0, 30.0]],
        total_route_distance=1000,
        distance_meters=250,
    )

    assert coordinate is not None
    assert coordinate[0] == -99.75
    assert coordinate[1] == 30.0


def test_schedule_events_receive_nearest_city_state_and_cache_same_stop():
    schedule = {
        "summary": {"total_trip_distance_meters": 1000},
        "events": [
            {
                "type": "DRIVING",
                "location": "current_location_to_pickup_location",
                "distance_meters": 400,
            },
            {
                "type": "BREAK",
                "location": "en_route",
                "distance_meters": 0,
            },
            {
                "type": "DRIVING",
                "location": "current_location_to_pickup_location",
                "distance_meters": 600,
            },
            {
                "type": "DROPOFF",
                "location": "dropoff_location",
                "distance_meters": 0,
            },
        ],
    }
    route = {
        "distance_meters": 1000,
        "geometry": {
            "type": "LineString",
            "coordinates": [[-100.0, 30.0], [-99.0, 30.0]],
        },
    }
    locations = {
        "current_location": {"label": "Start City, ST"},
        "dropoff_location": {"label": "End City, TX"},
    }

    with patch(
        "trips.services.route_locations.reverse_geocode_city_state",
        return_value="Midway, OK",
    ) as reverse:
        result = enrich_schedule_event_locations(
            schedule=schedule,
            route=route,
            locations=locations,
        )

    assert result["events"][0]["location_label"] == "Start City, ST"
    assert result["events"][1]["location_label"] == "Midway, OK"
    assert result["events"][2]["location_label"] == "Midway, OK"
    assert result["events"][3]["location_label"] == "End City, TX"
    reverse.assert_called_once()
    assert "location_label" not in schedule["events"][1]


def test_reverse_geocode_failure_never_breaks_trip_schedule_or_retries_every_stop():
    schedule = {
        "summary": {"total_trip_distance_meters": 1000},
        "events": [
            {
                "type": "DRIVING",
                "location": "current_location_to_pickup_location",
                "distance_meters": 400,
            },
            {
                "type": "FUEL",
                "location": "en_route",
                "distance_meters": 0,
            },
            {
                "type": "DRIVING",
                "location": "current_location_to_pickup_location",
                "distance_meters": 200,
            },
            {
                "type": "BREAK",
                "location": "en_route",
                "distance_meters": 0,
            },
        ],
    }
    route = {
        "distance_meters": 1000,
        "geometry": {
            "type": "LineString",
            "coordinates": [[-100.0, 30.0], [-99.0, 30.0]],
        },
    }

    with patch(
        "trips.services.route_locations.reverse_geocode_city_state",
        side_effect=RoutingServiceUnavailableError(),
    ) as reverse:
        result = enrich_schedule_event_locations(
            schedule=schedule,
            route=route,
        )

    assert result["events"][1]["location"] == "en_route"
    assert "location_label" not in result["events"][1]
    assert "location_label" not in result["events"][3]
    reverse.assert_called_once()



def test_driving_after_pickup_reuses_last_known_pickup_location_without_reverse_lookup():
    schedule = {
        "summary": {"total_trip_distance_meters": 1000},
        "events": [
            {
                "type": "DRIVING",
                "location": "current_location_to_pickup_location",
                "distance_meters": 400,
                "route_progress": {"leg_index": 0},
            },
            {
                "type": "PICKUP",
                "location": "pickup_location",
                "distance_meters": 0,
            },
            {
                "type": "DRIVING",
                "location": "pickup_location_to_dropoff_location",
                "distance_meters": 600,
                "route_progress": {"leg_index": 1},
            },
        ],
    }
    route = {
        "distance_meters": 1000,
        "geometry": {
            "type": "LineString",
            "coordinates": [[-100.0, 30.0], [-99.0, 30.0]],
        },
    }
    locations = {
        "current_location": {"label": "Start City, ST"},
        "pickup_location": {"label": "Pickup City, OK"},
    }

    with patch(
        "trips.services.route_locations.reverse_geocode_city_state"
    ) as reverse:
        result = enrich_schedule_event_locations(
            schedule=schedule,
            route=route,
            locations=locations,
        )

    assert result["events"][2]["location_label"] == "Pickup City, OK"
    reverse.assert_not_called()


def test_driving_after_en_route_rest_reuses_the_rest_location():
    schedule = {
        "summary": {"total_trip_distance_meters": 1000},
        "events": [
            {
                "type": "DRIVING",
                "location": "pickup_location_to_dropoff_location",
                "distance_meters": 600,
            },
            {
                "type": "SLEEPER",
                "location": "en_route",
                "distance_meters": 0,
            },
            {
                "type": "DRIVING",
                "location": "pickup_location_to_dropoff_location",
                "distance_meters": 400,
            },
        ],
    }
    route = {
        "distance_meters": 1000,
        "geometry": {
            "type": "LineString",
            "coordinates": [[-100.0, 30.0], [-99.0, 30.0]],
        },
    }
    locations = {
        "current_location": {"label": "Start City, ST"},
        "pickup_location": {"label": "Pickup City, OK"},
    }

    with patch(
        "trips.services.route_locations.reverse_geocode_city_state",
        return_value="Garland, TX",
    ):
        result = enrich_schedule_event_locations(
            schedule=schedule,
            route=route,
            locations=locations,
        )

    assert result["events"][1]["location_label"] == "Garland, TX"
    assert result["events"][2]["location_label"] == "Garland, TX"



def test_known_trip_location_prefers_city_state_over_full_provider_label():
    schedule = {
        "summary": {"total_trip_distance_meters": 1000},
        "events": [
            {
                "type": "PICKUP",
                "location": "pickup_location",
                "distance_meters": 0,
            }
        ],
    }
    route = {
        "distance_meters": 1000,
        "geometry": {
            "type": "LineString",
            "coordinates": [[-100.0, 30.0], [-99.0, 30.0]],
        },
    }
    locations = {
        "pickup_location": {
            "label": "Dallas, Dallas County, Texas, USA",
            "city_state": "Dallas, TX",
        }
    }

    result = enrich_schedule_event_locations(
        schedule=schedule,
        route=route,
        locations=locations,
    )

    assert result["events"][0]["location_label"] == "Dallas, TX"
