"""Versioned map metadata and normalized polygon lookup."""

from __future__ import annotations

import math
from typing import Literal

from pydantic import Field, field_validator, model_validator

from valoscribe.types.persistent import NormalizedPoint, PersistentModel


class MapPolygon(PersistentModel):
    """A simple normalized polygon; its first and last vertices need not repeat."""

    schema_version: Literal["1.0"] = "1.0"
    polygon_id: str = Field(min_length=1)
    vertices: list[NormalizedPoint] = Field(min_length=3)

    @field_validator("polygon_id")
    @classmethod
    def polygon_id_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("polygon_id must not be blank")
        return value

    @model_validator(mode="after")
    def polygon_has_area(self) -> MapPolygon:
        points = self.vertices
        area_twice = sum(
            point.x * points[(index + 1) % len(points)].y
            - points[(index + 1) % len(points)].x * point.y
            for index, point in enumerate(points)
        )
        if math.isclose(area_twice, 0.0, abs_tol=1e-12):
            raise ValueError("polygon vertices must enclose a non-zero area")
        return self

    def contains(self, point: NormalizedPoint) -> bool:
        """Return whether a normalized point lies inside or on the polygon boundary."""
        vertices = self.vertices
        inside = False
        for index, first in enumerate(vertices):
            second = vertices[(index + 1) % len(vertices)]
            if _point_on_segment(point, first, second):
                return True
            if (first.y > point.y) != (second.y > point.y):
                crossing_x = (second.x - first.x) * (point.y - first.y) / (
                    second.y - first.y
                ) + first.x
                if point.x < crossing_x:
                    inside = not inside
        return inside


class MapZone(PersistentModel):
    """Named zone polygon used for normalized point lookup."""

    schema_version: Literal["1.0"] = "1.0"
    zone_id: str = Field(min_length=1)
    polygon: MapPolygon

    @field_validator("zone_id")
    @classmethod
    def zone_id_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("zone_id must not be blank")
        return value


class MapSource(PersistentModel):
    """Provenance for a canonical map image, local or external."""

    schema_version: Literal["1.0"] = "1.0"
    image_url: str = Field(min_length=1)
    local_asset_path: str | None = None
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    asset_version: str = Field(min_length=1)
    patch_version: str | None = None
    provenance: str = Field(min_length=1)


class MapRegistrationThresholds(PersistentModel):
    """Configured acceptance limits for map registration and optional labels."""

    schema_version: Literal["1.0"] = "1.0"
    minimum_confidence: float = Field(ge=0.0, le=1.0)
    maximum_alignment_error: float = Field(gt=0.0)
    maximum_landmark_error_px: float | None = Field(default=None, gt=0.0)

    @field_validator(
        "minimum_confidence", "maximum_alignment_error", "maximum_landmark_error_px"
    )
    @classmethod
    def thresholds_are_finite(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("registration thresholds must be finite")
        return value


class FeatureRegistrationConfig(PersistentModel):
    """Map-specific grayscale feature-domain registration acceptance limits."""

    schema_version: Literal["1.0"] = "1.0"
    source_gray_range: tuple[int, int]
    canonical_gray_range: tuple[int, int]
    maximum_source_channel_spread: int = Field(ge=0, le=255)
    minimum_feature_coverage: float = Field(gt=0.0, le=1.0)
    maximum_feature_coverage: float = Field(gt=0.0, le=1.0)
    minimum_confidence: float = Field(ge=0.0, le=1.0)
    maximum_alignment_error: float = Field(gt=0.0, le=1.0)

    @model_validator(mode="after")
    def feature_limits_are_consistent(self) -> FeatureRegistrationConfig:
        for name, bounds in (
            ("source_gray_range", self.source_gray_range),
            ("canonical_gray_range", self.canonical_gray_range),
        ):
            if any(not 0 <= value <= 255 for value in bounds) or bounds[0] > bounds[1]:
                raise ValueError(f"{name} must be ordered grayscale values in [0, 255]")
        if self.minimum_feature_coverage >= self.maximum_feature_coverage:
            raise ValueError("feature coverage limits must be strictly increasing")
        if not math.isfinite(self.maximum_alignment_error):
            raise ValueError("feature registration thresholds must be finite")
        return self


class SmokeDetectionConfig(PersistentModel):
    """Explicit HSV and geometry limits for raw smoke extraction; no defaults."""

    schema_version: Literal["1.0"] = "1.0"
    hsv_lower: tuple[int, int, int]
    hsv_upper: tuple[int, int, int]
    minimum_area_px: int = Field(gt=0)
    maximum_area_px: int = Field(gt=0)
    minimum_radius_px: float = Field(gt=0.0)
    maximum_radius_px: float = Field(gt=0.0)
    minimum_circularity: float = Field(gt=0.0, le=1.0)

    @model_validator(mode="after")
    def bounds_are_consistent(self) -> SmokeDetectionConfig:
        if any(low > high for low, high in zip(self.hsv_lower, self.hsv_upper)):
            raise ValueError("smoke HSV lower bounds must not exceed upper bounds")
        if self.maximum_area_px < self.minimum_area_px:
            raise ValueError("smoke maximum area must be >= minimum area")
        if self.maximum_radius_px < self.minimum_radius_px:
            raise ValueError("smoke maximum radius must be >= minimum radius")
        if any(not 0 <= value <= 255 for value in (*self.hsv_lower, *self.hsv_upper)):
            raise ValueError("smoke HSV bounds must be in [0, 255]")
        radii = (self.minimum_radius_px, self.maximum_radius_px)
        if not all(math.isfinite(value) for value in radii):
            raise ValueError("smoke radii must be finite")
        return self


class SmokeTrackingThresholds(PersistentModel):
    """Map-specific association and missed-observation limits for smoke tracking."""

    schema_version: Literal["1.0"] = "1.0"
    association_distance: float = Field(gt=0.0, le=1.0)
    maximum_observation_gap_s: float = Field(gt=0.0)
    disappearance_confirmation_frames: int = Field(default=3, ge=2)

    @field_validator("association_distance", "maximum_observation_gap_s")
    @classmethod
    def thresholds_are_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("smoke tracking thresholds must be finite")
        return value


class FormationPolicy(PersistentModel):
    """Explicit map-specific spatial cutoffs; no production defaults are supplied."""

    schema_version: Literal["1.0"] = "1.0"
    group_distance: float = Field(gt=0.0, le=1.0)
    split_distance: float = Field(gt=0.0, le=1.0)
    spread_distance: float = Field(gt=0.0, le=1.0)
    site_stack_minimum: int = Field(ge=3, le=5)
    site_zone_ids: list[str] = Field(min_length=1)
    lane_zone_ids: list[str] = Field(min_length=2)

    @model_validator(mode="after")
    def thresholds_are_ordered(self) -> FormationPolicy:
        if not (0.0 < self.group_distance < self.split_distance < self.spread_distance <= 1.0):
            raise ValueError("formation distances must be strictly increasing in (0, 1]")
        if len(self.site_zone_ids) != len(set(self.site_zone_ids)):
            raise ValueError("site zone IDs must be unique")
        if len(self.lane_zone_ids) != len(set(self.lane_zone_ids)):
            raise ValueError("lane zone IDs must be unique")
        return self


class MapDefinition(PersistentModel):
    """Map source plus geometry; incomplete sources cannot be used as production maps."""

    schema_version: Literal["1.0"] = "1.0"
    map_id: str = Field(min_length=1)
    map_name: str = Field(min_length=1)
    coordinate_system: Literal["normalized_top_left_origin"] = "normalized_top_left_origin"
    canonical_minimap: MapSource
    geometry_status: Literal["pending", "validated"]
    walkable_areas: list[MapPolygon] = Field(default_factory=list)
    site_polygons: list[MapPolygon] = Field(default_factory=list)
    spawn_polygons: list[MapPolygon] = Field(default_factory=list)
    named_zones: list[MapZone] = Field(default_factory=list)
    zone_hysteresis_distance: float = Field(default=0.0, ge=0.0)
    orientation_rules: list[str] = Field(default_factory=list)
    registration_thresholds: MapRegistrationThresholds | None = None
    feature_registration: FeatureRegistrationConfig | None = None
    smoke_tracking_thresholds: SmokeTrackingThresholds | None = None
    smoke_detection: SmokeDetectionConfig | None = None
    formation_policy: FormationPolicy | None = None

    @field_validator("map_id", "map_name")
    @classmethod
    def names_not_blank(cls, value: str, info: object) -> str:
        if not value.strip():
            raise ValueError("map identifiers and names must not be blank")
        return value

    @field_validator("zone_hysteresis_distance")
    @classmethod
    def zone_hysteresis_is_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("zone hysteresis distance must be finite")
        return value

    @model_validator(mode="after")
    def validated_geometry_is_complete(self) -> MapDefinition:
        zone_ids = [zone.zone_id for zone in self.named_zones]
        if len(zone_ids) != len(set(zone_ids)):
            raise ValueError("named zone IDs must be unique")
        if self.geometry_status == "validated":
            if not self.walkable_areas:
                raise ValueError("validated maps require walkable-area polygons")
            if not self.site_polygons:
                raise ValueError("validated maps require site polygons")
            if not self.spawn_polygons:
                raise ValueError("validated maps require spawn polygons")
            if not self.named_zones:
                raise ValueError("validated maps require named-zone polygons")
            if not self.orientation_rules:
                raise ValueError("validated maps require orientation rules")
            if self.registration_thresholds is None:
                raise ValueError("validated maps require registration thresholds")
        return self

    def zone_at(self, point: NormalizedPoint) -> str | None:
        """Return first declared matching zone; overlaps are resolved by config order."""
        if self.geometry_status != "validated":
            return None
        return next(
            (zone.zone_id for zone in self.named_zones if zone.polygon.contains(point)),
            None,
        )


def _point_on_segment(
    point: NormalizedPoint, first: NormalizedPoint, second: NormalizedPoint
) -> bool:
    cross = (point.x - first.x) * (second.y - first.y) - (point.y - first.y) * (second.x - first.x)
    if not math.isclose(cross, 0.0, abs_tol=1e-12):
        return False
    return min(first.x, second.x) <= point.x <= max(first.x, second.x) and min(
        first.y, second.y
    ) <= point.y <= max(first.y, second.y)
