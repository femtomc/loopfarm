from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import threading

from loopfarm.runner import CodexPhaseModel, JwzPoller, LoopfarmConfig, LoopfarmRunner


class FakeDiscord:
    def __init__(self, messages: list[dict[str, object]]) -> None:
        self.bot_token = "token"
        self._messages = messages

    def get_bot_user_id(self) -> str:
        return "bot-id"

    def read_messages(self, thread_id: str, *, after_id: str | None) -> list[dict[str, object]]:
        return self._messages

    def post(self, content: str, thread_id: str) -> bool:
        return True


class AckDiscord:
    def __init__(self, messages: list[dict[str, object]]) -> None:
        self.bot_token = "token"
        self._messages = messages
        self.posts: list[tuple[str, str]] = []

    def get_bot_user_id(self) -> str:
        return "bot-id"

    def read_messages(self, thread_id: str, *, after_id: str | None) -> list[dict[str, object]]:
        if after_id and self._messages and str(self._messages[0].get("id")) == after_id:
            return []
        return self._messages

    def post(self, content: str, thread_id: str) -> bool:
        self.posts.append((content, thread_id))
        return True


class FailDiscord:
    def __init__(self) -> None:
        self.bot_token = "token"

    def post(self, content: str, thread_id: str) -> bool:
        return False


class FakeJwz:
    def __init__(self, messages: list[dict[str, object]]) -> None:
        self._messages = messages

    def read_json(self, topic: str, *, limit: int) -> list[dict[str, object]]:
        return self._messages


class WindowJwz:
    def __init__(self, messages: list[dict[str, object]]) -> None:
        self._messages = messages
        self.calls: list[int] = []

    def read_json(self, topic: str, *, limit: int) -> list[dict[str, object]]:
        self.calls.append(limit)
        return self._messages[:limit]


class CollectDiscord:
    def __init__(self) -> None:
        self.posts: list[str] = []

    def post(self, content: str, thread_id: str) -> bool:
        self.posts.append(content)
        return True


def _write_prompts(
    tmp_path: Path,
    *,
    include_placeholder: bool = True,
    include_required_summary: bool = True,
) -> None:
    prompts_root = tmp_path / "loopfarm" / "prompts" / "implementation"
    prompts_root.mkdir(parents=True)
    for phase in ("planning", "forward", "backward"):
        header = f"{phase.upper()} {{PROMPT}} {{SESSION}} {{PROJECT}}"
        header = (
            header.replace("{PROMPT}", "{{PROMPT}}")
            .replace("{SESSION}", "{{SESSION}}")
            .replace("{PROJECT}", "{{PROJECT}}")
        )
        lines = [header, ""]
        if include_placeholder:
            lines.append("{{DYNAMIC_CONTEXT}}")
            lines.append("")
        lines.append("## Workflow")
        lines.append("Do the thing.")
        if include_required_summary:
            lines.extend(
                ["", "## Required Phase Summary", "Summary goes here.", ""]
            )
        (prompts_root / f"{phase}.md").write_text(
            "\n".join(lines), encoding="utf-8"
        )


def _write_prompt_variants(
    tmp_path: Path,
    *,
    marker: str,
) -> None:
    prompts_root = tmp_path / "loopfarm" / "prompts" / "implementation"
    prompts_root.mkdir(parents=True, exist_ok=True)
    for phase in ("planning", "forward", "backward"):
        header = f"{marker} {phase.upper()} {{PROMPT}} {{SESSION}} {{PROJECT}}"
        header = (
            header.replace("{PROMPT}", "{{PROMPT}}")
            .replace("{SESSION}", "{{SESSION}}")
            .replace("{PROJECT}", "{{PROJECT}}")
        )
        lines = [header, "", "## Required Phase Summary", "Summary goes here."]
        (prompts_root / f"{phase}.md").write_text(
            "\n".join(lines), encoding="utf-8"
        )


def _cfg(tmp_path: Path) -> LoopfarmConfig:
    model = CodexPhaseModel(model="test", reasoning="fast")
    return LoopfarmConfig(
        repo_root=tmp_path,
        cli="claude",
        model_override=None,
        skip_plan=True,
        project="test",
        prompt="Example prompt",
        code_model=model,
        plan_model=model,
        review_model=model,
    )


def test_build_phase_prompt_injects_discord_context(tmp_path: Path) -> None:
    _write_prompts(tmp_path)
    runner = LoopfarmRunner(_cfg(tmp_path))
    runner.pending_discord_context.append("hello")

    prompt = runner._build_phase_prompt("sess", "planning")

    assert "PLANNING Example prompt sess test" in prompt
    assert "Discord User Context" in prompt
    assert "hello" in prompt
    assert "## Required Phase Summary" in prompt
    assert prompt.index("Discord User Context") < prompt.index(
        "## Required Phase Summary"
    )


def test_build_phase_prompt_injects_pinned_context(tmp_path: Path) -> None:
    _write_prompts(tmp_path)
    runner = LoopfarmRunner(_cfg(tmp_path))
    runner.discord_context_override = "Pinned guidance"

    prompt = runner._build_phase_prompt("sess", "planning")

    assert "Discord Session Context" in prompt
    assert "Pinned guidance" in prompt
    assert "Discord User Context" not in prompt
    assert prompt.index("Discord Session Context") < prompt.index(
        "## Required Phase Summary"
    )


def test_pinned_context_persists_across_phases(tmp_path: Path) -> None:
    _write_prompts(tmp_path)
    runner = LoopfarmRunner(_cfg(tmp_path))
    runner.discord_context_override = "Carry over"

    prompt_one = runner._build_phase_prompt("sess", "planning")
    prompt_two = runner._build_phase_prompt("sess", "forward")

    assert "Carry over" in prompt_one
    assert "Carry over" in prompt_two


def test_pinned_context_renders_before_user_context(tmp_path: Path) -> None:
    _write_prompts(tmp_path)
    runner = LoopfarmRunner(_cfg(tmp_path))
    runner.discord_context_override = "Pinned guidance"
    runner.pending_discord_context.append("hello")

    prompt = runner._build_phase_prompt("sess", "forward")

    assert "Discord Session Context" in prompt
    assert "Discord User Context" in prompt
    assert prompt.index("Discord Session Context") < prompt.index(
        "Discord User Context"
    )
    assert prompt.index("Discord User Context") < prompt.index(
        "## Required Phase Summary"
    )


def test_build_phase_prompt_without_context_returns_base(tmp_path: Path) -> None:
    _write_prompts(tmp_path)
    runner = LoopfarmRunner(_cfg(tmp_path))

    prompt = runner._build_phase_prompt("sess", "forward")

    assert "FORWARD Example prompt sess test" in prompt
    assert "Discord User Context" not in prompt
    assert "{{DYNAMIC_CONTEXT}}" not in prompt


def test_prompt_injects_context_before_summary_without_placeholder(
    tmp_path: Path,
) -> None:
    _write_prompts(tmp_path, include_placeholder=False)
    runner = LoopfarmRunner(_cfg(tmp_path))
    runner.pending_discord_context.append("hello")

    prompt = runner._build_phase_prompt("sess", "forward")

    assert "Discord User Context" in prompt
    assert prompt.index("Discord User Context") < prompt.index(
        "## Required Phase Summary"
    )


def test_collect_discord_messages_filters_control_commands(tmp_path: Path, monkeypatch: object) -> None:
    runner = LoopfarmRunner(_cfg(tmp_path))
    runner.discord_thread_id = "thread"
    monkeypatch.setenv("LOOPFARM_DISCORD_AUTHORIZED_USERS", "u1")

    runner.discord = FakeDiscord(
        [
            {
                "id": "2",
                "content": "!pause",
                "author": {"id": "u1", "username": "operator"},
                "timestamp": "2026-01-30T12:00:01.000Z",
            },
            {
                "id": "1",
                "content": "hello",
                "author": {"id": "u1", "username": "operator"},
                "timestamp": "2026-01-30T12:00:00.000Z",
            },
        ]
    )

    runner._collect_discord_messages()
    ctx = runner._flush_discord_context()
    commands = runner._drain_discord_commands()

    assert "hello" in ctx
    assert "!pause" not in ctx
    assert len(commands) == 1
    assert commands[0].kind == "pause"


def test_collect_discord_messages_posts_ack(tmp_path: Path, monkeypatch: object) -> None:
    runner = LoopfarmRunner(_cfg(tmp_path))
    runner.discord_thread_id = "thread"
    monkeypatch.setenv("LOOPFARM_DISCORD_AUTHORIZED_USERS", "u1")

    runner.discord = AckDiscord(
        [
            {
                "id": "2",
                "content": "hello",
                "author": {"id": "u1", "username": "operator"},
                "timestamp": "2026-01-30T12:00:01.000Z",
            }
        ]
    )

    runner._collect_discord_messages()

    assert runner.discord.posts
    assert "Received 1 message" in runner.discord.posts[0][0]

    runner._collect_discord_messages()

    assert len(runner.discord.posts) == 1


def test_post_jwz_status_does_not_mark_seen_on_failure(tmp_path: Path) -> None:
    runner = LoopfarmRunner(_cfg(tmp_path))
    runner.discord_thread_id = "thread"
    runner.discord = FailDiscord()
    runner.jwz = FakeJwz(
        [
            {
                "id": "msg-1",
                "body": '{"decision":"COMPLETE","summary":"ok"}',
            }
        ]
    )

    runner._post_jwz_status("loopfarm:status:test-session")

    assert not runner.seen_jwz_ids


def test_jwz_poller_expands_window_until_seen(monkeypatch: object) -> None:
    monkeypatch.setenv("LOOPFARM_JWZ_POLL_LIMIT", "2")
    monkeypatch.setenv("LOOPFARM_JWZ_POLL_MAX", "8")
    messages = [
        {"id": "m6", "body": ""},
        {"id": "m5", "body": ""},
        {"id": "m4", "body": ""},
        {"id": "m3", "body": ""},
        {"id": "m2", "body": ""},
        {"id": "m1", "body": ""},
    ]
    jwz = WindowJwz(messages)
    poller = JwzPoller(
        jwz=jwz,
        discord=CollectDiscord(),
        thread_id="thread",
        topics=["topic"],
        stop_event=threading.Event(),
        seen_ids={"m1"},
        debug=False,
    )

    result, truncated = poller._read_topic_window("topic")

    assert jwz.calls == [2, 4, 8]
    assert result == messages
    assert not truncated


def test_jwz_poller_warns_on_truncation(monkeypatch: object) -> None:
    monkeypatch.setenv("LOOPFARM_JWZ_POLL_LIMIT", "2")
    monkeypatch.setenv("LOOPFARM_JWZ_POLL_MAX", "4")
    messages = [
        {"id": "m6", "body": ""},
        {"id": "m5", "body": ""},
        {"id": "m4", "body": ""},
        {"id": "m3", "body": ""},
        {"id": "m2", "body": ""},
        {"id": "m1", "body": ""},
    ]
    jwz = WindowJwz(messages)
    discord = CollectDiscord()
    poller = JwzPoller(
        jwz=jwz,
        discord=discord,
        thread_id="thread",
        topics=["topic"],
        stop_event=threading.Event(),
        seen_ids={"missing"},
        debug=False,
    )

    poller._post_topic("topic")

    assert any("Discord status backlog" in post for post in discord.posts)


def test_prompt_paths_use_shared_set_for_all_backends(tmp_path: Path) -> None:
    _write_prompt_variants(tmp_path, marker="BASE")

    cfg = replace(_cfg(tmp_path), forward_cli="codex")
    runner = LoopfarmRunner(cfg)

    planning_prompt = runner._render_phase_prompt("sess", "planning")
    forward_prompt = runner._render_phase_prompt("sess", "forward")
    backward_prompt = runner._render_phase_prompt("sess", "backward")

    assert planning_prompt.startswith("BASE PLANNING")
    assert backward_prompt.startswith("BASE BACKWARD")
    assert forward_prompt.startswith("BASE FORWARD")


def test_prompt_path_precedence_mode_then_implementation_then_legacy(
    tmp_path: Path,
) -> None:
    prompts_root = tmp_path / "loopfarm" / "prompts"
    impl_root = prompts_root / "implementation"
    research_root = prompts_root / "research"
    impl_root.mkdir(parents=True, exist_ok=True)
    research_root.mkdir(parents=True, exist_ok=True)

    (prompts_root / "forward.md").write_text(
        "LEGACY FORWARD {{PROMPT}}\n## Required Phase Summary\nSummary\n",
        encoding="utf-8",
    )
    (impl_root / "forward.md").write_text(
        "IMPLEMENTATION FORWARD {{PROMPT}}\n## Required Phase Summary\nSummary\n",
        encoding="utf-8",
    )
    (research_root / "forward.md").write_text(
        "RESEARCH FORWARD {{PROMPT}}\n## Required Phase Summary\nSummary\n",
        encoding="utf-8",
    )

    research_runner = LoopfarmRunner(replace(_cfg(tmp_path), mode="research"))
    writing_runner = LoopfarmRunner(replace(_cfg(tmp_path), mode="writing"))
    no_mode_runner = LoopfarmRunner(_cfg(tmp_path))

    assert research_runner._render_phase_prompt("sess", "forward").startswith(
        "RESEARCH FORWARD"
    )
    assert writing_runner._render_phase_prompt("sess", "forward").startswith(
        "IMPLEMENTATION FORWARD"
    )
    assert no_mode_runner._render_phase_prompt("sess", "forward").startswith(
        "IMPLEMENTATION FORWARD"
    )


def test_prompt_path_supports_legacy_root_templates(tmp_path: Path) -> None:
    prompts_root = tmp_path / "loopfarm" / "prompts"
    prompts_root.mkdir(parents=True, exist_ok=True)
    (prompts_root / "forward.md").write_text(
        "LEGACY FORWARD {{PROMPT}}\n## Required Phase Summary\nSummary\n",
        encoding="utf-8",
    )

    runner = LoopfarmRunner(replace(_cfg(tmp_path), mode="implementation"))

    assert runner._render_phase_prompt("sess", "forward").startswith("LEGACY FORWARD")


def test_writing_mode_injects_guidance_into_shared_prompts(
    tmp_path: Path,
) -> None:
    _write_prompt_variants(tmp_path, marker="BASE")

    cfg = replace(_cfg(tmp_path), forward_cli="codex", mode="writing")
    runner = LoopfarmRunner(cfg)

    planning_prompt = runner._build_phase_prompt("sess", "planning")
    forward_prompt = runner._build_phase_prompt("sess", "forward")
    backward_prompt = runner._build_phase_prompt("sess", "backward")

    assert planning_prompt.startswith("BASE PLANNING")
    assert forward_prompt.startswith("BASE FORWARD")
    assert backward_prompt.startswith("BASE BACKWARD")
    assert "## Writing Mode" in planning_prompt
    assert "## Writing Mode" in forward_prompt
    assert "## Writing Mode" in backward_prompt
