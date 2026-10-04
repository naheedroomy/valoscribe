export type TeamSide = "attack" | "defense";
export type RoundStatus = "confirmed" | "unresolved" | "missing" | "excluded";
export interface ExcludedSpan { start_seconds: number; end_seconds: number; reason: string }
export interface TeamManifestDefinition { team_id: string; name: string; starting_side: TeamSide; broadcast_slot: string; broadcast_color_label: string }
export interface RoundManifestEntry {
  map_round: number; round_id: string; source_start_seconds: number; source_end_seconds: number; live_start_seconds: number;
  status: RoundStatus; team_sides: Record<string, TeamSide>; boundary_evidence: string; excluded_spans: ExcludedSpan[];
}
export interface VODRoundManifest {
  schema_version: number; source_video_sha256: string; match_id: string; map_id: string; map_name: string;
  teams: Record<string, TeamManifestDefinition>; halftime_after_round: number; rounds: RoundManifestEntry[];
  reviewer: string; review_method: string; notes?: string | null;
}
export interface CropConfig { x: number; y: number; width: number; height: number; orientation: string }
export interface HSVRange { lower: [number, number, number]; upper: [number, number, number] }
export interface TransformConfig {
  method: string; input_coordinates: string; output_coordinates: string; matrix: number[][]; training_points: number;
  training_residual_mean_rms_max_px: number[]; heldout_max_px: Record<string, number>; calibration_status: string;
}
export interface TeamColorCalibration { team_id: string; color_ranges_hsv: HSVRange[] }
export interface VODBroadcastProfile {
  profile_id: string; calibration_status: string; minimap_crop: CropConfig; transform: TransformConfig;
  team_calibrations: Record<string, TeamColorCalibration>;
}
export interface ResolvedRoundPlan {
  map_round: number; round_id: string; source_interval_seconds: [number, number]; live_start_offset_seconds: number;
  selected_team_side: TeamSide; opponent_team_side: TeamSide; boundary_evidence: string; excluded_intervals: ExcludedSpan[];
}
export interface VODExecutionPlan {
  match_id: string; map_id: string; map_name: string; source_video_path: string; source_video_sha256: string;
  selected_team_id: string; opponent_team_id: string; minimap_crop: CropConfig; transform: TransformConfig;
  selected_team_calibrations: HSVRange[]; opponent_team_calibrations: HSVRange[]; selected_rounds: ResolvedRoundPlan[]; output_dir: string;
}
export interface PreflightResult { status: "passed" | "failed"; executionPlan?: VODExecutionPlan; asciiSummary?: string; error?: string }

export interface PlanOnlyRun {
  match_id: string;
  map_id: string;
  map_name: string;
  source_video_path: string;
  source_video_sha256: string;
  selected_team_id: string;
  opponent_team_id: string;
  selected_rounds: ResolvedRoundPlan[];
  output_dir: string;
}
export type RunKind = "telemetry" | "plan-only" | "config-only";

export interface RunSummary {
  run_id: string; created_at?: string; source_identifier?: string; source_video_sha256?: string; source_dimensions?: [number, number];
  sample_fps?: number; round_ids?: string[]; warnings?: string[]; output_paths?: Record<string, string>;
}
export interface Observation {
  run_id: string; round_id: string; sample_index: number; source_frame_index?: number | null; source_timestamp_seconds: number;
  crop_x?: number; crop_y?: number; canonical_x: number; canonical_y: number; confidence: number;
  detector_version?: string; quality_flags?: string[]; observation_id?: string; team_id?: string;
}
export interface CorrectedObservation extends Observation { source?: "raw" | "corrected"; corrected: boolean; correction_ids: string[]; evidenceNotes?: string[] }
export interface EvidenceRecord { [key: string]: unknown }
