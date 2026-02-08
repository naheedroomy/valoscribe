# Valoscribe Architecture Guide

> A comprehensive reference for AI agents and developers working on this codebase.

## 1. What Valoscribe Does

Valoscribe is a **computer vision pipeline** that converts Valorant esports VOD (Video on Demand) recordings into structured game event data. It processes 1080p broadcast footage frame-by-frame, extracting:

- **Discrete events**: kills, deaths, ability usage, ultimate usage, spike plants, round starts/ends, match start/end
- **Per-frame state**: health, armor, ability charges, ultimate charge, alive/dead status for all 10 players
- **Match metadata**: teams, players, agents, maps, starting sides (scraped from VLR.gg)

There are **no LLM/AI API calls** anywhere in the pipeline. All detection is pure computer vision: template matching, blob detection, and Tesseract OCR.

The system is tested on **VCT Champions 2025** broadcasts and processes at ~4 FPS (sampling rate), taking 20-40 minutes per map on a 14-core MacBook Pro.

---

## 2. Project Layout

```
valoscribe/
├── src/valoscribe/                  # Main Python package
│   ├── __main__.py                  # CLI entry point (Typer app)
│   ├── types/                       # Pydantic data models
│   │   ├── detections.py            # Detection result models (12 classes)
│   │   └── video.py                 # Video metadata models (2 classes)
│   ├── video/                       # Video I/O
│   │   ├── reader.py                # Frame iterator with FPS filtering
│   │   └── youtube.py               # yt-dlp download wrapper
│   ├── scraper/                     # Web scraping
│   │   └── vlr_scraper.py           # VLR.gg match metadata extraction
│   ├── detectors/                   # Computer vision detectors (15 modules)
│   │   ├── cropper.py               # HUD region extraction from frames
│   │   ├── template_timer_detector.py
│   │   ├── template_score_detector.py
│   │   ├── template_spike_detector.py
│   │   ├── template_health_detector.py
│   │   ├── template_armor_detector.py
│   │   ├── template_credits_detector.py
│   │   ├── template_agent_detector.py      # Preround agent detection
│   │   ├── active_round_agent_detector.py  # In-round agent detection
│   │   ├── ability_detector.py             # In-round ability charges
│   │   ├── preround_ability_detector.py    # Preround ability charges
│   │   ├── ultimate_detector.py            # In-round ultimate charges
│   │   ├── preround_ultimate_detector.py   # Preround ultimate charges
│   │   ├── preround_credits_detector.py    # Credits icon (preround indicator)
│   │   ├── killfeed_detector.py            # Kill event detection from killfeed
│   │   └── round_detector.py               # Round number OCR
│   ├── orchestration/               # Core state management (10 modules)
│   │   ├── game_state_manager.py    # Main orchestrator (1787 lines)
│   │   ├── phase_detector.py        # Game phase state machine
│   │   ├── round_manager.py         # Round/score/side tracking
│   │   ├── player_state_tracker.py  # Per-player state (10 instances)
│   │   ├── state_validator.py       # Transition validation & event generation
│   │   ├── event_collector.py       # Event aggregation & deduplication
│   │   ├── output_writer.py         # CSV + JSONL file writing
│   │   ├── timer_manager.py         # Game/spike/post-round timers
│   │   ├── detector_registry.py     # Detector initialization & access
│   │   └── killfeed_deduplicator.py # Kill deduplication (5s window)
│   ├── commands/                    # CLI command implementations
│   │   ├── orchestrate.py           # `process-vod` command
│   │   ├── detect.py                # Individual detector test commands
│   │   ├── scrape.py                # `scrape-vlr` command
│   │   └── utils.py                 # Utility commands (download, etc.)
│   ├── config/                      # HUD coordinate configs
│   │   ├── champs2025.json          # Champions 2025 HUD layout
│   │   ├── champs2025_opening_games.json
│   │   └── agents_champs2025.json   # Agent ability specifications
│   ├── templates/                   # Template image assets
│   │   ├── preround_agents/{attack,defense}/  # Agent portraits
│   │   ├── killfeed_agents/{attack,defense}/  # Killfeed agent icons
│   │   ├── score_digits/            # 0-9 digit templates
│   │   ├── timer_digits/            # 0-9 digit templates
│   │   ├── health_digits/           # Health value templates
│   │   ├── armor/                   # Armor templates
│   │   ├── credits/                 # Credit icon templates
│   │   ├── spike/                   # Spike status templates
│   │   └── abilities/              # Ability status templates
│   └── utils/                       # Shared utilities
│       ├── logger.py                # Logging setup
│       ├── ocr.py                   # Tesseract OCR wrapper
│       ├── validate_event_logs.py   # Post-processing validation
│       └── remove_final_round_end.py
├── tests/                           # Pytest test suite
├── scripts/                         # Shell scripts for batch processing
│   ├── process_vlr_series.sh        # Full pipeline: VLR URL -> outputs
│   ├── process_all_series_parallel.sh  # Parallel batch processing
│   ├── process_single_map.sh        # Single map processing
│   └── validate_event_logs.sh       # Batch validation
├── analysis/                        # Analysis scripts & outputs
├── series_output/                   # Processed match outputs
├── pyproject.toml                   # Project config & dependencies
└── README.md                        # User-facing documentation
```

---

## 3. End-to-End Data Flow

```
┌─────────────────────────────────────────────────────────────────┐
│ INPUT: VLR.gg Match URL                                         │
│   e.g. https://www.vlr.gg/542272/...                           │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│ STEP 1: VLR Scraping (vlr_scraper.py)                           │
│   - Extracts teams, players, agents, maps, VOD URLs             │
│   - Determines starting sides (attack/defense)                  │
│   - Output: series_metadata.json → split into per-map JSONs     │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│ STEP 2: YouTube Download (video/youtube.py)                     │
│   - Downloads VOD at 1080p using yt-dlp                         │
│   - Supports timestamp-based trimming (?t=2683)                 │
│   - Output: MP4 file on disk                                    │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│ STEP 3: Frame-by-Frame Processing (GameStateManager)            │
│                                                                 │
│   VideoReader iterates frames at 4 FPS                          │
│        │                                                        │
│        ▼                                                        │
│   For each frame:                                               │
│     1. PhaseDetector → determine game phase                     │
│     2. Route to phase handler (preround/active/post_round)      │
│     3. Run detectors via DetectorRegistry                       │
│     4. Update PlayerStateTrackers (×10)                         │
│     5. StateValidator → generate events                         │
│     6. EventCollector → aggregate & deduplicate                 │
│     7. OutputWriter → write to CSV + JSONL                      │
│                                                                 │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│ OUTPUT:                                                          │
│   event_log.jsonl  - Timestamped discrete events (~200-850/map) │
│   frame_states.csv - Per-frame player states (~2000-5000/map)   │
│   metadata.json    - Match metadata from VLR.gg                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 4. The Phase State Machine

The `PhaseDetector` (`orchestration/phase_detector.py`) classifies each frame into one of four phases. Detection routing depends entirely on the current phase.

```
                    ┌───────────┐
                    │ NON_GAME  │  Timer not parseable, no spike
                    └─────┬─────┘
                          │ timer becomes parseable
                          ▼
                    ┌───────────┐
            ┌──────│ PREROUND  │◄──────────────────────┐
            │      └─────┬─────┘                        │
            │            │ credits icon disappears       │
            │            │ + timer visible               │
            │            ▼                               │
            │   ┌──────────────┐                         │
            │   │ ACTIVE_ROUND │                         │
            │   └──────┬───────┘                         │
            │          │ score changes                   │
            │          ▼                                 │
            │   ┌──────────────┐                         │
            │   │  POST_ROUND  │─────────────────────────┘
            │   └──────────────┘  credits icon appears
            │          │           (next preround)
            └──────────┘
```

**Phase detection logic** (in order):
1. Check spike planted → if yes, cannot be PREROUND
2. Check timer → if not parseable AND no spike → `NON_GAME`
3. Check credits icon → if visible → `PREROUND`
4. Check score change → if changed during ACTIVE_ROUND → `POST_ROUND`
5. If timer > 70s while in POST_ROUND → new `ACTIVE_ROUND`
6. Default: `ACTIVE_ROUND` (requires score detection)

**What happens in each phase:**

| Phase | Detections Run | Events Generated |
|-------|---------------|-----------------|
| `PREROUND` | Agent identification, abilities, ultimates, score (retroactive round_end) | round_start (on transition to ACTIVE_ROUND) |
| `ACTIVE_ROUND` | Health, armor, abilities, ultimates, killfeed, spike | kill, death, ability_used, ability_recharged, ultimate_used, spike_plant |
| `POST_ROUND` | Health, armor, abilities, ultimates, killfeed, score | round_end, match_end, kill, death |
| `NON_GAME` | Nothing | Nothing (frame skipped entirely) |

---

## 5. Key Classes and Their Responsibilities

### 5.1 GameStateManager (`orchestration/game_state_manager.py`)

The **central orchestrator**. Coordinates all other components.

**Constructor args:**
- `video_path` - Path to MP4 file
- `vlr_metadata` - Dict from VLR scraper (teams, players, agents, starting sides)
- `output_dir` - Where to write event_log.jsonl and frame_states.csv
- `config_path` - Optional HUD config override (default: champs2025.json)
- `fps` - Processing frame rate (default: 4.0)
- `debug_player_filter` - Optional player index (0-9) to filter debug logs

**Key methods:**
- `process_video()` - Main loop: iterates frames, calls `process_frame()`, finalizes
- `process_frame(timestamp, frame)` - Processes one frame: phase detection → route to handler → write output
- `_process_preround()` - Detects agents (lazy init of player trackers), updates abilities/ultimates
- `_process_active_round()` - Detects player states, killfeed, spike plant
- `_process_post_round()` - Detects score changes, generates round_end/match_end
- `_finalize_events()` - Infers missing round_end/match_end when VOD ends early
- `_initialize_player_trackers_from_agents()` - Maps detected agents to VLR metadata players

**Critical behavior:**
- Player trackers are **lazily initialized** on the first preround where all 10 agents are detected
- Match ends when one team reaches 13+ rounds with 2+ round lead
- After match_end, processes 5 more frames then raises `StopIteration`
- Kill validation requires: correct sides, victim is dead in UI, victim not already killed this round

### 5.2 PhaseDetector (`orchestration/phase_detector.py`)

State machine that classifies frames. See Section 4 above.

**Returns:** `(Phase, detections_dict)` where detections_dict contains timer, spike, score, preround_credits.

### 5.3 RoundManager (`orchestration/round_manager.py`)

Tracks rounds, scores, and side swaps.

**Key state:**
- `current_round` - Round number (starts at 0, incremented to 1 on first round)
- `current_score` - `{"team1": int, "team2": int}`
- `team_names` - `[left_team_name, right_team_name]` (reordered to match screen position)
- `starting_sides` - `{"team1": "attack"|"defense", "team2": "attack"|"defense"}`

**Side swap logic** in `get_current_sides()`:
- Rounds 1-12: original starting sides
- Rounds 13-24: swapped sides (halftime)
- Rounds 25+: overtime, swap every round starting from original

**Important:** `team_names[0]` = left side of screen (positions 0-4), `team_names[1]` = right side (positions 5-9). This mapping is fixed after initialization and does NOT change at halftime - only the attack/defense roles swap.

### 5.4 PlayerStateTracker (`orchestration/player_state_tracker.py`)

Tracks state for a **single player** (10 instances created, one per player position 0-9).

**State dict fields:**
```python
{
    "alive": bool,       # True at round start
    "health": int|None,  # 0-150, None = not detected
    "armor": int|None,   # 0-50
    "ability_1": int|None,  # Charge count
    "ability_2": int|None,
    "ability_3": int|None,
    "ultimate": {"charges": int, "is_full": bool} | None,
    "killer": str|None,  # Agent name of killer (prevents duplicate kill events)
}
```

**Key constants:**
- `REVIVAL_THRESHOLD = 3` - Consecutive alive detections needed to confirm revival
- `DEATH_THRESHOLD = 2` - Consecutive None health detections to confirm death
- `ROUND_START_GRACE_PERIOD = 2.0` - Seconds after round start where deaths are suppressed (UI fade-in)

**Ability validation:** Rejects detections exceeding `max_charges` from agent config, and rejects charge increases on non-rechargeable abilities.

### 5.5 StateValidator (`orchestration/state_validator.py`)

Compares current vs previous player state and generates events.

**Events generated:**
- `revival` - dead → alive transition (only if team has Sage)
- `ability_used` - ability charges decreased (with 2-frame confirmation)
- `ability_recharged` - ability charges increased (only if ability is rechargeable)
- `ultimate_used` - ultimate went from full → not full

**2-frame confirmation for abilities:** A change must persist for 2 consecutive frames before an event fires. This prevents false events during UI transitions (death animations, etc.). The event timestamp uses the **first** detection time, not the confirmation frame.

### 5.6 DetectorRegistry (`orchestration/detector_registry.py`)

Factory that initializes all detectors with shared dependencies (Cropper, OCREngine).

**Detector groups:**
- Template detectors: timer, score, spike, health, armor
- OCR detectors: round
- Preround detectors: credits, agent, ability, ultimate
- In-round detectors: agent, ability, ultimate
- Killfeed detector (reinitialized after first preround with known agent list)

### 5.7 EventCollector (`orchestration/event_collector.py`)

Aggregates events from all sources. Handles killfeed deduplication via `KillfeedDeduplicator`.

**Kill deduplication:** Uses a 5-second sliding window. Kill signature = `(killer_agent, killer_side, victim_agent, victim_side)`. Same signature within 5s is deduplicated.

### 5.8 OutputWriter (`orchestration/output_writer.py`)

Writes two output files incrementally (context manager for file handles):

- **frame_states.csv** - Written every frame. 119 columns: 9 game state + 11 per player x 10 players
- **event_log.jsonl** - Written whenever new events accumulate. One JSON object per line.

### 5.9 TimerManager (`orchestration/timer_manager.py`)

Calculates three timer values per frame:
- `game_timer` - Visible round countdown (from detector, only pre-spike in ACTIVE_ROUND)
- `spike_timer` - Seconds since spike plant (calculated, stops in POST_ROUND)
- `post_round_timer` - Seconds since round end (calculated, only in POST_ROUND)

### 5.10 Cropper (`detectors/cropper.py`)

Extracts pixel regions from 1080p frames based on JSON config coordinates. The config file (`champs2025.json`) defines exact pixel coordinates for every UI element: score display, timer, spike indicator, 10 player scoreboard slots (each with health, armor, ability, ultimate sub-regions), and killfeed.

---

## 6. Detection Methods

All detection is pure computer vision. Three techniques are used:

### 6.1 Template Matching

Used for: agents, score digits, timer digits, spike, health digits, armor, credits

**How it works:** Pre-captured template images are matched against cropped frame regions using OpenCV's `cv2.matchTemplate()`. Best match above a confidence threshold is accepted.

**Agent detection specifics:**
- Separate templates for attack and defense visual styles (color differences)
- Preround uses larger portraits; in-round uses smaller scoreboard icons
- After first detection, `set_agent_filter()` limits search to only the 10 agents in play
- Greyscale fallback for dead player icons

### 6.2 Blob Detection

Used for: ability charges, ultimate charges

**How it works:** Detects bright dots/segments in cropped regions. Count of detected blobs = number of charges.

**Ultimate detection** is two-stage:
1. Check if ultimate is "full" by measuring white pixel density in the ultimate ring region
2. If not full, count individual charge segments via blob detection

### 6.3 OCR (Tesseract)

Used for: round number, health values, armor values

**OCR wrapper** (`utils/ocr.py`): `OCREngine` class with preprocessing (upscaling, adaptive thresholding, denoising) and multiple PSM modes (single line, digits only, single character).

### 6.4 Killfeed Detection

The killfeed detector (`detectors/killfeed_detector.py`) uses a specialized approach:
1. Crops the killfeed region (top-right of screen, up to 6 entries)
2. For each entry, template-matches killer agent icon (attack/defense variants) on the left
3. Template-matches victim agent icon (horizontally flipped templates) on the right
4. Returns all candidate (killer, victim) pairs sorted by confidence
5. `GameStateManager` validates candidates: correct sides, victim dead, victim not already killed

---

## 7. Player Initialization & Team Matching

This is one of the most complex parts of the system. Happens once during the first preround.

**Process (`_initialize_player_trackers_from_agents`):**

1. Detect all 10 agent icons in preround scoreboard (positions 0-9)
2. Detect attack/defense visual style for each (determines side)
3. Left side (positions 0-4) = one team, right side (5-9) = other team
4. Majority vote on each side determines which side is attacking/defending
5. Match to VLR metadata using `starting_side` field
6. Create `PlayerStateTracker` for each position, matched to player name from VLR data
7. Reorder `RoundManager.team_names` to match screen positions if needed
8. Initialize killfeed detector with known agent list (performance optimization)
9. Cache which teams have Sage (for revival validation)

**After initialization:**
- Player indices 0-4 are ALWAYS the left-side team, 5-9 are ALWAYS the right-side team
- This screen-position mapping is fixed for the entire match
- Only the attack/defense roles swap at halftime (handled by `RoundManager.get_current_sides()`)

---

## 8. Event Types & Schemas

### 8.1 match_start
```json
{
    "type": "match_start",
    "timestamp": 16.58,
    "team1": "RED Canids",
    "team2": "Six Karma",
    "timers": {"game_timer": null, "spike_timer": null, "post_round_timer": null}
}
```
Emitted once, when round 1 transitions from PREROUND to ACTIVE_ROUND.

### 8.2 round_start
```json
{
    "type": "round_start",
    "timestamp": 16.58,
    "round_number": 1,
    "score_team1": 0,
    "score_team2": 0,
    "timers": {"game_timer": null, "spike_timer": null, "post_round_timer": null}
}
```
Emitted on PREROUND → ACTIVE_ROUND transition.

### 8.3 round_end
```json
{
    "type": "round_end",
    "timestamp": 125.79,
    "round_number": 1,
    "winner": "RED Canids",
    "score_team1": 1,
    "score_team2": 0,
    "timers": {"game_timer": null, "spike_timer": null, "post_round_timer": 0.0}
}
```
Emitted when score change detected in POST_ROUND. Winner is actual team name (not "team1"/"team2").

### 8.4 kill
```json
{
    "type": "kill",
    "timestamp": 27.09,
    "killer_agent": "neon",
    "killer_side": "defense",
    "victim_agent": "sova",
    "victim_side": "attack",
    "confidence": 0.917,
    "weapon": null,
    "killer_name": "maestr0",
    "killer_team": "RED Canids",
    "victim_name": "Peloncito",
    "victim_team": "Six Karma",
    "timers": {"game_timer": 89.0, "spike_timer": null, "post_round_timer": null}
}
```
From killfeed detection. `weapon` is always null (TODO). `confidence` is template match score.

### 8.5 death
```json
{
    "type": "death",
    "timestamp": 18.92,
    "player": "Jow",
    "team": "Six Karma",
    "agent": "yoru",
    "player_index": 9,
    "timers": {"game_timer": 97.0, "spike_timer": null, "post_round_timer": null}
}
```
From health detection (player's agent icon disappears or health drops to 0). Independent of killfeed.

### 8.6 ability_used
```json
{
    "type": "ability_used",
    "timestamp": 17.75,
    "player": "RgLMeister",
    "team": "RED Canids",
    "agent": "omen",
    "ability": "dark cover",
    "charges_used": 1,
    "remaining_charges": 1,
    "timers": {"game_timer": 98.0, "spike_timer": null, "post_round_timer": null}
}
```

### 8.7 ability_recharged
```json
{
    "type": "ability_recharged",
    "timestamp": 47.65,
    "player": "RgLMeister",
    "team": "RED Canids",
    "agent": "omen",
    "ability": "dark cover",
    "charges_gained": 1,
    "total_charges": 1,
    "timers": {"game_timer": null, "spike_timer": 1.40, "post_round_timer": null}
}
```
Only for rechargeable abilities (as defined in `agents_champs2025.json`).

### 8.8 ultimate_used
```json
{
    "type": "ultimate_used",
    "timestamp": 2511.78,
    "player": "otaQ",
    "team": "Six Karma",
    "agent": "omen",
    "previous_charges": 7,
    "current_charges": 0,
    "ultimate": "from the shadows",
    "timers": {"game_timer": 87.0, "spike_timer": null, "post_round_timer": null}
}
```
Detected when ultimate transitions from full → not full.

### 8.9 spike_plant
```json
{
    "type": "spike_plant",
    "timestamp": 46.48,
    "timers": {"game_timer": null, "spike_timer": 0.0, "post_round_timer": null}
}
```

### 8.10 revival
```json
{
    "type": "revival",
    "timestamp": 150.0,
    "player": "PlayerName",
    "team": "TeamName",
    "agent": "sage",
    "timers": {"game_timer": 75.0, "spike_timer": null, "post_round_timer": null}
}
```
Only possible if the player's team has Sage. Requires 3 consecutive alive detections.

### 8.11 match_end
```json
{
    "type": "match_end",
    "timestamp": 2525.79,
    "winner": "Six Karma",
    "final_score_team1": 7,
    "final_score_team2": 13,
    "team1": "RED Canids",
    "team2": "Six Karma",
    "timers": {"game_timer": null, "spike_timer": null, "post_round_timer": 0.0}
}
```
Emitted when a team reaches 13+ rounds with 2+ round lead, or retroactively by `_finalize_events()`.

---

## 9. CSV Frame State Schema

**File:** `frame_states.csv`

**Core columns (9):**
| Column | Type | Description |
|--------|------|-------------|
| `timestamp` | float | Video timestamp in seconds |
| `frame_number` | int | Sequential frame index |
| `phase` | str | `PREROUND`, `ACTIVE_ROUND`, or `POST_ROUND` |
| `round_number` | int | Current round (1-24+) |
| `score_team1` | int | Left team score |
| `score_team2` | int | Right team score |
| `game_timer` | float\|empty | Round countdown timer |
| `spike_timer` | float\|empty | Seconds since spike plant |
| `post_round_timer` | float\|empty | Seconds since round end |

**Per-player columns (11 x 10 players = 110):**
| Column Pattern | Type | Description |
|---------------|------|-------------|
| `player_{i}_name` | str | Player name from VLR |
| `player_{i}_team` | str | Team name |
| `player_{i}_agent` | str | Agent name (lowercase) |
| `player_{i}_alive` | bool | Whether player is alive |
| `player_{i}_health` | int\|empty | Health value (0-150) |
| `player_{i}_armor` | int\|empty | Armor value (0-50) |
| `player_{i}_ability_1` | int\|empty | Ability 1 charges |
| `player_{i}_ability_2` | int\|empty | Ability 2 charges |
| `player_{i}_ability_3` | int\|empty | Ability 3 charges |
| `player_{i}_ultimate_charges` | int\|empty | Ultimate charge points (0-8) |
| `player_{i}_ultimate_full` | bool\|empty | Whether ultimate is ready |

Where `i` ranges from 0-9. Players 0-4 are left team, 5-9 are right team.

---

## 10. Configuration Files

### 10.1 HUD Config (`config/champs2025.json`)

Defines pixel coordinates for every UI element in the Champions 2025 broadcast layout. Used by `Cropper` to extract regions from 1080p frames.

**Structure:**
```json
{
    "name": "VCT Champions 2025",
    "resolution": {"width": 1920, "height": 1080},
    "regions": {
        "score_team1": {"x": ..., "y": ..., "width": ..., "height": ...},
        "score_team2": {...},
        "timer": {...},
        "spike": {...},
        "round_number": {...},
        "killfeed": {"x": ..., "y": ..., "width": ..., "height": ..., "entry_height": ..., "max_entries": 6},
        "players": {
            "left": [
                {"health": {...}, "armor": {...}, "agent": {...}, "abilities": [...], "ultimate": {...}, "credits": {...}},
                // ... 5 player slots
            ],
            "right": [
                // ... 5 player slots
            ]
        }
    }
}
```

**Key point for new tournaments:** When the broadcast HUD layout changes, a new config file must be created with updated pixel coordinates. This is the primary adaptation needed.

### 10.2 Agent Config (`config/agents_champs2025.json`)

Defines ability specifications per agent. Used by `StateValidator` and `PlayerStateTracker` for validation.

**Structure:**
```json
{
    "jett": {
        "ability_1": {"name": "cloudburst", "max_charges": 2, "rechargeable": false},
        "ability_2": {"name": "updraft", "max_charges": 1, "rechargeable": false},
        "ability_3": {"name": "tailwind", "max_charges": 1, "rechargeable": true},
        "ultimate": {"name": "blade storm"}
    },
    // ... all agents
}
```

---

## 11. CLI Usage

**Entry point:** `valoscribe` (installed via `uv sync` or `pip install -e .`)

### Primary command (full pipeline):
```bash
valoscribe orchestrate process-vod <video.mp4> <metadata.json> \
    --output ./output \
    --fps 4.0 \
    [--show] [--step] [--debug] [--quiet] \
    [--player 0-9] [--start 10.0] [--end 500.0]
```

### Utility commands:
```bash
valoscribe scrape-vlr <vlr_url>              # Scrape match metadata
valoscribe download <youtube_url>            # Download VOD
valoscribe split-metadata <meta.json> -o .   # Split series metadata into per-map files
valoscribe detect <subcommand>               # Test individual detectors
```

### Shell scripts (batch processing):
```bash
# Full automated pipeline from VLR URL
./scripts/process_vlr_series.sh "https://www.vlr.gg/542272/..."

# Parallel batch processing (reads URLs from matches_part2.txt)
./scripts/process_all_series_parallel.sh

# Single map with existing VOD
./scripts/process_single_map.sh video.mp4 metadata.json ./output

# Validate all outputs
./scripts/validate_event_logs.sh
```

---

## 12. Output Directory Structure

```
series_output/
└── {match_id}_{team1}_vs_{team2}/
    ├── series_metadata.json              # Full series metadata
    ├── metadata/
    │   ├── map1.json                     # Per-map metadata
    │   ├── map2.json
    │   └── map3.json
    ├── map1_{mapname}/
    │   ├── metadata.json                 # Symlink or copy of metadata/map1.json
    │   └── output/
    │       ├── event_log.jsonl           # ~200-850 events
    │       ├── frame_states.csv          # ~2000-5000 rows
    │       └── processing.log           # Full processing log
    ├── map2_{mapname}/
    │   └── output/
    │       └── ...
    └── map3_{mapname}/
        └── output/
            └── ...
```

---

## 13. VLR Metadata Format

The scraper (`scraper/vlr_scraper.py`) produces metadata used throughout the pipeline.

**Per-map metadata (what `process-vod` consumes):**
```json
{
    "map_number": 1,
    "map_name": "Haven",
    "map": "Haven",
    "vod_url": "https://youtu.be/P06cwz5RNk0?t=2683",
    "match_url": "https://www.vlr.gg/556019/...",
    "teams": [
        {
            "name": "RED Canids",
            "starting_side": "defense",
            "players": [
                {"name": "maestr0", "agent": "neon"},
                {"name": "RgLMeister", "agent": "omen"},
                {"name": "prozin", "agent": "breach"},
                {"name": "mazin", "agent": "killjoy"},
                {"name": "heat", "agent": "jett"}
            ]
        },
        {
            "name": "Six Karma",
            "starting_side": "attack",
            "players": [
                {"name": "Peloncito", "agent": "sova"},
                {"name": "otaQ", "agent": "omen"},
                {"name": "Mephisto", "agent": "neon"},
                {"name": "drsjombol", "agent": "omen"},
                {"name": "Jow", "agent": "yoru"}
            ]
        }
    ],
    "players": [
        {"name": "maestr0", "agent": "neon", "team": "RED Canids"},
        // ... all 10 players flattened
    ]
}
```

**Note:** The metadata has both a nested `teams[].players` structure and a flat `players` list. The `GameStateManager` uses `players` for lookup and `teams` for side information.

---

## 14. Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `opencv-python` | >=4.8.0 | Frame reading, template matching, image processing |
| `numpy` | >=1.24.0 | Array operations for image data |
| `pydantic` | >=2.0.0 | Data validation models |
| `typer` | >=0.9.0 | CLI framework |
| `pytesseract` | >=0.3.10 | OCR text extraction (requires system Tesseract) |
| `yt-dlp` | >=2023.0.0 | YouTube video downloading |
| `pillow` | >=10.0.0 | Image format handling |
| `beautifulsoup4` | >=4.12.0 | VLR.gg HTML parsing |
| `requests` | >=2.31.0 | HTTP requests |
| `playwright` | >=1.40.0 | Browser automation for VLR.gg scraping |
| `tqdm` | >=4.66.0 | Progress bars |
| `matplotlib` | >=3.10.8 | Visualization (analysis scripts) |
| `seaborn` | >=0.13.2 | Statistical visualization |

**System requirements:** Tesseract OCR must be installed at the system level (`brew install tesseract` on macOS).

---

## 15. Known Limitations & Edge Cases

1. **1080p only** - Template matching is calibrated for 1920x1080 resolution
2. **Spectator HUD required** - Cannot process POV/player-cam streams
3. **Champions 2025 HUD specific** - New tournaments need new config files with updated pixel coordinates
4. **Broadcast interruptions** - Replays, analyst desk overlays, and tech pauses can cause false detections
5. **Agent-specific quirks** - Astra, Neon, Chamber, Jett, Viper have detection issues documented in README
6. **~13% validation failure rate** - 9/71 maps have round start/end mismatches (usually from replays or tech issues)
7. **Weapon detection not implemented** - `weapon` field in kill events is always null
8. **No spike defuse events** - Only spike_plant is detected; defuse is inferred from round_end
9. **Mirror agent matches** - When both teams play the same agent, killfeed attribution relies on side detection (attack/defense color)
10. **Preround slot ordering** - In preround, player positions change each round (scoreboard rank), requiring agent re-detection to match to correct player tracker

---

## 16. Testing

```bash
# Run all tests
uv run pytest

# Run specific test suite
uv run pytest tests/test_orchestration/
uv run pytest tests/test_detectors/

# Run with verbose output
uv run pytest -v
```

Test structure mirrors source: `tests/test_detectors/`, `tests/test_orchestration/`, `tests/test_utils/`, `tests/test_video/`.

---

## 17. Common Modification Scenarios

### Adding support for a new tournament
1. Capture new template images for the HUD layout
2. Create a new config JSON in `config/` with updated pixel coordinates
3. Update `agents_champs2025.json` if new agents are added
4. Pass `--config new_config.json` to `process-vod`

### Adding a new event type
1. Add detection logic in the appropriate phase handler in `GameStateManager`
2. Add event to `EventCollector` via `add_event()`
3. Add print formatting in `commands/orchestrate.py:_print_event()`
4. Events are automatically written to JSONL by `OutputWriter`

### Adding a new detector
1. Create detector class in `detectors/`
2. Register it in `DetectorRegistry`
3. Call it from the appropriate phase handler in `GameStateManager`

### Modifying validation rules
1. Edit `StateValidator` for event generation rules
2. Edit `PlayerStateTracker._validate_and_update_ability()` for ability constraints
3. Update `agents_champs2025.json` for agent-specific ability configs
