"""Map configuration validation and geometry lookup tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import cv2
import pytest
from pydantic import ValidationError

from valoscribe.maps.config import MapDefinition, MapPolygon, MapRegistrationThresholds, MapZone
from valoscribe.types.persistent import NormalizedPoint


def point(x: float, y: float) -> NormalizedPoint:
    return NormalizedPoint(x=x, y=y)


def polygon(polygon_id: str, coords: list[tuple[float, float]]) -> MapPolygon:
    return MapPolygon(
        polygon_id=polygon_id,
        vertices=[point(x, y) for x, y in coords],
    )


def validated_map(zones: list[MapZone]) -> MapDefinition:
    return MapDefinition(
        map_id="synthetic-map-v1",
        map_name="Synthetic",
        canonical_minimap={
            "image_url": "https://example.invalid/synthetic.png",
            "sha256": "a" * 64,
            "asset_version": "synthetic-test",
            "patch_version": "not-applicable",
            "provenance": "Synthetic test geometry; no external map data.",
        },
        geometry_status="validated",
        walkable_areas=[polygon("walkable", [(0, 0), (1, 0), (1, 1), (0, 1)])],
        site_polygons=[polygon("site-a", [(0.1, 0.1), (0.3, 0.1), (0.3, 0.3), (0.1, 0.3)])],
        spawn_polygons=[polygon("spawn-a", [(0.7, 0.7), (0.9, 0.7), (0.9, 0.9), (0.7, 0.9)])],
        named_zones=zones,
        orientation_rules=["Synthetic coordinates: origin is top-left."],
        registration_thresholds=MapRegistrationThresholds(
            minimum_confidence=0.8, maximum_alignment_error=0.02
        ),
    )


def test_ascent_source_metadata_loads_without_claiming_unverified_geometry() -> None:
    config_path = Path(__file__).parents[2] / "src/valoscribe/config/ascent_map.json"
    config = MapDefinition.model_validate_json(config_path.read_text(encoding="utf-8"))

    assert config.map_id == "7eaecc1b-4337-bbf6-6ab9-04b8f06b3319"
    assert config.geometry_status == "pending"
    assert config.canonical_minimap.patch_version is None
    assert config.canonical_minimap.asset_version == "Riot Public Content Catalog release 13.06"
    asset_path = config_path.parent / str(config.canonical_minimap.local_asset_path)
    asset_bytes = asset_path.read_bytes()
    assert hashlib.sha256(asset_bytes).hexdigest() == config.canonical_minimap.sha256
    image = cv2.imread(str(asset_path), cv2.IMREAD_UNCHANGED)
    assert image is not None
    assert image.shape == (2048, 2048, 4)
    assert config.walkable_areas == []
    assert [polygon.polygon_id for polygon in config.site_polygons] == [
        "asset-highlight-top",
        "asset-highlight-bottom",
    ]
    assert config.site_polygons[0].vertices == [
        point(551 / 2048, 162 / 2048),
        point(726 / 2048, 162 / 2048),
        point(726 / 2048, 444 / 2048),
        point(551 / 2048, 444 / 2048),
    ]
    assert config.site_polygons[1].vertices == [
        point(426 / 2048, 1502 / 2048),
        point(691 / 2048, 1502 / 2048),
        point(691 / 2048, 1745 / 2048),
        point(426 / 2048, 1745 / 2048),
    ]
    assert config.site_polygons[0].contains(point(0.3, 0.15))
    assert config.site_polygons[1].contains(point(0.27, 0.8))
    assert config.spawn_polygons == []
    assert config.named_zones == []
    assert config.zone_at(point(0.5, 0.5)) is None


def test_zone_lookup_is_deterministic_and_includes_polygon_boundary() -> None:
    first = MapZone(
        zone_id="synthetic-a",
        polygon=polygon("zone-a", [(0.1, 0.1), (0.5, 0.1), (0.5, 0.5), (0.1, 0.5)]),
    )
    overlap = MapZone(
        zone_id="synthetic-overlap",
        polygon=polygon("zone-overlap", [(0.4, 0.4), (0.8, 0.4), (0.8, 0.8), (0.4, 0.8)]),
    )
    config = validated_map([first, overlap])

    assert config.zone_at(point(0.2, 0.2)) == "synthetic-a"
    assert config.zone_at(point(0.5, 0.5)) == "synthetic-a"
    assert config.zone_at(point(0.9, 0.9)) is None


def test_polygon_rejects_out_of_range_and_degenerate_vertices() -> None:
    with pytest.raises(ValidationError):
        polygon("outside", [(-0.1, 0), (1, 0), (1, 1)])
    with pytest.raises(ValidationError, match="non-zero area"):
        polygon("line", [(0.1, 0.1), (0.5, 0.5), (0.9, 0.9)])


def test_validated_map_requires_real_geometry_and_registration_contract() -> None:
    config_path = Path(__file__).parents[2] / "src/valoscribe/config/ascent_map.json"
    pending = json.loads(config_path.read_text(encoding="utf-8"))
    pending["geometry_status"] = "validated"

    with pytest.raises(ValidationError, match="walkable-area polygons"):
        MapDefinition.model_validate(pending)


def test_map_definition_round_trips_to_json_schema() -> None:
    config = validated_map(
        [
            MapZone(
                zone_id="synthetic-a",
                polygon=polygon("zone-a", [(0.1, 0.1), (0.4, 0.1), (0.4, 0.4)]),
            )
        ]
    )

    restored = MapDefinition.model_validate_json(config.model_dump_json())

    assert restored == config
    assert MapDefinition.model_json_schema()["properties"]["geometry_status"]
