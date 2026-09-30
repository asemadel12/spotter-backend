from __future__ import annotations

from collections.abc import Sequence

from trips.services.hos import METERS_PER_MILE


def make_route(
    *,
    leg_durations_seconds: Sequence[float] = (3600, 3600),
    leg_distances_meters: Sequence[float] | None = None,
    steps_per_leg: int = 1,
    include_zero_step: bool = False,
) -> dict:
    if len(leg_durations_seconds) != 2:
        raise ValueError("Test routes require exactly two legs.")
    if leg_distances_meters is None:
        leg_distances_meters = tuple(
            duration / 3600 * 60 * float(METERS_PER_MILE)
            for duration in leg_durations_seconds
        )
    if len(leg_distances_meters) != 2:
        raise ValueError("Test routes require exactly two leg distances.")

    names = (
        ("current_location", "pickup_location"),
        ("pickup_location", "dropoff_location"),
    )
    legs = []
    way_point = 0
    for leg_index, ((from_name, to_name), duration, distance) in enumerate(
        zip(names, leg_durations_seconds, leg_distances_meters)
    ):
        steps = []
        if include_zero_step:
            steps.append(
                {
                    "instruction": "Remain in place",
                    "distance_meters": 0,
                    "duration_seconds": 0,
                    "type": 11,
                    "way_points": [way_point, way_point],
                }
            )

        if duration > 0:
            for step_index in range(steps_per_leg):
                is_last = step_index == steps_per_leg - 1
                step_duration = (
                    duration - sum(step["duration_seconds"] for step in steps)
                    if is_last
                    else duration / steps_per_leg
                )
                step_distance = (
                    distance - sum(step["distance_meters"] for step in steps)
                    if is_last
                    else distance / steps_per_leg
                )
                steps.append(
                    {
                        "instruction": f"Leg {leg_index + 1}, step {step_index + 1}",
                        "distance_meters": step_distance,
                        "duration_seconds": step_duration,
                        "type": 6,
                        "way_points": [way_point, way_point + 1],
                    }
                )
                way_point += 1
        elif not steps:
            steps.append(
                {
                    "instruction": "Remain in place",
                    "distance_meters": 0,
                    "duration_seconds": 0,
                    "type": 11,
                    "way_points": [way_point, way_point],
                }
            )

        legs.append(
            {
                "from": from_name,
                "to": to_name,
                "distance_meters": distance,
                "duration_seconds": duration,
                "steps": steps,
            }
        )

    total_distance = sum(leg_distances_meters)
    total_duration = sum(leg_durations_seconds)
    return {
        "distance_meters": total_distance,
        "duration_seconds": total_duration,
        "geometry": {
            "type": "LineString",
            "coordinates": [[0, 0], [1, 1]],
        },
        "legs": legs,
    }
