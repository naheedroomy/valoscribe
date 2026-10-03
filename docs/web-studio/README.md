# Valoscribe Esports Web Studio — Living Documentation

This document maintains the active record of what has been implemented, what is currently in progress, how the web studio components function, and how to operate the system.

## 1. Quick Reference & Status

| Milestone / Component | Status | Details |
|---|---|---|
| **Python Tactical Engine (Stage 1 Foundation)** | ✅ **Complete & Merged** | Two-team contracts, round manifests, fail-closed preflight, and `analyze-vod` CLI verified on real 1.8GB VOD with 1,282 tests passing. |
| **Product & Architecture Spec** | ✅ **Complete & Approved** | [`PRODUCT.md`](../../PRODUCT.md) and [`docs/superpowers/specs/2026-10-04-web-studio-tactical-ui-design.md`](../superpowers/specs/2026-10-04-web-studio-tactical-ui-design.md). |
| **Next.js Web Studio Application** | 🏗️ **Under Construction** | Interactive Command Center UI tailored for high-level esports teams. |
| **Interactive 2D Tactical Radar** | ⏳ **Upcoming Task** | Canvas/SVG Ascent minimap, zone polygons, and real-time player positions. |
| **Synchronized Video Player Deck** | ⏳ **Upcoming Task** | Frame-accurate scrub bar with HTTP Range video streaming. |
| **VOD Preflight & Execution Console** | ⏳ **Upcoming Task** | UI controls for `analyze-vod` with live SSE terminal log streaming. |

## 2. Directory Structure

- `web/`: Next.js 15 web application.
  - `src/app/page.tsx`: Main tactical command center dashboard.
  - `src/app/api/`: Subprocess bridge connecting web UI to Python engine.
  - `src/components/`: Modular UI widgets (Radar, VideoDeck, PreflightConfig, Terminal).
- `valoscribe/`: Core Python tactical analysis library and CLI.
- `VOD/`: Tournament video fixtures.
- `configs/examples/`: Grounded round manifests and broadcast calibration profiles.

## 3. How to Run the Web Studio

From repository root:
```bash
cd web
npm install
npm run dev
```
Open [http://localhost:3000](http://localhost:3000) to view the Esports Command Center.

## 4. Work Log & Changelog

- **2026-10-04 (Session 1)**:
  - Completed Stage 1 Foundation: implemented two-team contracts, VOD manifests, preflight engine, and `analyze-vod` CLI. Verified on real 1.8GB VOD fixture and merged to `main`.
  - Moved spec to `specs/finished/VOD_ROUND_RANGE_AND_AGENT_EVIDENCE_SPEC.md` with detailed execution notes.
  - Initialized `PRODUCT.md` per `impeccable` init flow for high-level esports coaching staffs.
  - Designed Next.js 15 Web Studio architecture in `docs/superpowers/specs/2026-10-04-web-studio-tactical-ui-design.md`.
  - Created living documentation in `docs/web-studio/README.md`.
