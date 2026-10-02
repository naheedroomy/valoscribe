# ADR 0001: Extend Valoscribe with an isolated minimap pipeline

- Status: Accepted
- Date: 2026-09-29

## Context

Valoscribe already provides the Python package and CLI, local video frame reading, tournament HUD crop configuration, round-state orchestration, event extraction, and an MIT-licensed foundation. Replacing it would duplicate working ingestion and HUD/event behavior and increase migration risk before the new computer-vision stages are validated.

Minimap analysis has different inputs, outputs, calibration needs, and failure modes from the current HUD detectors. Enabling it must not alter existing Valoscribe processing or output formats by default.

## Decision

Continue the existing Valoscribe fork and preserve its package name, MIT license, existing HUD/event behavior, and output compatibility. Add minimap-specific processing behind new, separately testable modules. Expose the capability through an explicit opt-in CLI command or flag; do not make existing workflows invoke it implicitly. Reuse existing video reading and HUD configuration seams where appropriate rather than duplicating them.

## Consequences

- Existing commands remain the default path and retain their behavior.
- Minimap implementation can be developed and tested independently, with its own configuration and diagnostics.
- Integration is explicit and can be reviewed after its outputs are validated.
- New module boundaries and CLI wiring must avoid coupling existing HUD extraction to minimap availability.

## Alternatives considered

- **Rewrite the application:** rejected because it would replace working video, HUD, and event-processing behavior without a demonstrated need.
- **Integrate minimap detection into existing detectors unconditionally:** rejected because this could change current runtime cost, failure behavior, and outputs for users who did not opt in.
