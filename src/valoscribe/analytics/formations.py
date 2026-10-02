"""Deterministic formation labels from explicit five-player spatial evidence."""

from __future__ import annotations

import math
from itertools import combinations

from valoscribe.maps.config import MapDefinition
from valoscribe.types.persistent import (
    FormationLabel,
    FormationObservation,
    FormationObservationResult,
)


class DeterministicFormationEngine:
    """Classify a single five-player snapshot using an explicit map policy."""

    def __init__(self, map_definition: MapDefinition) -> None:
        self.map_definition = map_definition

    def observe(self, observation: FormationObservation) -> FormationObservationResult:
        """Classify one snapshot; incomplete/conflicting evidence fails closed."""
        definition = self.map_definition
        policy = definition.formation_policy
        evidence = [f"formation_snapshot:{observation.team_id}:{observation.vod_timestamp_s}"]
        diagnostics: list[str] = []
        if observation.map_id != definition.map_id:
            diagnostics.append("map_id_mismatch")
        if policy is None:
            diagnostics.append("formation_policy_missing")
        if definition.geometry_status != "validated":
            diagnostics.append("map_geometry_not_validated")
        if observation.conflicting_signals:
            diagnostics.append("conflicting_signals")
        ids = [player.player_id for player in observation.players]
        if len(ids) != 5 or len(set(ids)) != 5:
            diagnostics.append("five_unique_players_required")
        if any(not player.evidence for player in observation.players):
            diagnostics.append("player_evidence_missing")
        if observation.spike_position is not None and not observation.spike_evidence:
            diagnostics.append("spike_evidence_missing")
        if diagnostics or policy is None:
            return self._result(
                observation,
                FormationLabel.UNKNOWN_FORMATION,
                0.0,
                evidence + diagnostics,
                diagnostics,
            )

        zones = [definition.zone_at(player.position) for player in observation.players]
        if any(zone is None for zone in zones):
            diagnostics.append("player_zone_unresolved")
        spike_zone = (
            definition.zone_at(observation.spike_position)
            if observation.spike_position is not None
            else None
        )
        if observation.spike_position is not None and spike_zone is None:
            diagnostics.append("spike_zone_unresolved")
        if diagnostics:
            return self._result(
                observation,
                FormationLabel.UNKNOWN_FORMATION,
                0.0,
                evidence + diagnostics,
                diagnostics,
            )

        zone_counts: dict[str, int] = {}
        for zone in zones:
            assert zone is not None
            zone_counts[zone] = zone_counts.get(zone, 0) + 1
        distances = [
            math.dist((a.position.x, a.position.y), (b.position.x, b.position.y))
            for a, b in combinations(observation.players, 2)
        ]
        lane_set = set(policy.lane_zone_ids)
        occupied_lanes = sorted({zone for zone in zones if zone in lane_set})
        cluster_sizes = self._cluster_sizes(observation, policy.split_distance)
        group_cluster_sizes = self._cluster_sizes(observation, policy.group_distance)
        exact_cluster_sizes = cluster_sizes

        label = FormationLabel.UNKNOWN_FORMATION
        rule_evidence = "rule:unknown_insufficient_shape_evidence"
        site_occupancy = sum(zone_counts.get(zone, 0) for zone in policy.site_zone_ids)
        if (
            spike_zone in policy.site_zone_ids
            and site_occupancy >= policy.site_stack_minimum
        ):
            label, rule_evidence = FormationLabel.SITE_STACK, "rule:site_stack"
        elif self._has_cluster_sizes(group_cluster_sizes, [5]):
            label, rule_evidence = FormationLabel.FIVE_MAN_GROUP, "rule:five_man_group"
        elif self._has_cluster_sizes(exact_cluster_sizes, [4, 1]):
            label, rule_evidence = FormationLabel.FOUR_ONE_LURK, "rule:four_one_lurk"
        elif self._has_cluster_sizes(exact_cluster_sizes, [3, 2]):
            label, rule_evidence = FormationLabel.THREE_TWO_SPLIT, "rule:three_two_split"
        elif self._has_cluster_sizes(exact_cluster_sizes, [2, 2, 1]):
            label, rule_evidence = FormationLabel.TWO_ONE_TWO_DEFAULT, "rule:two_one_two_default"
        elif self._has_cluster_sizes(exact_cluster_sizes, [3, 1, 1]):
            label, rule_evidence = (
                FormationLabel.THREE_ONE_ONE_DEFAULT,
                "rule:three_one_one_default",
            )
        elif max(distances) >= policy.spread_distance and min(distances) > policy.group_distance:
            label, rule_evidence = FormationLabel.SPREAD_DEFAULT, "rule:spread_default"
        confidence = (
            0.75
            if label not in (FormationLabel.SPREAD_DEFAULT, FormationLabel.UNKNOWN_FORMATION)
            else 0.5 if label is FormationLabel.SPREAD_DEFAULT else 0.0
        )
        evidence.extend(
            [rule_evidence, f"map_config:{definition.map_id}:{definition.schema_version}"]
        )
        for player in observation.players:
            evidence.extend(player.evidence)
        evidence.extend(observation.spike_evidence)
        return self._result(
            observation,
            label,
            confidence,
            evidence,
            [],
            zone_counts,
            occupied_lanes,
            distances,
            spike_zone,
        )

    @staticmethod
    def _cluster_sizes(observation: FormationObservation, threshold: float) -> list[int]:
        """Return deterministic complete-link clusters at the configured cutoff."""
        points = sorted(
            (player.position.x, player.position.y) for player in observation.players
        )
        clusters: list[list[tuple[float, float]]] = [[point] for point in points]
        while True:
            eligible: list[tuple[float, int, int]] = []
            for left, right in combinations(range(len(clusters)), 2):
                maximum_distance = max(
                    math.dist(a, b) for a in clusters[left] for b in clusters[right]
                )
                if maximum_distance <= threshold:
                    eligible.append((maximum_distance, left, right))
            if not eligible:
                break
            _, left, right = min(eligible)
            clusters[left] = sorted(clusters[left] + clusters[right])
            del clusters[right]
        return sorted((len(cluster) for cluster in clusters), reverse=True)

    @staticmethod
    def _has_cluster_sizes(actual: list[int], expected: list[int]) -> bool:
        """Require an exact partition, including all singleton clusters."""
        return actual == sorted(expected, reverse=True)

    @staticmethod
    def _result(
        observation: FormationObservation,
        label: FormationLabel,
        confidence: float,
        evidence: list[str],
        diagnostics: list[str],
        zone_occupancy: dict[str, int] | None = None,
        occupied_lanes: list[str] | None = None,
        pairwise_distances: list[float] | None = None,
        spike_zone_id: str | None = None,
    ) -> FormationObservationResult:
        return FormationObservationResult(
            match_id=observation.match_id,
            map_id=observation.map_id,
            round_id=observation.round_id,
            team_id=observation.team_id,
            vod_timestamp_s=observation.vod_timestamp_s,
            formation=label,
            confidence=confidence,
            evidence=list(dict.fromkeys(evidence)),
            diagnostics=diagnostics,
            zone_occupancy=zone_occupancy or {},
            occupied_lanes=occupied_lanes or [],
            pairwise_distances=pairwise_distances or [],
            spike_zone_id=spike_zone_id,
        )
