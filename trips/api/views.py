from rest_framework.response import Response
from rest_framework.views import APIView

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

        return Response(
            {
                "status": "ready",
                "trip": serializer.validated_data,
            }
        )
