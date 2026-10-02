# Documentation index

## Active source of truth

- [VALORANT MVP Reset v1.0 specification](../specs/active/MVP_RESET_AND_REPOSITORY_CLEANUP_SPEC.md) — the only active implementation specification. It supersedes the earlier broad `PROJECT_SPEC.md` for the current milestone.
- [Project instructions](../AGENTS.md) — scope lock, evidence policy, and required phase order.
- [Provisional root README](../README.md) — setup and verified existing CLI entry point. The MVP workflow is not yet implemented or accepted.

## Current system references

- [Code and configuration layout](architecture/code-layout.md) — canonical Valoscribe module map and config distinction.
- [Minimap calibration](architecture/minimap-calibration.md)
- [Minimap registration](architecture/minimap-registration.md)
- [Ascent map data](architecture/ascent-map-data.md)
- [HUD profiles](architecture/hud-profiles.md)
- [Existing minimap extension ADR](adr/0001-minimap-extension.md)
- [Publishing boundary](architecture/publish-boundary.md)

These documents describe existing or historical capabilities and do not certify MVP real-round acceptance.

## Guides and examples

- `guides/` is reserved for current operational guides. There is no verified end-to-end tactical MVP guide yet.
- [Archived synthetic VTA-704 example](../examples/tactical_mvp/vta704/) is a legacy report example, not real tactical evidence.

## Status and preservation

- [Pre-reset repository inventory](status/pre-reset-repository-inventory.md)
- [2026-10-02 readiness report (historical, unverified against this reset)](status/2026-10-02-full-run-readiness-historical.md)
- [Generated-output hash manifest for relocated Champions artifacts](status/legacy-champs2025-generated-output-manifest.sha256)
- [RST-001/RST-002 cleanup report](status/repository-cleanup-report.md)

## Historical archive

`archive/` retains superseded VTA specifications, plans, status reports, evidence notes, diagnostics, and prior agent prompts for provenance. Archive entries are not current implementation instructions; use the active specification above.

`specs/archive/` retains the prior project specification and superseded milestone plans. Only `specs/active/` contains an active implementation spec.
