from django.urls import path

from .views import HealthCheckView, LocationAutocompleteView, TripPlanView

urlpatterns = [
    path("health/", HealthCheckView.as_view(), name="health-check"),
    path(
        "locations/autocomplete/",
        LocationAutocompleteView.as_view(),
        name="location-autocomplete",
    ),
    path("trips/plan/", TripPlanView.as_view(), name="trip-plan"),
]
