class RoutingServiceError(Exception):
    """Base exception for controlled trip-planning service failures."""


class RoutingServiceNotConfiguredError(RoutingServiceError):
    """Raised when the HeiGIT API key is not configured."""


class RoutingServiceUnavailableError(RoutingServiceError):
    """Raised when an upstream service cannot provide a usable response."""


class LocationNotFoundError(RoutingServiceError):
    """Raised when Pelias cannot resolve a location."""


class LocationTooBroadError(RoutingServiceError):
    """Raised when Pelias resolves a trip input only to a coarse area."""
