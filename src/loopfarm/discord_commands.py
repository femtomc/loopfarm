from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class DiscordCommand:
    kind: str
    args: str | None
    author: str
    author_id: str
    timestamp: str
    content: str


@dataclass(frozen=True)
class DiscordParseResult:
    commands: list[DiscordCommand]
    context_lines: list[str]
    context_authors: list[str]
    newest_id: str

    @property
    def context_text(self) -> str:
        return "\n".join(self.context_lines).strip()


def authorized_users_from_env(env: Mapping[str, str] | None = None) -> set[str] | None:
    env = env or os.environ
    raw = (
        env.get("LOOPFARM_DISCORD_AUTHORIZED_USERS")
        or env.get("LOOPFARM_DISCORD_AUTHORIZED_USER_IDS")
        or ""
    ).strip()
    if not raw:
        return None
    return {user.strip() for user in raw.split(",") if user.strip()}


def parse_discord_messages(
    messages: list[dict[str, Any]],
    *,
    bot_user_id: str,
    authorized_users: set[str] | None,
) -> DiscordParseResult:
    if not messages:
        return DiscordParseResult(
            commands=[], context_lines=[], context_authors=[], newest_id=""
        )

    newest_id = str(messages[0].get("id") or "")
    commands: list[DiscordCommand] = []
    context_lines: list[str] = []
    context_authors: list[str] = []

    # Discord returns newest first; process oldest first for context ordering.
    for msg in reversed(messages):
        author = msg.get("author") or {}
        author_id = str(author.get("id") or "")
        if not author_id:
            continue
        if author_id == bot_user_id:
            continue
        if author.get("bot") is True:
            continue
        if msg.get("webhook_id") is not None:
            continue
        if authorized_users is not None and author_id not in authorized_users:
            continue

        content = str(msg.get("content") or "")
        if not content.strip():
            continue

        parsed = parse_command_text(content)
        if parsed is None:
            username = str(author.get("username") or "unknown")
            context_lines.append(_format_context_line(author, msg, content))
            context_authors.append(username)
            continue

        kind, args = parsed
        commands.append(
            DiscordCommand(
                kind=kind,
                args=args,
                author=str(author.get("username") or "unknown"),
                author_id=author_id,
                timestamp=str(msg.get("timestamp") or ""),
                content=content.strip(),
            )
        )

    return DiscordParseResult(
        commands=commands,
        context_lines=context_lines,
        context_authors=context_authors,
        newest_id=newest_id,
    )


def parse_command_text(content: str) -> tuple[str, str | None] | None:
    text = content.strip()
    if not text.startswith("!"):
        return None

    lowered = text.lower()
    for prefix in ("!loopfarm",):
        if lowered.startswith(prefix):
            boundary_index = len(prefix)
            if len(text) > boundary_index:
                next_char = text[boundary_index]
                if not (next_char.isspace() or next_char == ":"):
                    return _parse_command_payload(text[1:])

            remainder = text[boundary_index:].lstrip()
            if remainder.startswith(":"):
                remainder = remainder[1:].lstrip()
            if not remainder:
                return ("help", None)
            parsed = _parse_command_payload(remainder)
            return parsed or ("help", None)

    return _parse_command_payload(text[1:])


def _parse_command_payload(payload: str) -> tuple[str, str | None] | None:
    payload = payload.strip()
    if not payload:
        return None

    parts = payload.split(None, 1)
    head = parts[0].lower().lstrip("!")
    tail = parts[1] if len(parts) > 1 else ""

    if head in {"pause", "resume", "stop"}:
        return (head, None)

    if head == "help":
        return ("help", None)

    if head == "context":
        return _parse_context_command(payload)

    if head in {"chat", "ask"}:
        return ("chat", tail)

    return None


def _parse_context_command(payload: str) -> tuple[str, str | None] | None:
    tokens = payload.split(None, 2)
    if len(tokens) == 1:
        return ("context_show", None)

    sub = tokens[1].lower()
    if sub == "show":
        return ("context_show", None)
    if sub == "clear":
        return ("context_clear", None)
    if sub == "set":
        arg = tokens[2] if len(tokens) > 2 else ""
        return ("context_set", arg)
    return None


def _format_context_line(
    author: dict[str, Any], msg: dict[str, Any], content: str
) -> str:
    username = author.get("username") or "unknown"
    ts = str(msg.get("timestamp") or "")
    date = ts.split("T")[0] if "T" in ts else ts
    time_part = ts.split("T")[1].split(".")[0] if "T" in ts else ""
    return f"[{username} at {date} {time_part}]: {content}"
