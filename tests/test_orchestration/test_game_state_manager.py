"""Unit tests for GameStateManager."""

from __future__ import annotations
import pytest
from pathlib import Path
import tempfile
import shutil

from valoscribe.orchestration.game_state_manager import GameStateManager
from valoscribe.orchestration.phase_detector import Phase


class TestGameStateManager:
    """Tests for GameStateManager class."""

    @pytest.fixture
    def temp_dir(self):
        """Create temporary directory for test outputs."""
        temp_dir = Path(tempfile.mkdtemp())
        yield temp_dir
        # Cleanup
        shutil.rmtree(temp_dir)

    @pytest.fixture
    def vlr_metadata(self):
        """Create sample VLR metadata."""
        return {
            "teams": [
                {"name": "NRG", "starting_side": "defense"},
                {"name": "FNATIC", "starting_side": "attack"},
            ],
            "players": [
                {"name": "player0", "team": "NRG", "agent": "sova"},
                {"name": "player1", "team": "NRG", "agent": "jett"},
                {"name": "player2", "team": "NRG", "agent": "raze"},
                {"name": "player3", "team": "NRG", "agent": "omen"},
                {"name": "player4", "team": "NRG", "agent": "killjoy"},
                {"name": "player5", "team": "FNATIC", "agent": "sova"},
                {"name": "player6", "team": "FNATIC", "agent": "jett"},
                {"name": "player7", "team": "FNATIC", "agent": "raze"},
                {"name": "player8", "team": "FNATIC", "agent": "omen"},
                {"name": "player9", "team": "FNATIC", "agent": "killjoy"},
            ],
            "map": "Ascent",
            "match_date": "2024-01-15",
        }

    @pytest.fixture
    def dummy_video_path(self, temp_dir):
        """Create a dummy video file."""
        import cv2
        import numpy as np

        video_path = temp_dir / "test_video.mp4"

        # Create a minimal video file (10 frames of black)
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(str(video_path), fourcc, 30.0, (1920, 1080))

        for _ in range(10):
            frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
            out.write(frame)

        out.release()

        return video_path

    def test_init(self, dummy_video_path, vlr_metadata, temp_dir):
        """Test GameStateManager initialization."""
        manager = GameStateManager(
            video_path=dummy_video_path,
            vlr_metadata=vlr_metadata,
            output_dir=temp_dir / "output",
            fps=4.0,
        )

        assert manager.video_path == dummy_video_path
        assert manager.fps == 4.0
        assert manager.current_phase is None  # Set to first detected game phase
        assert manager.frame_count == 0

    def test_components_initialized(self, dummy_video_path, vlr_metadata, temp_dir):
        """Test that all components are initialized."""
        manager = GameStateManager(
            video_path=dummy_video_path,
            vlr_metadata=vlr_metadata,
            output_dir=temp_dir / "output",
        )

        # Check all components exist
        assert manager.detector_registry is not None
        assert manager.phase_detector is not None
        assert manager.round_manager is not None
        assert manager.state_validator is not None
        assert manager.event_collector is not None
        assert manager.timer_manager is not None
        assert manager.output_writer is not None

    def test_player_trackers_initialized(self, dummy_video_path, vlr_metadata, temp_dir):
        """Test that player trackers are lazy-initialized (None at construction)."""
        manager = GameStateManager(
            video_path=dummy_video_path,
            vlr_metadata=vlr_metadata,
            output_dir=temp_dir / "output",
        )

        # Player trackers are lazy-initialized on first preround agent detection
        assert manager.player_trackers is None

        # Simulate initialization with detected agents and sides
        detected_agents = [
            "sova", "jett", "raze", "omen", "killjoy",
            "sova", "jett", "raze", "omen", "killjoy",
        ]
        detected_sides = [
            "defense", "defense", "defense", "defense", "defense",
            "attack", "attack", "attack", "attack", "attack",
        ]
        manager._initialize_player_trackers_from_agents(detected_agents, detected_sides)

        assert len(manager.player_trackers) == 10

        # Check first player
        tracker0 = manager.player_trackers[0]
        assert tracker0.metadata["name"] == "player0"
        assert tracker0.metadata["team"] == "NRG"
        assert tracker0.metadata["agent"] == "sova"

        # Check last player
        tracker9 = manager.player_trackers[9]
        assert tracker9.metadata["name"] == "player9"
        assert tracker9.metadata["team"] == "FNATIC"
        assert tracker9.metadata["agent"] == "killjoy"

    def test_phase_detector_initialized(self, dummy_video_path, vlr_metadata, temp_dir):
        """Test that phase detector is initialized with correct detectors."""
        manager = GameStateManager(
            video_path=dummy_video_path,
            vlr_metadata=vlr_metadata,
            output_dir=temp_dir / "output",
        )

        # PhaseDetector should have references to detectors from registry
        assert manager.phase_detector.timer_detector is manager.detector_registry.timer_detector
        assert manager.phase_detector.spike_detector is manager.detector_registry.spike_detector
        assert manager.phase_detector.score_detector is manager.detector_registry.score_detector
        assert manager.phase_detector.credits_detector is manager.detector_registry.preround_credits_detector

    def test_detect_alive_players_all_none(self, dummy_video_path, vlr_metadata, temp_dir):
        """Test _detect_alive_players with no health detections."""
        import numpy as np

        manager = GameStateManager(
            video_path=dummy_video_path,
            vlr_metadata=vlr_metadata,
            output_dir=temp_dir / "output",
        )

        # Create dummy frame
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)

        # All health detections will be None (no health visible)
        alive_list = manager._detect_alive_players(frame)

        assert len(alive_list) == 10
        # All should be False since no health detected
        assert all(not alive for alive in alive_list)

    def test_handle_phase_transition_preround_to_active(
        self, dummy_video_path, vlr_metadata, temp_dir
    ):
        """Test phase transition from PREROUND to ACTIVE_ROUND."""
        manager = GameStateManager(
            video_path=dummy_video_path,
            vlr_metadata=vlr_metadata,
            output_dir=temp_dir / "output",
        )

        manager._handle_phase_transition(Phase.PREROUND, Phase.ACTIVE_ROUND, 10.0)

        # Should add round_start event
        events = manager.event_collector.get_all_events()
        assert len(events) == 1
        assert events[0]["type"] == "round_start"
        assert events[0]["timestamp"] == 10.0

    def test_handle_phase_transition_post_to_preround(
        self, dummy_video_path, vlr_metadata, temp_dir
    ):
        """Test phase transition from POST_ROUND to PREROUND."""
        manager = GameStateManager(
            video_path=dummy_video_path,
            vlr_metadata=vlr_metadata,
            output_dir=temp_dir / "output",
        )

        # Set up some state
        manager.timer_manager.on_spike_planted(45.0)
        manager.timer_manager.on_round_ended(100.0)

        manager._handle_phase_transition(Phase.POST_ROUND, Phase.PREROUND, 110.0)

        # Timers should be reset
        assert manager.timer_manager.spike_planted_at is None
        assert manager.timer_manager.round_ended_at is None

    def test_handle_phase_transition_post_to_active_skipped_preround(
        self, dummy_video_path, vlr_metadata, temp_dir
    ):
        """Test phase transition from POST_ROUND to ACTIVE_ROUND (skipped preround)."""
        manager = GameStateManager(
            video_path=dummy_video_path,
            vlr_metadata=vlr_metadata,
            output_dir=temp_dir / "output",
        )

        manager._handle_phase_transition(Phase.POST_ROUND, Phase.ACTIVE_ROUND, 110.0)

        # Should add round_start and match_start events (round 1 triggers both)
        events = manager.event_collector.get_all_events()
        assert len(events) == 2
        assert events[0]["type"] == "round_start"
        assert events[1]["type"] == "match_start"

        # Timers should be reset
        assert manager.timer_manager.spike_planted_at is None
        assert manager.timer_manager.round_ended_at is None

    def test_phantom_round_correction_preround_to_active(
        self, dummy_video_path, vlr_metadata, temp_dir
    ):
        """Test phantom round correction on PREROUND -> ACTIVE_ROUND transition."""
        manager = GameStateManager(
            video_path=dummy_video_path,
            vlr_metadata=vlr_metadata,
            output_dir=temp_dir / "output",
        )

        # Simulate: round 1 played normally
        manager._handle_phase_transition(None, Phase.PREROUND, 0.0)       # round 1 preround
        manager._handle_phase_transition(Phase.PREROUND, Phase.ACTIVE_ROUND, 5.0)  # round 1 start

        # Score updated: team1 wins round 1
        manager.round_manager.current_score = {"team1": 1, "team2": 0}

        # Simulate: phantom round (replayed broadcast)
        manager._handle_phase_transition(Phase.ACTIVE_ROUND, Phase.PREROUND, 100.0)  # round 2 preround (phantom)
        # Add some phantom events to the buffer
        manager.event_collector.add_event("death", timestamp=105.0, player="player1")
        manager.event_collector.add_event("kill", timestamp=106.0, killer="player2")

        # Another preround without score change -> round 3 (actually should be round 2)
        manager._handle_phase_transition(Phase.PREROUND, Phase.ACTIVE_ROUND, 110.0)

        # Correction should have happened:
        # expected = 1 + 0 + 1 = 2, current was 3 -> corrected to 2
        assert manager.round_manager.current_round == 2

        # The phantom events should have been discarded
        # Only committed events (from flush) + the new round_start should exist
        all_events = manager.event_collector.get_all_events()
        round_starts = [e for e in all_events if e["type"] == "round_start"]
        # Should have round 1 start and round 2 start (corrected)
        assert len(round_starts) == 2
        assert round_starts[0]["round_number"] == 1
        assert round_starts[1]["round_number"] == 2

    def test_phantom_round_correction_post_to_active(
        self, dummy_video_path, vlr_metadata, temp_dir
    ):
        """Test phantom round correction on POST_ROUND/None -> ACTIVE_ROUND transition."""
        manager = GameStateManager(
            video_path=dummy_video_path,
            vlr_metadata=vlr_metadata,
            output_dir=temp_dir / "output",
        )

        # Simulate: round 1 via POST_ROUND -> ACTIVE_ROUND (skipped preround)
        manager._handle_phase_transition(None, Phase.ACTIVE_ROUND, 5.0)  # round 1 start

        # Score updated: team1 wins round 1
        manager.round_manager.current_score = {"team1": 1, "team2": 0}

        # Simulate: phantom round via POST_ROUND -> ACTIVE_ROUND
        manager._handle_phase_transition(Phase.ACTIVE_ROUND, Phase.POST_ROUND, 90.0)
        # Add phantom events
        manager.event_collector.add_event("death", timestamp=95.0, player="player1")

        manager._handle_phase_transition(Phase.POST_ROUND, Phase.ACTIVE_ROUND, 110.0)

        # expected = 1 + 0 + 1 = 2, current was 3 -> corrected to 2
        assert manager.round_manager.current_round == 2

        all_events = manager.event_collector.get_all_events()
        round_starts = [e for e in all_events if e["type"] == "round_start"]
        assert round_starts[-1]["round_number"] == 2

    def test_no_correction_when_round_matches_score(
        self, dummy_video_path, vlr_metadata, temp_dir
    ):
        """Test that no correction happens when round number matches score."""
        manager = GameStateManager(
            video_path=dummy_video_path,
            vlr_metadata=vlr_metadata,
            output_dir=temp_dir / "output",
        )

        # Normal progression: round 1
        manager._handle_phase_transition(None, Phase.PREROUND, 0.0)
        manager._handle_phase_transition(Phase.PREROUND, Phase.ACTIVE_ROUND, 5.0)

        # Score is 0-0, expected = 1, current = 1 -> no correction
        assert manager.round_manager.current_round == 1
        all_events = manager.event_collector.get_all_events()
        assert len([e for e in all_events if e["type"] == "round_start"]) == 1

    def test_repr(self, dummy_video_path, vlr_metadata, temp_dir):
        """Test string representation."""
        manager = GameStateManager(
            video_path=dummy_video_path,
            vlr_metadata=vlr_metadata,
            output_dir=temp_dir / "output",
            fps=8.0,
        )

        repr_str = repr(manager)

        assert "GameStateManager" in repr_str
        assert "test_video.mp4" in repr_str
        assert "8.0" in repr_str
