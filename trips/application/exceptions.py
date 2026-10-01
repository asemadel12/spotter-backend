class TripPlanningApplicationError(Exception):
    """Base exception for application-level trip-planning failures."""


class TripLocationNotFoundError(TripPlanningApplicationError):
    """Raised when one of the requested trip locations cannot be resolved."""

    def __init__(self, field: str):
        self.field = field
        super().__init__(f"Could not resolve {field}.")


class TripLocationTooBroadError(TripPlanningApplicationError):
    """Raised when a trip location resolves only to a state/county/country."""

    def __init__(self, field: str):
        self.field = field
        super().__init__(f"{field} is too broad for routing.")
