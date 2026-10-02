# Code and configuration layout

## Existing canonical source home

The Python package remains `src/valoscribe/`. Existing VTA extensions are organized by responsibility within the package; the reset does not rename the package or rewrite stable upstream Valoscribe modules.

| Responsibility | Existing location |
|---|---|
| CLI and commands | `src/valoscribe/commands/` |
| HUD and selected-color detectors | `src/valoscribe/detectors/` |
| HUD profiles and existing map assets/config | `src/valoscribe/config/` |
| Map definitions, registration and landmarks | `src/valoscribe/maps/`; existing profile/config files remain in `src/valoscribe/config/` |
| Round/scenario analytics | `src/valoscribe/analytics/` |
| Tracking and run artifacts | `src/valoscribe/tracking/` |
| Reporting | `src/valoscribe/reporting/` |
| Pydantic contracts | `src/valoscribe/types/` |
| Video decoding | `src/valoscribe/video/` |
| Tests and reviewed small fixtures | `tests/` |
| Research/maintenance scripts | `scripts/` |

The directories above are the existing VTA source home, not proof that their features meet the reset's real-round acceptance criteria. Existing commands include minimap calibration/anonymous diagnostics and deterministic round analysis; neither is the requested five-round team-movement workflow.

## New MVP work

Keep new implementation under the `valoscribe` package. Use specific modules for the active movement slice and avoid moving stable upstream modules only to imitate a diagram. Keep raw observations, append-only corrections, derived occupancy, and reports distinct as required by the active specification. Team-shape output does not imply identity or tracking support.

The active specification's preferred conceptual package is `valoscribe/tactical/`; establish it only when MVP code is implemented and only for components that need a single cohesive home. Do not create duplicate minimap, map, analytics, or reporting implementations that already exist.

## Configuration distinction

- Existing Valoscribe HUD profiles and their consuming code are under `src/valoscribe/config/`; changing those paths can break runtime lookup or package data.
- Existing map candidate configs and the map asset are also under that package path. Their calibration status remains whatever the committed contract says; moving or renaming them does not validate them.
- The reset's future portable MVP examples belong under top-level `configs/examples/`; map and broadcast data should be separate, with crop/color values in the broadcast/source profile and polygons/thresholds in map configuration.
- Machine-specific absolute paths and run output belong only under ignored `.local/configs/` and `.local/runs/`. Never commit a local real-VOD path, generated run, or credential.

The top-level `configs/` tree is created when the first reviewed MVP configuration is added; RST-002 does not invent production calibration values or empty placeholder configs.
