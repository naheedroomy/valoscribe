"""Typed map configuration and normalized geometry helpers."""

from valoscribe.maps.config import (
    MapDefinition,
    MapPolygon,
    MapRegistrationThresholds,
    MapSource,
    MapZone,
    SmokeDetectionConfig,
    SmokeTrackingThresholds,
)
from valoscribe.maps.registration import MinimapRegistrar, RegistrationResult

__all__ = [
    "MapDefinition",
    "MapPolygon",
    "MapRegistrationThresholds",
    "MapSource",
    "MapZone",
    "SmokeDetectionConfig",
    "SmokeTrackingThresholds",
    "MinimapRegistrar",
    "RegistrationResult",
]
