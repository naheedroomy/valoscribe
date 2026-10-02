from typer.main import get_command

from valoscribe.commands import test_active_agent


def test_active_agent_command_remains_registered() -> None:
    command = get_command(test_active_agent.app)

    assert command.name == "test"
