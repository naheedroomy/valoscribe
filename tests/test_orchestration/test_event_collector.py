"""Unit tests for EventCollector."""

from __future__ import annotations
import pytest

from valoscribe.orchestration.event_collector import EventCollector
from valoscribe.types.detections import KillfeedAgentDetection


class TestEventCollector:
    """Tests for EventCollector class."""

    @pytest.fixture
    def collector(self):
        """Create EventCollector instance."""
        return EventCollector()

    def test_init(self, collector):
        """Test EventCollector initialization."""
        assert collector.events == []
        assert collector.killfeed_dedup is not None

    def test_init_custom_dedup_window(self):
        """Test initialization with custom dedup window."""
        collector = EventCollector(dedup_window_sec=10.0)
        assert collector.killfeed_dedup.dedup_window_sec == 10.0

    def test_add_event_basic(self, collector):
        """Test adding a basic event."""
        collector.add_event("round_start", timestamp=0.0, round_number=1)

        assert len(collector.round_buffer) == 1
        assert collector.round_buffer[0]["type"] == "round_start"
        assert collector.round_buffer[0]["timestamp"] == 0.0
        assert collector.round_buffer[0]["round_number"] == 1

    def test_add_event_with_data(self, collector):
        """Test adding event with multiple data fields."""
        collector.add_event(
            "death",
            timestamp=10.5,
            player="brawk",
            team="NRG",
            agent="sova",
        )

        assert len(collector.round_buffer) == 1
        event = collector.round_buffer[0]
        assert event["type"] == "death"
        assert event["timestamp"] == 10.5
        assert event["player"] == "brawk"
        assert event["team"] == "NRG"
        assert event["agent"] == "sova"

    def test_add_multiple_events(self, collector):
        """Test adding multiple events."""
        collector.add_event("round_start", timestamp=0.0, round_number=1)
        collector.add_event("death", timestamp=5.0, player="player1")
        collector.add_event("kill", timestamp=5.0, killer="player2")

        assert len(collector.round_buffer) == 3
        assert collector.round_buffer[0]["type"] == "round_start"
        assert collector.round_buffer[1]["type"] == "death"
        assert collector.round_buffer[2]["type"] == "kill"

    def test_add_player_events(self, collector):
        """Test adding player events from StateValidator."""
        player_events = [
            {
                "type": "death",
                "timestamp": 10.0,
                "player": "brawk",
                "team": "NRG",
                "agent": "sova",
            },
            {
                "type": "ability_used",
                "timestamp": 12.0,
                "player": "marved",
                "ability": "ability_1",
            },
        ]

        collector.add_player_events(player_events)

        assert len(collector.round_buffer) == 2
        assert collector.round_buffer[0]["type"] == "death"
        assert collector.round_buffer[1]["type"] == "ability_used"

    def test_add_killfeed_events_single(self, collector):
        """Test adding single killfeed event."""
        detection = KillfeedAgentDetection(
            killer_agent="jett",
            killer_side="attack",
            victim_agent="sova",
            victim_side="defense",
            confidence=0.95,
        )

        added = collector.add_killfeed_events(
            timestamp=5.0, killfeed_detections=[(detection, {})]
        )

        assert added == 1
        assert len(collector.round_buffer) == 1
        assert collector.round_buffer[0]["type"] == "kill"
        assert collector.round_buffer[0]["killer_agent"] == "jett"
        assert collector.round_buffer[0]["victim_agent"] == "sova"

    def test_add_killfeed_events_multiple(self, collector):
        """Test adding multiple killfeed events."""
        detections = [
            (KillfeedAgentDetection(
                killer_agent="jett",
                killer_side="attack",
                victim_agent="sova",
                victim_side="defense",
                confidence=0.95,
            ), {}),
            (KillfeedAgentDetection(
                killer_agent="raze",
                killer_side="attack",
                victim_agent="cypher",
                victim_side="defense",
                confidence=0.92,
            ), {}),
        ]

        added = collector.add_killfeed_events(timestamp=5.0, killfeed_detections=detections)

        assert added == 2
        assert len(collector.round_buffer) == 2

    def test_killfeed_deduplication(self, collector):
        """Test that duplicate killfeed events are filtered."""
        detection = KillfeedAgentDetection(
            killer_agent="jett",
            killer_side="attack",
            victim_agent="sova",
            victim_side="defense",
            confidence=0.95,
        )

        # Add same kill multiple times (simulating consecutive frames)
        added1 = collector.add_killfeed_events(timestamp=5.0, killfeed_detections=[(detection, {})])
        added2 = collector.add_killfeed_events(timestamp=5.25, killfeed_detections=[(detection, {})])
        added3 = collector.add_killfeed_events(timestamp=5.5, killfeed_detections=[(detection, {})])

        assert added1 == 1  # First is new
        assert added2 == 0  # Duplicate
        assert added3 == 0  # Duplicate
        assert len(collector.round_buffer) == 1  # Only one kill logged

    def test_killfeed_expiration(self, collector):
        """Test that kills expire after dedup window."""
        detection = KillfeedAgentDetection(
            killer_agent="jett",
            killer_side="attack",
            victim_agent="sova",
            victim_side="defense",
            confidence=0.95,
        )

        # Add kill at t=0
        added1 = collector.add_killfeed_events(timestamp=0.0, killfeed_detections=[(detection, {})])

        # Same kill at t=6 (beyond 5s window) - should be new
        added2 = collector.add_killfeed_events(timestamp=6.0, killfeed_detections=[(detection, {})])

        assert added1 == 1
        assert added2 == 1
        assert len(collector.round_buffer) == 2  # Two separate kill instances

    def test_get_events_all(self, collector):
        """Test getting all events."""
        collector.add_event("round_start", timestamp=0.0)
        collector.add_event("death", timestamp=5.0)
        collector.add_event("kill", timestamp=5.0)

        events = collector.get_events()

        assert len(events) == 3
        # Should be a copy (concatenation creates new list)
        events.append({"type": "test"})
        assert len(collector.round_buffer) == 3

    def test_get_events_filtered(self, collector):
        """Test getting events filtered by type."""
        collector.add_event("death", timestamp=5.0, player="player1")
        collector.add_event("kill", timestamp=5.0, killer="player2")
        collector.add_event("death", timestamp=10.0, player="player3")

        deaths = collector.get_events(event_type="death")
        kills = collector.get_events(event_type="kill")

        assert len(deaths) == 2
        assert len(kills) == 1
        assert all(e["type"] == "death" for e in deaths)
        assert all(e["type"] == "kill" for e in kills)

    def test_get_events_in_range(self, collector):
        """Test getting events within time range."""
        collector.add_event("event1", timestamp=0.0)
        collector.add_event("event2", timestamp=5.0)
        collector.add_event("event3", timestamp=10.0)
        collector.add_event("event4", timestamp=15.0)

        events = collector.get_events_in_range(start_time=5.0, end_time=10.0)

        assert len(events) == 2
        assert events[0]["timestamp"] == 5.0
        assert events[1]["timestamp"] == 10.0

    def test_get_events_in_range_filtered(self, collector):
        """Test getting events in range filtered by type."""
        collector.add_event("death", timestamp=5.0)
        collector.add_event("kill", timestamp=7.0)
        collector.add_event("death", timestamp=10.0)
        collector.add_event("kill", timestamp=15.0)

        deaths = collector.get_events_in_range(
            start_time=0.0,
            end_time=12.0,
            event_type="death",
        )

        assert len(deaths) == 2
        assert all(e["type"] == "death" for e in deaths)
        assert all(0.0 <= e["timestamp"] <= 12.0 for e in deaths)

    def test_get_event_count_all(self, collector):
        """Test getting total event count."""
        collector.add_event("event1", timestamp=0.0)
        collector.add_event("event2", timestamp=5.0)
        collector.add_event("event3", timestamp=10.0)

        assert collector.get_event_count() == 3

    def test_get_event_count_filtered(self, collector):
        """Test getting event count filtered by type."""
        collector.add_event("death", timestamp=5.0)
        collector.add_event("kill", timestamp=5.0)
        collector.add_event("death", timestamp=10.0)

        assert collector.get_event_count(event_type="death") == 2
        assert collector.get_event_count(event_type="kill") == 1
        assert collector.get_event_count(event_type="revival") == 0

    def test_reset(self, collector):
        """Test resetting the collector."""
        collector.add_event("event1", timestamp=0.0)
        collector.add_event("event2", timestamp=5.0)

        assert len(collector.round_buffer) == 2

        # Reset
        collector.reset()

        assert len(collector.events) == 0
        assert len(collector.round_buffer) == 0

    def test_get_event_summary(self, collector):
        """Test getting event summary."""
        collector.add_event("death", timestamp=5.0)
        collector.add_event("kill", timestamp=5.0)
        collector.add_event("death", timestamp=10.0)
        collector.add_event("death", timestamp=15.0)
        collector.add_event("ability_used", timestamp=20.0)

        summary = collector.get_event_summary()

        assert summary["death"] == 3
        assert summary["kill"] == 1
        assert summary["ability_used"] == 1
        assert len(summary) == 3

    def test_event_summary_empty(self, collector):
        """Test event summary when empty."""
        summary = collector.get_event_summary()
        assert summary == {}

    def test_repr(self, collector):
        """Test string representation."""
        collector.add_event("death", timestamp=5.0)
        collector.add_event("kill", timestamp=5.0)

        repr_str = repr(collector)
        assert "EventCollector" in repr_str
        assert "total_events=2" in repr_str
        assert "event_types=2" in repr_str

    def test_discard_round_buffer_with_events(self, collector):
        """Test discarding round buffer returns and clears events."""
        collector.add_event("death", timestamp=5.0, player="player1")
        collector.add_event("kill", timestamp=5.0, killer="player2")

        discarded = collector.discard_round_buffer()

        assert len(discarded) == 2
        assert discarded[0]["type"] == "death"
        assert discarded[1]["type"] == "kill"
        assert len(collector.round_buffer) == 0

    def test_discard_round_buffer_empty(self, collector):
        """Test discarding empty round buffer."""
        discarded = collector.discard_round_buffer()

        assert discarded == []
        assert len(collector.round_buffer) == 0

    def test_discard_does_not_affect_committed_events(self, collector):
        """Test that discard only affects the buffer, not committed events."""
        # Commit some events first
        collector.add_event("round_start", timestamp=0.0)
        collector.flush_round_buffer()

        # Add events to buffer then discard
        collector.add_event("death", timestamp=5.0)
        collector.discard_round_buffer()

        assert len(collector.events) == 1  # committed event remains
        assert len(collector.round_buffer) == 0

    def test_realistic_scenario(self, collector):
        """Test realistic game scenario with mixed events."""
        # Round start
        collector.add_event("round_start", timestamp=0.0, round_number=1)

        # Player events
        player_events = [
            {"type": "death", "timestamp": 10.0, "player": "brawk"},
            {"type": "ability_used", "timestamp": 8.0, "player": "marved"},
        ]
        collector.add_player_events(player_events)

        # Round end
        collector.add_event("round_end", timestamp=100.0, round_number=1)

        # All events are in the buffer before flush
        assert len(collector.round_buffer) == 4

        # Flush to simulate round boundary
        flushed = collector.flush_round_buffer()
        assert len(flushed) == 4
        assert len(collector.events) == 4
        assert len(collector.round_buffer) == 0

        # Events should be sorted by timestamp after flush
        timestamps = [e["timestamp"] for e in collector.events]
        assert timestamps == sorted(timestamps)

        summary = collector.get_event_summary()
        assert summary["round_start"] == 1
        assert summary["death"] == 1
        assert summary["ability_used"] == 1
        assert summary["round_end"] == 1
