from rest_framework.response import Response
from rest_framework.views import APIView

from trips.application.planning import plan_trip

from .errors import (
    CONTROLLED_TRIP_PLANNING_ERRORS,
    trip_planning_error_response,
)
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

        try:
            result = plan_trip(serializer.validated_data)
        except CONTROLLED_TRIP_PLANNING_ERRORS as exc:
            return trip_planning_error_response(exc)

        return Response(result)
