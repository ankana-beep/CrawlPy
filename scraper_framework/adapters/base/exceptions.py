class AdapterError(Exception):
    """Base adapter exception."""


class DetectionError(AdapterError):
    """Raised when detection logic fails unexpectedly."""
