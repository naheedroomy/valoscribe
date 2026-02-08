# Planned Changes

## 1. Round Number Correction on Round Start

**Problem:** When a round is replayed (tech pause, broadcast issue), the round number gets blindly incremented, leading to incorrect round numbering and duplicate/phantom round events.

**Desired behavior:**
- On every `round_start`, compute the correct round number as `score_team1 + score_team2 + 1`
- If the computed round number matches the previous round's number, treat the previous round as erroneous:
  - Remove all events associated with that previous round (everything since its `round_start`)
  - The new `round_start` replaces it

**Files likely affected:**
- `src/valoscribe/orchestration/round_manager.py` - Round number computation logic
- `src/valoscribe/orchestration/game_state_manager.py` - Phase transition handling

---

## 2. Batch Events Per Round Before Writing

**Problem:** Events are written to the output file immediately as they occur, with no opportunity to reorder or edit them before committing.

**Desired behavior:**
- Starting at every `round_start`, events accumulate into a per-round buffer
- On the next `round_start`, the buffered events are sorted by timestamp and flushed to the output file, then the buffer is cleared
- At the end of processing (after `_finalize_events`), the remaining buffer is also flushed to handle the final round

**Files likely affected:**
- `src/valoscribe/orchestration/event_collector.py` - Buffering logic
- `src/valoscribe/orchestration/output_writer.py` - Batched write support
- `src/valoscribe/orchestration/game_state_manager.py` - Flush triggers on round start and finalization

---

## 3. Backdate Kill Event Timestamps by 2 Frames

**Problem:** Kill events are detected ~2 frames after they actually happen (due to killfeed appearing with a delay). Their timestamps reflect when the killfeed was read, not when the kill occurred.

**Desired behavior:**
- Subtract `2 / fps` seconds from every kill event's timestamp (e.g., at 4 FPS, subtract 0.5s)
- Combined with change #2 (round batching + sort by timestamp), kills will appear in the correct chronological position relative to other events

**Files likely affected:**
- `src/valoscribe/orchestration/game_state_manager.py` - Kill event creation in `_process_active_round` and `_process_post_round`
- Alternatively, `src/valoscribe/orchestration/event_collector.py` - Could adjust timestamp in `add_killfeed_events()`

---

## 4. Per-Patch Config with VLR Patch Scraping

**Problem:** HUD config is currently per-tournament. Game patches can change HUD layouts, ability specs, or agent properties within a tournament. Currently requires manually selecting the right config.

**Desired behavior:**
- Scrape the patch number from VLR.gg match pages (e.g., "Patch 12.0")
- Organize configs by patch: `config/patch_12.0/hud.json`, `config/patch_12.0/agents.json` (or similar)
- When processing a match, automatically select the config matching the scraped patch
- To support a new patch: copy the previous patch's config directory, make changes as needed

**Files likely affected:**
- `src/valoscribe/scraper/vlr_scraper.py` - Scrape patch number from match page
- `src/valoscribe/config/` - Reorganize into per-patch directories
- `src/valoscribe/orchestration/detector_registry.py` - Config resolution by patch
- `src/valoscribe/orchestration/game_state_manager.py` - Pass patch info through
- `src/valoscribe/commands/orchestrate.py` - Patch-aware config loading

---

## 5. Astra Ability Detection via Template Matching

**Problem:** Astra's abilities are visually represented differently from other agents. Instead of bright blobs (dots), her ability charges appear as a specific template/icon. The blob detection method returns incorrect results for her.

**Desired behavior:**
- Detect when the current player is Astra
- For Astra, use template matching instead of blob detection for ability charges
- Count the number of template matches in the ability region to determine charge count
- All other agents continue using the existing blob detection

**Files likely affected:**
- `src/valoscribe/detectors/ability_detector.py` - Add Astra-specific template matching path
- `src/valoscribe/detectors/preround_ability_detector.py` - Same for preround
- `src/valoscribe/config/agents_champs2025.json` - Flag Astra's abilities as template-based
- `src/valoscribe/templates/abilities/` - Add Astra ability template images
