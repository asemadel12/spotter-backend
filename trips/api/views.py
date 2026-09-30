from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from trips.services.exceptions import (
    LocationNotFoundError,
    RoutingServiceNotConfiguredError,
    RoutingServiceUnavailableError,
)
from trips.services.geocoding import geocode_location
from trips.services.hos import HosPlanningError, build_hos_schedule
from trips.services.routing import calculate_route

from .serializers import TripPlanSerializer


class HealthCheckView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        return Response(
            {
                "status": "ok",
                "service": "spotter-assessment-api",
            }
        )


class TripPlanView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        serializer = TripPlanSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        locations = {}
        try:
            for field in (
                "current_location",
                "pickup_location",
                "dropoff_location",
            ):
                try:
                    locations[field] = geocode_location(
                        serializer.validated_data[field]
                    )
                except LocationNotFoundError:
                    return Response(
                        {
                            "error": {
                                "code": "location_not_found",
                                "field": field,
                                "message": (
                                    f"Could not resolve {field.replace('_', ' ')}."
                                ),
                            }
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )

            route = calculate_route(
                locations["current_location"],
                locations["pickup_location"],
                locations["dropoff_location"],
            )
            schedule = build_hos_schedule(
                route=route,
                current_cycle_used_hours=serializer.validated_data[
                    "current_cycle_used_hours"
                ],
                start_datetime=timezone.now(),
            )
        except RoutingServiceNotConfiguredError:
            return Response(
                {
                    "error": {
                        "code": "routing_service_not_configured",
                        "message": "Trip routing service is not configured.",
                    }
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except RoutingServiceUnavailableError:
            return Response(
                {
                    "error": {
                        "code": "routing_service_unavailable",
                        "message": "Trip routing service is temporarily unavailable.",
                    }
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )
        except HosPlanningError:
            return Response(
                {
                    "error": {
                        "code": "trip_planning_failed",
                        "message": "Trip schedule could not be generated.",
                    }
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response(
            {
                "status": "planned",
                "trip": serializer.validated_data,
                "locations": locations,
                "route": route,
                "schedule": schedule,
            }
        )
