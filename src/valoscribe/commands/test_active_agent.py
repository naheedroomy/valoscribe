"""Test active round agent detector."""

__test__ = False

from pathlib import Path

import cv2
import typer

from valoscribe.detectors.active_round_agent_detector import ActiveRoundAgentDetector
from valoscribe.detectors.cropper import Cropper
from valoscribe.utils.logger import setup_logging

app = typer.Typer(help="Test active round agent detector")


@app.command(name="test")
def test_active_agent_detector(
    image_path: Path = typer.Argument(..., help="Path to test image"),
    player_index: int = typer.Option(0, "--player", "-p", help="Player index to test (0-9)"),
    config_path: Path = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to HUD config file (default: champs2025.json)",
    ),
    min_confidence: float = typer.Option(
        0.7,
        "--min-confidence",
        "-m",
        help="Minimum confidence threshold (0-1)",
    ),
    debug: bool = typer.Option(
        False,
        "--debug",
        "-d",
        help="Show debug information",
    ),
    greyscale: bool = typer.Option(
        False,
        "--greyscale",
        "-g",
        help="Use greyscale detection (for dead players)",
    ),
):
    """
    Test active round agent detector on a single image.

    Example:
        valoscribe test-active-agent test frame.png --player 0
    """
    setup_logging()

    # Validate player index
    if not 0 <= player_index <= 9:
        typer.echo(f"Error: Player index must be between 0 and 9, got {player_index}", err=True)
        raise typer.Exit(1)

    # Load image
    typer.echo(f"Loading image: {image_path}")
    frame = cv2.imread(str(image_path))
    if frame is None:
        typer.echo(f"Error: Could not load image: {image_path}", err=True)
        raise typer.Exit(1)

    typer.echo(f"Image loaded: {frame.shape[1]}x{frame.shape[0]}")

    # Initialize cropper
    if config_path:
        cropper = Cropper(config_path=config_path)
    else:
        cropper = Cropper()

    typer.echo(f"Using HUD config: {cropper.config['name']}")

    # Initialize detector
    detector = ActiveRoundAgentDetector(
        cropper=cropper,
        min_confidence=min_confidence,
    )

    typer.echo(f"Loaded {len(detector.templates)} templates")
    typer.echo(f"Testing player {player_index}...")
    typer.echo("")

    if debug:
        # Use debug detection
        agent_name, agent_crop, debug_info = detector.detect_with_debug(frame, player_index)

        typer.echo("=== DEBUG INFO ===")
        if debug_info.get("error"):
            typer.echo(f"Error: {debug_info['error']}")
        else:
            typer.echo(f"Number of crops: {debug_info.get('num_crops', 'N/A')}")
            typer.echo(f"Crop keys: {debug_info.get('crop_keys', [])}")
            typer.echo(f"Agent crop shape: {debug_info.get('agent_crop_shape', 'N/A')}")

            if "match_scores" in debug_info:
                typer.echo("\n=== MATCH SCORES ===")
                # Sort by confidence
                scores = sorted(
                    debug_info["match_scores"].items(),
                    key=lambda x: x[1].get("confidence", 0),
                    reverse=True,
                )

                for agent_name_key, score_data in scores[:10]:  # Top 10
                    agent = score_data["agent"]
                    confidence = score_data.get("confidence", 0)

                    if "skipped" in score_data:
                        typer.echo(f"  {agent_name_key:30s} - SKIPPED ({score_data['skipped']})")
                    else:
                        typer.echo(
                            f"  {agent_name_key:30s} - {agent:10s} - "
                            f"Confidence: {confidence:.3f}"
                        )

        typer.echo("\n=== DETECTION RESULT ===")
        if agent_name:
            side = "LEFT" if player_index < 5 else "RIGHT"
            typer.echo(f"✓ Detected: {agent_name} (screen position: {side})")
            if greyscale:
                typer.echo("  (greyscale mode - likely dead player)")
        else:
            typer.echo("✗ No agent detected")

        # Save agent crop if available
        if agent_crop.size > 0:
            output_path = image_path.parent / f"agent_crop_player_{player_index}.png"
            cv2.imwrite(str(output_path), agent_crop)
            typer.echo(f"\nAgent crop saved to: {output_path}")

    else:
        # Simple detection
        agent_name = detector.detect(frame, player_index, greyscale=greyscale)

        if agent_name:
            side = "LEFT" if player_index < 5 else "RIGHT"
            typer.echo(f"✓ Detected: {agent_name} (screen position: {side})")
            if greyscale:
                typer.echo("  (greyscale mode - likely dead player)")
        else:
            typer.echo("✗ No agent detected")


if __name__ == "__main__":
    app()
