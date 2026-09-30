class TripPlanningApplicationError(Exception):
    """Base exception for application-level trip-planning failures."""


class TripLocationNotFoundError(TripPlanningApplicationError):
    """Raised when one of the requested trip locations cannot be resolved."""

    def __init__(self, field: str):
        self.field = field
        super().__init__(f"Could not resolve {field}.")
