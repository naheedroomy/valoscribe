"""
Validate event logs for structural integrity.
"""

import json
from pathlib import Path
from typing import Dict, List, Tuple


def validate_event_log(event_log_path: Path) -> Dict[str, any]:
    """
    Validate an event log file.

    Returns:
        Dictionary with validation results
    """
    results = {
        'path': str(event_log_path),
        'has_match_start': False,
        'has_match_end': False,
        'round_starts': 0,
        'round_ends': 0,
        'rounds_balanced': False,
        'final_score_valid': False,
        'final_score': None,
        'errors': []
    }

    try:
        # Read all events
        events = []
        with open(event_log_path, 'r') as f:
            for line in f:
                events.append(json.loads(line.strip()))

        # Count event types
        match_start_events = [e for e in events if e.get('type') == 'match_start']
        match_end_events = [e for e in events if e.get('type') == 'match_end']
        round_start_events = [e for e in events if e.get('type') == 'round_start']
        round_end_events = [e for e in events if e.get('type') == 'round_end']

        # Check for match_start and match_end
        results['has_match_start'] = len(match_start_events) > 0
        results['has_match_end'] = len(match_end_events) > 0

        if not results['has_match_start']:
            results['errors'].append('Missing match_start event')
        if not results['has_match_end']:
            results['errors'].append('Missing match_end event')

        # Count rounds
        results['round_starts'] = len(round_start_events)
        results['round_ends'] = len(round_end_events)
        results['rounds_balanced'] = results['round_starts'] == results['round_ends']

        if not results['rounds_balanced']:
            results['errors'].append(
                f'Unbalanced rounds: {results["round_starts"]} starts vs {results["round_ends"]} ends'
            )

        # Validate final score
        if match_end_events:
            match_end = match_end_events[-1]
            score_team1 = match_end.get('final_score_team1', 0)
            score_team2 = match_end.get('final_score_team2', 0)
            results['final_score'] = f"{score_team1}-{score_team2}"

            # Check if one team has at least 13 rounds
            has_13_rounds = max(score_team1, score_team2) >= 13

            # Check if winner wins by 2
            score_diff = abs(score_team1 - score_team2)
            wins_by_2 = score_diff >= 2

            results['final_score_valid'] = has_13_rounds and wins_by_2

            if not has_13_rounds:
                results['errors'].append(
                    f'No team reached 13 rounds (score: {score_team1}-{score_team2})'
                )
            if not wins_by_2:
                results['errors'].append(
                    f'Winner did not win by 2 (score: {score_team1}-{score_team2})'
                )

    except Exception as e:
        results['errors'].append(f'Exception during validation: {str(e)}')

    return results


def main():
    series_output_dir = Path('series_output')

    if not series_output_dir.exists():
        print(f"Directory {series_output_dir} does not exist")
        return

    # Find all event_log.jsonl files
    event_logs = sorted(series_output_dir.glob('*/*/output/event_log.jsonl'))

    print(f"Validating {len(event_logs)} event log files...\n")

    all_results = []
    failed_count = 0

    for event_log in event_logs:
        results = validate_event_log(event_log)
        all_results.append(results)

        # Check if all validations passed
        all_passed = (
            results['has_match_start'] and
            results['has_match_end'] and
            results['rounds_balanced'] and
            results['final_score_valid']
        )

        if not all_passed:
            failed_count += 1
            relative_path = event_log.relative_to(series_output_dir)
            print(f"❌ FAILED: {relative_path}")
            print(f"   Match start: {results['has_match_start']}")
            print(f"   Match end: {results['has_match_end']}")
            print(f"   Rounds balanced: {results['rounds_balanced']} ({results['round_starts']} starts, {results['round_ends']} ends)")
            print(f"   Final score valid: {results['final_score_valid']} (score: {results['final_score']})")
            if results['errors']:
                for error in results['errors']:
                    print(f"   - {error}")
            print()

    # Summary
    passed_count = len(event_logs) - failed_count
    print("=" * 80)
    print(f"\n✅ PASSED: {passed_count}/{len(event_logs)} ({passed_count/len(event_logs)*100:.1f}%)")
    print(f"❌ FAILED: {failed_count}/{len(event_logs)} ({failed_count/len(event_logs)*100:.1f}%)")

    # Breakdown by issue type
    print("\n=== Issue Breakdown ===")
    missing_match_start = sum(1 for r in all_results if not r['has_match_start'])
    missing_match_end = sum(1 for r in all_results if not r['has_match_end'])
    unbalanced_rounds = sum(1 for r in all_results if not r['rounds_balanced'])
    invalid_score = sum(1 for r in all_results if not r['final_score_valid'])

    print(f"Missing match_start: {missing_match_start}")
    print(f"Missing match_end: {missing_match_end}")
    print(f"Unbalanced rounds: {unbalanced_rounds}")
    print(f"Invalid final score: {invalid_score}")

    # List of failed logs
    if failed_count > 0:
        print("\n=== Failed Event Logs ===")
        failed_logs = [
            Path(r['path']).relative_to(series_output_dir)
            for r in all_results
            if not (r['has_match_start'] and r['has_match_end'] and
                   r['rounds_balanced'] and r['final_score_valid'])
        ]
        for log in failed_logs:
            print(f"  {log}")


if __name__ == '__main__':
    main()
