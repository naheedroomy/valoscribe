# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Next.js 15 (App Router, TypeScript, Tailwind CSS), Node.js v24 runtime, integrated API routes to execute and stream `valoscribe` Python CLI tactical jobs (`analyze-vod`, `inspect`), with high-density SVG/Canvas tactical board and minimap telemetry.

## Users

Primary users: Professional VALORANT esports analysts, coaching staff (head coaches, strategic coaches, assistant coaches), and tier-1 pro teams preparing match prep, anti-stratting opponents, and reviewing tournament VODs.

## Product Purpose

Transform offline VALORANT tournament spectator VODs into an interactive tactical analysis studio. Pro teams can submit local broadcast VODs, configure teams and round ranges, run preflight validation, execute tactical reconstruction jobs, and explore verified evidence-backed opponent formations, rotations, and opening shapes.

## Positioning

Unlike generic video review tools or manual drawing boards, this system reconstructs ground-truth spatial movement and anonymous zone occupancies with deterministic confidence and cryptographic evidence hashing, guaranteeing fail-closed integrity for competitive anti-stratting without manual scrubbing or hallucinated inferences.

## Operating Context

High-stakes match preparation, opponent tendency scouting, and post-match review. Analysts work with high-resolution 1080p broadcast VODs, multi-monitor setups, fast keyboard shortcuts, and frame-accurate timeline scrubbing. Needs broadcast-grade aesthetics, dark esports tactical HUD visual language, and crystal-clear data density.

## Capabilities and Constraints

- Capabilities:
  - VOD file selection and SHA-256 integrity inspection.
  - Interactive round-range selection and halftime side-switching verification.
  - Profile and color calibration validation.
  - Live job execution monitoring with streamed execution plan and status.
  - Tactical run inspection, round timeline scrubbing, and minimap playback.
- Constraints:
  - Offline-first execution: no external network/API dependencies.
  - Strict fail-closed verification: missing or unconfirmed rounds halt execution with explicit diagnostic anchors.
  - Grounded deterministic evidence: inferences must be tied to verified timestamps and markers.

## Brand Commitments

- Name: VALORANT Tactical Movement Analyzer (Valoscribe Esports Studio)
- Aesthetic: Dark mode tactical broadcast HUD, precision radar/telemetry visual language, cyber-tactical accents (VALORANT red/radianite green accents on obsidian/slate dark backgrounds), crisp monospace data tables, micro-interactions with mechanical feedback.

## Evidence on Hand

- Validated local tournament VOD fixture: VCT Americas Stage 2 Grand Finals Map 3 Ascent (`YTDown.com_YouTube_Media_4LEGEQ8KBS0...`, 1.8GB, SHA `a2feb25b...`).
- Grounded round manifest for rounds 4, 5, 6, 7, 9 in `configs/examples/ascent-map3-rounds.example.json`.
- Grounded broadcast profile in `configs/examples/ascent-vct-profile.example.json`.
- Fully verified Stage 1 Python CLI (`analyze-vod`) in `valoscribe/`.

## Product Principles

1. **Evidence Before Assertion**: Every tactical pattern, rotation, and opening must be visually inspectable and bound to exact timestamps and confidence.
2. **Speed & Precision for Analysts**: Dense, scan-friendly layouts with zero fluff; keyboard-first navigation and immediate preflight feedback.
3. **Fail-Closed Integrity**: Clear, unambiguous diagnostics when footage is occluded, uncalibrated, or missing rather than silent skips or optimistic guesses.
4. **Esports Broadcast Authority**: Visual hierarchy and styling worthy of tier-1 championship analysis rooms.

## Accessibility & Inclusion

High-contrast dark mode palette (WCAG AA/AAA compliant), distinct iconography alongside color-coding (never relying on color alone for attack/defense or team identification), legible typography scales, and keyboard accessible navigation.
