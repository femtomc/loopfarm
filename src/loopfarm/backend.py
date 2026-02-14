"""Backend runners for Claude, Codex, OpenCode, pi, and Gemini CLI tools."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Callable


class Backend:
    name: str

    def build_argv(
        self,
        prompt: str,
        model: str,
        reasoning: str,
        cwd: Path,
    ) -> list[str]:
        raise NotImplementedError

    def run(
        self,
        prompt: str,
        model: str,
        reasoning: str,
        cwd: Path,
        on_line: Callable[[str], None] | None = None,
        tee_path: Path | None = None,
    ) -> int:
        argv = self.build_argv(prompt, model, reasoning, cwd)
        tee_fh = open(tee_path, "w") if tee_path else None
        try:
            proc = subprocess.Popen(
                argv,
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            assert proc.stdout is not None
            while True:
                line = proc.stdout.readline()
                if not line and proc.poll() is not None:
                    break
                if not line:
                    continue
                line = line.rstrip("\n")
                if on_line:
                    on_line(line)
                if tee_fh:
                    tee_fh.write(line + "\n")
                    tee_fh.flush()
            return proc.wait()
        finally:
            if tee_fh:
                tee_fh.close()


class ClaudeBackend(Backend):
    name = "claude"

    def build_argv(
        self,
        prompt: str,
        model: str,
        reasoning: str,
        cwd: Path,
    ) -> list[str]:
        return [
            "claude",
            "--dangerously-skip-permissions",
            "-p",
            "--output-format",
            "stream-json",
            "--verbose",
            "--include-partial-messages",
            "--model",
            model,
            prompt,
        ]


class CodexBackend(Backend):
    name = "codex"

    def build_argv(
        self,
        prompt: str,
        model: str,
        reasoning: str,
        cwd: Path,
    ) -> list[str]:
        return [
            "codex",
            "exec",
            "--dangerously-bypass-approvals-and-sandbox",
            "--json",
            "-C",
            str(cwd),
            "-m",
            model,
            "-c",
            f"reasoning={reasoning}",
            prompt,
        ]


def _pi_stream_has_error(line: str) -> bool:
    """Return True when a pi JSON stream line indicates an assistant failure."""
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return False

    etype = event.get("type")
    if etype == "message_update":
        assistant_event = event.get("assistantMessageEvent", {})
        if isinstance(assistant_event, dict) and assistant_event.get("type") == "error":
            return True

    if etype == "message_end":
        message = event.get("message", {})
        if not isinstance(message, dict):
            return False
        if message.get("role") != "assistant":
            return False
        return message.get("stopReason") in ("error", "aborted")

    return False


class OpenCodeBackend(Backend):
    name = "opencode"

    def build_argv(
        self,
        prompt: str,
        model: str,
        reasoning: str,
        cwd: Path,
    ) -> list[str]:
        return [
            "opencode",
            "run",
            "--format",
            "json",
            "--dir",
            str(cwd),
            "--model",
            model,
            "--variant",
            reasoning,
            prompt,
        ]


def _gemini_stream_has_failure(line: str) -> bool:
    """Return True when a Gemini stream-json result event reports failure."""
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return False

    if event.get("type") != "result":
        return False
    status = event.get("status")
    if not isinstance(status, str):
        return False
    return status.lower() != "success"


class PiBackend(Backend):
    name = "pi"

    def build_argv(
        self,
        prompt: str,
        model: str,
        reasoning: str,
        cwd: Path,
    ) -> list[str]:
        return [
            "pi",
            "--mode",
            "json",
            "--no-session",
            "--model",
            model,
            "--thinking",
            reasoning,
            prompt,
        ]

    def run(
        self,
        prompt: str,
        model: str,
        reasoning: str,
        cwd: Path,
        on_line: Callable[[str], None] | None = None,
        tee_path: Path | None = None,
    ) -> int:
        saw_assistant_error = False

        def _on_line(line: str) -> None:
            nonlocal saw_assistant_error
            if _pi_stream_has_error(line):
                saw_assistant_error = True
            if on_line:
                on_line(line)

        exit_code = super().run(
            prompt,
            model,
            reasoning,
            cwd,
            on_line=_on_line,
            tee_path=tee_path,
        )
        if exit_code == 0 and saw_assistant_error:
            return 1
        return exit_code


class GeminiBackend(Backend):
    name = "gemini"

    def build_argv(
        self,
        prompt: str,
        model: str,
        reasoning: str,
        cwd: Path,
    ) -> list[str]:
        return [
            "gemini",
            "--output-format",
            "stream-json",
            "--model",
            model,
            "--yolo",
            "--prompt",
            prompt,
        ]

    def run(
        self,
        prompt: str,
        model: str,
        reasoning: str,
        cwd: Path,
        on_line: Callable[[str], None] | None = None,
        tee_path: Path | None = None,
    ) -> int:
        saw_result_failure = False

        def _on_line(line: str) -> None:
            nonlocal saw_result_failure
            if _gemini_stream_has_failure(line):
                saw_result_failure = True
            if on_line:
                on_line(line)

        exit_code = super().run(
            prompt,
            model,
            reasoning,
            cwd,
            on_line=_on_line,
            tee_path=tee_path,
        )
        if exit_code == 0 and saw_result_failure:
            return 1
        return exit_code


_BACKENDS: dict[str, Backend] = {
    "claude": ClaudeBackend(),
    "codex": CodexBackend(),
    "opencode": OpenCodeBackend(),
    "pi": PiBackend(),
    "gemini": GeminiBackend(),
}


def get_backend(name: str) -> Backend:
    b = _BACKENDS.get(name)
    if b is None:
        raise ValueError(f"unknown backend: {name!r} (available: {list(_BACKENDS)})")
    return b
