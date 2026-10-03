# Web Studio Tactical UI: Architecture & Visual Design Document

- **Status**: Approved by User
- **Date**: 2026-10-04
- **Related Spec**: `valoscribe/specs/finished/VOD_ROUND_RANGE_AND_AGENT_EVIDENCE_SPEC.md`
- **Product Truth**: `PRODUCT.md` (root)
- **Scope**: Node.js / Next.js 15 Interactive Tactical Web Application (Valoscribe Esports Studio)

## 1. Executive Summary & Audience

The **Valoscribe Esports Studio** is an interactive, browser-based command center for tier-1 VALORANT pro coaching staffs and data analysts. It wraps the offline `valoscribe` Python computer vision and tactical movement pipeline in an esports broadcast HUD interface.

The application allows analysts to:
1. Submit local tournament VODs, configure teams, profiles, and round ranges, and run instant preflight verification.
2. Monitor execution jobs in real time with streamed terminal output.
3. Interactively scrub 2D canonical map radar representations synchronized with frame-accurate video playback.
4. Inspect evidence-backed opening distributions, cross-zone rotations, and site commitment clusters.

## 2. System Architecture

```text
valorant-analyzer/
├── PRODUCT.md                                # Root product truth & positioning
├── docs/web-studio/                          # Living documentation for analysts & engineers
│   └── README.md                             # Setup, component status, and API guide
├── valoscribe/                               # Python tactical analysis engine
│   ├── src/valoscribe/tactical/cli.py        # Typer CLI (analyze-vod, inspect, rebuild)
│   ├── configs/examples/                     # Verified manifest & profile JSON fixtures
│   └── .local/runs/                          # Generated tactical run directories
└── web/                                      # Next.js 15 Web Application
    ├── package.json                          # Next.js 15, React 19, Tailwind CSS v4, Lucide
    ├── src/
    │   ├── app/
    │   │   ├── layout.tsx                    # Esports HUD shell (dark theme, fonts)
    │   │   ├── page.tsx                      # Unified Tactical Studio Dashboard
    │   │   └── api/
    │   │       ├── preflight/route.ts        # POST: runs python analyze-vod --preflight
    │   │       ├── jobs/run/route.ts         # POST: streams job execution via SSE
    │   │       ├── manifests/route.ts        # GET: lists available round manifests
    │   │       ├── runs/route.ts             # GET: lists completed runs in .local/runs
    │   │       └── media/[...path]/route.ts  # GET: streams local VOD/MP4s with HTTP Range
    │   ├── components/
    │   │   ├── Header.tsx                    # Match status ticker, VOD SHA pill, and teams
    │   │   ├── PreflightConfig.tsx           # VOD picker, round range scrubber, team select
    │   │   ├── TacticalRadar.tsx             # 2D Interactive SVG/Canvas minimap & zones
    │   │   ├── VideoDeck.tsx                 # Synced video player with frame stepping
    │   │   ├── RoundTimeline.tsx             # Phase-colored scrubber (opening, mid, site)
    │   │   ├── ExecutionTerminal.tsx         # Monospace real-time job log terminal
    │   │   └── TacticalEventsFeed.tsx        # Cited openings, rotations, concentrations
    │   └── lib/
    │       ├── types.ts                      # TypeScript interfaces matching Pydantic models
    │       └── py-bridge.ts                  # Subprocess bridge to valoscribe Python CLI
```

## 3. Data & API Contracts

### 3.1 `POST /api/preflight`
- **Request Body**:
  ```json
  {
    "vodPath": "string",
    "mapName": "ascent",
    "matchId": "string",
    "mapId": "string",
    "fromRound": 4,
    "toRound": 7,
    "team": "100T",
    "profilePath": "string",
    "manifestPath": "string",
    "outputDir": "string",
    "verifySha": true
  }
  ```
- **Response (Success 200)**:
  ```json
  {
    "status": "passed",
    "executionPlan": {
      "match_id": "vct-americas-2024-stage-2-gf",
      "map_id": "map3",
      "selected_team_id": "100T",
      "opponent_team_id": "LOUD",
      "selected_rounds": [ ... ]
    },
    "asciiSummary": "..."
  }
  ```
- **Response (Fail-Closed 400)**:
  ```json
  {
    "status": "failed",
    "error": "Round range [(4, 8)] contains unconfirmed or missing rounds:\n  - Round 8 is missing from the round manifest"
  }
  ```

### 3.2 `POST /api/jobs/run` (Server-Sent Events)
- Streams `text/event-stream` chunks:
  - `event: log\ndata: "Running preflight check..."\n\n`
  - `event: log\ndata: "VOD SHA-256 verified..."\n\n`
  - `event: complete\ndata: {"runDir": ".local/runs/..."}\n\n`

### 3.3 `GET /api/media/[...path]`
- Securely serves `.mp4` and `.png` files from authorized repository paths (`../VOD`, `valoscribe/.local/runs`).
- Supports `Range: bytes=start-end` headers for native seeking and zero-latency frame scrubbing in HTML5 video elements.

## 4. Visual Design Tokens (Impeccable Operate Mode)

Designed to elevate esports analysis to a broadcast-grade command center:

| Token | Value | Role |
|---|---|---|
| `bg-obsidian` | `#080b10` | Root background |
| `bg-panel` | `#0f141c` | Cards & control containers |
| `bg-elevated` | `#161e2a` | Active items, modal overlays |
| `border-tactical`| `#232f42` | Hairline panel borders (1px) |
| `text-primary` | `#f8fafc` | High-contrast headers & values |
| `text-muted` | `#64748b` | Field labels & inactive cues |
| `color-team-a` | `#ff4655` | VALORANT red (100T / Attack) |
| `color-team-b` | `#10b981` | Radianite emerald (LOUD / Defense) |
| `color-cyan` | `#06b6d4` | Live opening window & scrub cursor |
| `color-amber` | `#f59e0b` | Replay gaps & site commitment alert |

### Typography
- **Sans**: `Inter`, system grotesque for labels and hierarchy.
- **Mono**: `JetBrains Mono`, `ui-monospace` with `tabular-nums` for timestamps, SHA digests, and coordinates.

## 5. Key Interactive Workflows

### 5.1 Preflight Configuration & Run Generation
1. Analyst opens studio; default preset loads Ascent Map 3 Grand Finals.
2. Analyst adjusts round range slider (e.g. Rounds 4–7).
3. Clicking **[Run Preflight Inspection]** executes within 2s, updating the round matrix pills (🟢 confirmed, 🟡 unresolved).
4. Clicking **[Generate Run Plan]** streams live logs and serializes the execution plan to disk.

### 5.2 2D Radar & Video Sync Deck
1. Scrubbing the timeline synchronizes the video player and the 2D canvas marker positions simultaneously.
2. Visual phase markers identify the 0–8s opening window, mid-round transition, and site concentration.
3. Zone hover highlights active polygons (A Site, B Site, Mid Courtyard) and lists player counts with deterministic confidence scores.
