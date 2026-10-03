# Web Studio Tactical UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Node/Next.js 15 interactive web studio for tier-1 esports coaching staffs to configure, inspect, and run offline VOD tactical reconstruction jobs, explore 2D map radar telemetry, and scrub frame-accurate video synchronized with evidence-backed tactical movement.

**Architecture:** Next.js 15 App Router application in `valoscribe/web/` (symlinked at repo root) with Tailwind CSS v4 and dark esports broadcast HUD styling. Built-in API routes invoke the `valoscribe` Python CLI via a robust subprocess bridge, streaming job progress via Server-Sent Events (SSE) and serving video via HTTP Range streaming. Interactive Canvas/SVG Tactical Radar renders Ascent canonical zones and synchronized player markers.

**Tech Stack:** Next.js 15, React 19, TypeScript, Tailwind CSS v4, Lucide React, Node.js v24 child_process, Pytest, Python 3.10+.

**Spec:** [`valoscribe/docs/superpowers/specs/2026-10-04-web-studio-tactical-ui-design.md`](file:///Users/naheedroomy/Documents/valorant-analyzer/valoscribe/docs/superpowers/specs/2026-10-04-web-studio-tactical-ui-design.md) & [`PRODUCT.md`](file:///Users/naheedroomy/Documents/valorant-analyzer/PRODUCT.md).

## Global Constraints

- Offline first: no external cloud services, analytics, external CDNs, or network APIs.
- Strict fail-closed error handling: UI must clearly surface preflight validation errors (missing rounds, SHA mismatch, unconfirmed status).
- Preserve Valoscribe behavior and existing Python CLI contracts.
- High data density (Impeccable Operate mode): dark obsidian theme (`#080b10`), tournament red (`#ff4655`), radianite emerald (`#10b981`), monospace telemetry.
- Maintain living documentation in `docs/web-studio/README.md`.
- Next.js build (`npm run build`) must pass with zero TypeScript or ESLint errors.

---

### Task 1: Scaffold Next.js 15 Web Application with Tailwind CSS & Esports Theme

**Files:**
- Create: `valoscribe/web/package.json`
- Create: `valoscribe/web/tsconfig.json`
- Create: `valoscribe/web/next.config.ts`
- Create: `valoscribe/web/src/app/globals.css`
- Create: `valoscribe/web/src/app/layout.tsx`
- Create: `valoscribe/web/src/app/page.tsx`

**Interfaces:**
- Produces: Runnable Next.js app with Tailwind CSS dark obsidian esports design tokens.

- [ ] **Step 1: Create package.json and project configuration**

Write `valoscribe/web/package.json` with Next.js 15, React 19, TypeScript, Tailwind CSS v4, `@tailwindcss/postcss`, and `lucide-react`.

- [ ] **Step 2: Run npm install**

Run: `npm install` inside `valoscribe/web/`.
Expected: `package-lock.json` created, `node_modules` populated.

- [ ] **Step 3: Setup Tailwind CSS & Dark Tactical Theme Tokens**

Configure `globals.css` with `@theme` block defining `--color-obsidian: #080b10`, `--color-panel: #0f141c`, `--color-elevated: #161e2a`, `--color-tactical-border: #232f42`, `--color-team-red: #ff4655`, `--color-team-green: #10b981`, `--color-cyan-glow: #06b6d4`, and `--color-amber-alert: #f59e0b`.

- [ ] **Step 4: Create layout and placeholder smoke test page**

Create `src/app/layout.tsx` with dark background and monospace styling, and `src/app/page.tsx` rendering a basic tactical shell header.

- [ ] **Step 5: Verify build passes and commit**

Run: `npm run build` in `valoscribe/web/`.
Expected: Static build successful.
Commit: `git add web/ && git commit -m "feat(web): scaffold Next.js 15 application with esports HUD theme"`

---

### Task 2: TypeScript Data Contracts & Python Bridge API

**Files:**
- Create: `valoscribe/web/src/lib/types.ts`
- Create: `valoscribe/web/src/lib/py-bridge.ts`
- Create: `valoscribe/web/src/app/api/preflight/route.ts`
- Create: `valoscribe/web/src/app/api/manifests/route.ts`

**Interfaces:**
- Consumes: Python CLI `analyze-vod` in `valoscribe/`.
- Produces: API routes `/api/preflight` (POST) and `/api/manifests` (GET).

- [ ] **Step 1: Write TypeScript contract definitions in `src/lib/types.ts`**

Define `VODExecutionPlan`, `ResolvedRoundPlan`, `VODRoundManifest`, `RoundManifestEntry`, `VODBroadcastProfile`, and `PreflightResult` matching Pydantic contracts.

- [ ] **Step 2: Implement Python subprocess bridge in `src/lib/py-bridge.ts`**

Implement `runPreflight(args)` that executes:
`uv run --extra parquet python -m valoscribe tactical analyze-vod ... --preflight`
and captures stdout JSON or parses stderr errors.

- [ ] **Step 3: Implement `/api/preflight` route**

Handle POST requests with validation parameters, invoke `runPreflight`, return 200 with `executionPlan` on success or 400 with actionable error on failure.

- [ ] **Step 4: Implement `/api/manifests` route**

Scan `valoscribe/configs/examples/` for example manifests and profiles, returning pre-populated options for the UI.

- [ ] **Step 5: Test API endpoints and commit**

Run: Node script or automated fetch test against `/api/preflight` using example fixtures.
Commit: `git add web/src/lib/ web/src/app/api/ && git commit -m "feat(web): add tactical contracts and preflight API bridge"`

---

### Task 3: Streaming Job Execution API & Media Streaming Route

**Files:**
- Create: `valoscribe/web/src/app/api/jobs/run/route.ts`
- Create: `valoscribe/web/src/app/api/media/[...path]/route.ts`
- Create: `valoscribe/web/src/app/api/runs/route.ts`

**Interfaces:**
- Consumes: Local VOD files in `VOD/` and run directories in `.local/runs`.
- Produces: SSE streaming for live job runs, HTTP Range video streaming for video players, and run discovery.

- [ ] **Step 1: Implement `/api/jobs/run` with Server-Sent Events (SSE)**

Spawn `uv run --extra parquet python -m valoscribe tactical analyze-vod ... --no-preflight`.
Stream lines of stdout/stderr as SSE `data: <line>\n\n`. Send `event: complete` when process exits.

- [ ] **Step 2: Implement `/api/media/[...path]` with HTTP Range Support**

Read requested file from approved media roots (`../VOD` or `.local/runs`).
Parse `req.headers.get("range")` and respond with `206 Partial Content` (or `200 OK`) and proper `Content-Range`, `Content-Length`, and `video/mp4` MIME type.

- [ ] **Step 3: Implement `/api/runs` route**

Scan `valoscribe/.local/runs` for completed run directories and their `execution-plan.json` or `config.snapshot.yaml`.

- [ ] **Step 4: Verify streaming routes and commit**

Run test verifying range requests and directory scanning.
Commit: `git add web/src/app/api/ && git commit -m "feat(web): add streaming job execution and HTTP range media routes"`

---

### Task 4: Esports Command Header & Preflight Configuration Panel

**Files:**
- Create: `valoscribe/web/src/components/Header.tsx`
- Create: `valoscribe/web/src/components/PreflightConfig.tsx`
- Create: `valoscribe/web/src/components/ExecutionTerminal.tsx`

**Interfaces:**
- Consumes: `/api/manifests`, `/api/preflight`, `/api/jobs/run`.
- Produces: Header bar with match ticker, interactive VOD/round range configurator with preset loading, and live terminal console.

- [ ] **Step 1: Implement `Header.tsx`**

Esports broadcast HUD header:
- Tournament title (`VCT Americas Grand Final - Map 3 Ascent`).
- Team A (`100T`) vs Team B (`LOUD`) badge pill with color accents.
- VOD SHA chip with click-to-copy.
- Preflight Status badge (`PREFLIGHT VERIFIED` or `UNCONFIGURED`).

- [ ] **Step 2: Implement `PreflightConfig.tsx`**

Form inputs:
- Quick Preset selector: "VCT Americas GF Map 3 Ascent".
- VOD path input with detected file size badge.
- Round range sliders/inputs (`fromRound`, `toRound`).
- Round status chip matrix (R1-R15): green for confirmed, amber for unresolved, grey for excluded.
- Team selection and starting side indicators.
- Action button: `[Run Preflight Inspection]`.

- [ ] **Step 3: Implement `ExecutionTerminal.tsx`**

Dark monospace window rendering real-time streaming output from `/api/jobs/run` or formatted JSON execution plans.

- [ ] **Step 4: Verify components build cleanly and commit**

Run: `npm run build` in `valoscribe/web/`.
Commit: `git add web/src/components/ && git commit -m "feat(web): implement esports header, preflight configurator, and terminal"`

---

### Task 5: Interactive 2D Tactical Radar & Zone Occupancy Overlay

**Files:**
- Create: `valoscribe/web/src/lib/ascent-zones.ts`
- Create: `valoscribe/web/src/components/TacticalRadar.tsx`

**Interfaces:**
- Consumes: `ascent.yaml` zone polygons, player observation coordinates.
- Produces: Interactive 2D Canvas/SVG tactical radar with zone overlays, player pips, and occupancy badges.

- [ ] **Step 1: Extract Ascent zone polygon data into `src/lib/ascent-zones.ts`**

Export canonical polygon coordinate arrays for A Site, B Site, Mid Courtyard, Catwalk, Main, Market, and Garden from `configs/maps/ascent.yaml`.

- [ ] **Step 2: Implement `TacticalRadar.tsx` Canvas/SVG Renderer**

- Render canonical Ascent floorplan layout (2048x2048 scaled to container).
- Draw zone polygon boundaries with soft glowing stroke (`#232f42` at rest, `#06b6d4` on hover/active).
- Draw live player marker pips at `(canonical_x, canonical_y)`:
  - Team A: Crimson circles (`#ff4655`) with player index label.
  - Team B: Radiant emerald circles (`#10b981`).
- Zone occupancy badge pills showing real-time player count per zone.
- Hover tooltip showing zone name, players inside, and observation confidence.

- [ ] **Step 3: Verify radar rendering and commit**

Run: `npm run build` in `valoscribe/web/`.
Commit: `git add web/src/lib/ascent-zones.ts web/src/components/TacticalRadar.tsx && git commit -m "feat(web): add interactive 2D tactical radar and zone occupancy overlay"`

---

### Task 6: Video Deck, Synchronized Round Timeline, & Tactical Events Feed

**Files:**
- Create: `valoscribe/web/src/components/VideoDeck.tsx`
- Create: `valoscribe/web/src/components/RoundTimeline.tsx`
- Create: `valoscribe/web/src/components/TacticalEventsFeed.tsx`

**Interfaces:**
- Consumes: Video stream from `/api/media`, round interval specs, and event records.
- Produces: Synced video player, phase-colored timeline scrubber, and evidence-backed events list.

- [ ] **Step 1: Implement `RoundTimeline.tsx`**

- Timeline scrubber tracking `currentTimestamp` within `[source_start_seconds, source_end_seconds]`.
- Phase interval bands:
  - Freeze time (0 to live_start): Grey.
  - Opening Window (live_start to live_start + 8s): Cyan (`#06b6d4`).
  - Mid-round play: Slate.
  - Site Commitment window: Amber (`#f59e0b`).
  - Replay exclusion span: Striped caution bar.
- Playback controls: Play/Pause, 0.5x, 1x, 2x, and step +/- 0.25s.

- [ ] **Step 2: Implement `VideoDeck.tsx`**

HTML5 video player linked to `/api/media/[...path]` syncing currentTime bidirectionally with the timeline scrubber.

- [ ] **Step 3: Implement `TacticalEventsFeed.tsx`**

Chronological list of tactical events:
- Opening distribution tuple (e.g. `1/0/2` with 19 votes).
- Apparent rotations and siteward shifts.
- Apparent site concentrations.
- Exact evidence citation chip: `[E-001; Round 4; 04:23.0]`.

- [ ] **Step 4: Verify components build and commit**

Run: `npm run build` in `valoscribe/web/`.
Commit: `git add web/src/components/ && git commit -m "feat(web): add synchronized video deck, round timeline, and events feed"`

---

### Task 7: Full Web Studio Integration, Build Verification, & Living Docs Update

**Files:**
- Modify: `valoscribe/web/src/app/page.tsx`
- Modify: `docs/web-studio/README.md`
- Create root symlink: `valorant-analyzer/web -> valoscribe/web`

**Interfaces:**
- Consumes: All components from Tasks 1-6.
- Produces: Complete, polished Valoscribe Esports Studio interface.

- [ ] **Step 1: Integrate all components into `src/app/page.tsx`**

Assemble the three-panel layout:
- Top: Header with tournament ticker and match status.
- Left: PreflightConfig panel and ExecutionTerminal.
- Center/Right: TacticalRadar, VideoDeck, RoundTimeline, and TacticalEventsFeed.
- Connect state: Selecting a round in the config updates the timeline, radar, and video deck simultaneously.

- [ ] **Step 2: Create root symlink for convenient access**

Run: `ln -s valoscribe/web web` at repository root.

- [ ] **Step 3: Run comprehensive verification**

Run:
1. `cd valoscribe/web && npm run build` (Must pass cleanly).
2. `cd valoscribe && uv run --extra parquet --extra dev pytest` (Python test suite remains 100% green).
3. `uv run --extra parquet --extra dev ruff check src tests` (Clean).
4. `uv run --extra parquet --extra dev mypy src/valoscribe` (Clean).

- [ ] **Step 4: Update living documentation**

Update `docs/web-studio/README.md` with:
- Detailed breakdown of all implemented components.
- Exact instructions on how pro teams and analysts run the studio.
- Live screenshots/descriptions of radar, timeline, and preflight workflows.

- [ ] **Step 5: Final commit & push**

```bash
git add web/ docs/web-studio/
git commit -m "feat(web): deliver complete Valoscribe Esports Studio interactive web app"
git push origin main
```
