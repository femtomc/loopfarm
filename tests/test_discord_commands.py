from __future__ import annotations

from loopfarm.discord_commands import parse_command_text, parse_discord_messages


def _msg(
    *,
    msg_id: str,
    content: str,
    author_id: str = "u1",
    username: str = "operator",
    timestamp: str = "2026-01-30T12:00:00.000Z",
) -> dict[str, object]:
    return {
        "id": msg_id,
        "content": content,
        "author": {"id": author_id, "username": username},
        "timestamp": timestamp,
    }


def test_parse_command_text_supports_prefixes() -> None:
    assert parse_command_text("!pause") == ("pause", None)
    assert parse_command_text("!loopfarm pause") == ("pause", None)
    assert parse_command_text("!loopfarm:pause") == ("pause", None)
    assert parse_command_text("!context") == ("context_show", None)
    assert parse_command_text("!loopfarm context set hello") == ("context_set", "hello")
    assert parse_command_text("!chat hi") == ("chat", "hi")
    assert parse_command_text("!ask hi") == ("chat", "hi")
    assert parse_command_text("!loopfarm frobnicate") == ("help", None)
    assert parse_command_text("!loopfarmian") is None


def test_parse_discord_messages_splits_commands_and_context() -> None:
    messages = [
        _msg(msg_id="3", content="!pause", timestamp="2026-01-30T12:00:03.000Z"),
        _msg(msg_id="2", content="hello", timestamp="2026-01-30T12:00:02.000Z"),
        _msg(
            msg_id="1",
            content="!context set use the new prompt",
            timestamp="2026-01-30T12:00:01.000Z",
        ),
    ]

    result = parse_discord_messages(
        messages, bot_user_id="bot-id", authorized_users={"u1"}
    )

    assert result.newest_id == "3"
    assert result.context_lines
    assert "hello" in result.context_lines[0]
    assert result.context_authors == ["operator"]

    kinds = [cmd.kind for cmd in result.commands]
    assert kinds == ["context_set", "pause"]
    assert all("!pause" not in line for line in result.context_lines)


def test_parse_discord_messages_ignores_unauthorized() -> None:
    messages = [_msg(msg_id="1", content="!pause", author_id="u2")]

    result = parse_discord_messages(
        messages, bot_user_id="bot-id", authorized_users={"u1"}
    )

    assert result.newest_id == "1"
    assert not result.commands
    assert not result.context_lines
    assert not result.context_authors
