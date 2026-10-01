from rest_framework import status
from rest_framework.response import Response

from trips.application.exceptions import (
    TripLocationNotFoundError,
    TripLocationTooBroadError,
)
from trips.services.daily_logs import DailyLogBuildError
from trips.services.exceptions import (
    RoutingServiceNotConfiguredError,
    RoutingServiceUnavailableError,
)
from trips.services.hos import HosPlanningError

CONTROLLED_TRIP_PLANNING_ERRORS = (
    TripLocationNotFoundError,
    TripLocationTooBroadError,
    RoutingServiceNotConfiguredError,
    RoutingServiceUnavailableError,
    HosPlanningError,
    DailyLogBuildError,
)


def trip_planning_error_response(exc: Exception) -> Response:
    """Translate controlled planning failures into stable public API errors."""
    if isinstance(exc, TripLocationNotFoundError):
        return Response(
            {
                "error": {
                    "code": "location_not_found",
                    "field": exc.field,
                    "message": f"Could not resolve {_field_label(exc.field)}.",
                }
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    if isinstance(exc, TripLocationTooBroadError):
        return Response(
            {
                "error": {
                    "code": "location_too_broad",
                    "field": exc.field,
                    "message": (
                        f"Use a city, street, or full address for "
                        f"{_field_label(exc.field)}."
                    ),
                }
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    if isinstance(exc, RoutingServiceNotConfiguredError):
        return _error_response(
            code="routing_service_not_configured",
            message="Trip routing service is not configured.",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    if isinstance(exc, RoutingServiceUnavailableError):
        return _error_response(
            code="routing_service_unavailable",
            message="Trip routing service is temporarily unavailable.",
            status_code=status.HTTP_502_BAD_GATEWAY,
        )

    if isinstance(exc, HosPlanningError):
        return _error_response(
            code="trip_planning_failed",
            message="Trip schedule could not be generated.",
            status_code=status.HTTP_502_BAD_GATEWAY,
        )

    if isinstance(exc, DailyLogBuildError):
        return _error_response(
            code="daily_log_generation_failed",
            message="Daily log sheets could not be generated.",
            status_code=status.HTTP_502_BAD_GATEWAY,
        )

    raise TypeError(f"Unsupported trip-planning error: {type(exc).__name__}")


def _field_label(field: str) -> str:
    labels = {
        "current_location": "current location",
        "pickup_location": "pickup location",
        "dropoff_location": "drop-off location",
    }
    return labels.get(field, field.replace("_", " "))


def _error_response(*, code: str, message: str, status_code: int) -> Response:
    return Response(
        {
            "error": {
                "code": code,
                "message": message,
            }
        },
        status=status_code,
    )
