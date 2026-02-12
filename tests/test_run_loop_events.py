from __future__ import annotations

from dataclasses import replace
import io
import os
from pathlib import Path

from loopfarm.events import LoopfarmEvent
from loopfarm.runner import CodexPhaseModel, LoopfarmConfig, LoopfarmIO, LoopfarmRunner, run_loop


class FakeBackend:
    name = "fake"

    def __init__(self) -> None:
        self.runs: list[tuple[str, Path, Path]] = []

    def build_argv(
        self,
        *,
        phase: str,
        prompt: str,
        last_message_path: Path,
        cfg: LoopfarmConfig,
    ) -> list[str]:
        return ["fake", phase]

    def run(
        self,
        *,
        phase: str,
        prompt: str,
        output_path: Path,
        last_message_path: Path,
        cfg: LoopfarmConfig,
        event_sink,
        stdout,
        stderr,
    ) -> bool:
        self.runs.append((phase, output_path, last_message_path))
        if stdout:
            stdout.write(f"backend stdout ({phase})\n")
        if stderr:
            stderr.write(f"backend stderr ({phase})\n")
        output_path.write_text(f"output {phase}\n", encoding="utf-8")
        last_message_path.write_text(f"summary {phase}\n", encoding="utf-8")
        if event_sink:
            event_sink("stream.text", {"text": f"hello {phase}"})
        return True

    def extract_summary(
        self,
        *,
        phase: str,
        output_path: Path,
        last_message_path: Path,
        cfg: LoopfarmConfig,
    ) -> str:
        if last_message_path.exists():
            return last_message_path.read_text(encoding="utf-8").strip()
        return ""

    def prompt_suffix(self, *, phase: str, cfg: LoopfarmConfig) -> str:
        return ""


def _write_prompts(tmp_path: Path) -> None:
    prompts_root = tmp_path / "loopfarm" / "prompts" / "implementation"
    prompts_root.mkdir(parents=True)
    for phase in (
        "planning",
        "forward",
        "documentation",
        "architecture",
        "backward",
    ):
        (prompts_root / f"{phase}.md").write_text(
            "## Required Phase Summary\n\nSummary goes here.\n",
            encoding="utf-8",
        )


def _cfg(tmp_path: Path) -> LoopfarmConfig:
    model = CodexPhaseModel(model="test", reasoning="fast")
    return LoopfarmConfig(
        repo_root=tmp_path,
        cli="fake",
        model_override=None,
        skip_plan=True,
        project="test",
        prompt="Example prompt",
        code_model=model,
        plan_model=model,
        review_model=model,
    )


def _restore_env(key: str, value: str | None) -> None:
    if value is None:
        os.environ.pop(key, None)
    else:
        os.environ[key] = value


def test_run_loop_event_sink_and_backend_provider(
    tmp_path: Path, monkeypatch
) -> None:
    _write_prompts(tmp_path)
    cfg = _cfg(tmp_path)
    backend = FakeBackend()
    provider_calls: list[tuple[str, str]] = []
    events: list[LoopfarmEvent] = []

    def backend_provider(name: str, phase: str, _: LoopfarmConfig) -> FakeBackend:
        provider_calls.append((name, phase))
        return backend

    def event_sink(event: LoopfarmEvent) -> None:
        events.append(event)

    def fake_read_completion(self: LoopfarmRunner, session_id: str) -> tuple[str, str]:
        return ("COMPLETE", "done")

    monkeypatch.setattr(LoopfarmRunner, "_read_completion", fake_read_completion)

    stdout = io.StringIO()
    stderr = io.StringIO()
    prev_session = os.environ.get("LOOPFARM_SESSION")
    prev_thread = os.environ.get("DISCORD_THREAD_ID")

    try:
        exit_code = run_loop(
            cfg,
            session_id="sess-123",
            event_sink=event_sink,
            io=LoopfarmIO(stdout=stdout, stderr=stderr),
            backend_provider=backend_provider,
        )
    finally:
        _restore_env("LOOPFARM_SESSION", prev_session)
        _restore_env("DISCORD_THREAD_ID", prev_thread)

    assert exit_code == 0

    types = [ev.type for ev in events]
    assert "session.start" in types
    assert "phase.start" in types
    assert "phase.end" in types
    assert "session.end" in types

    phase_starts = {(ev.phase, ev.iteration) for ev in events if ev.type == "phase.start"}
    phase_ends = {(ev.phase, ev.iteration) for ev in events if ev.type == "phase.end"}
    assert ("forward", 1) in phase_starts
    assert ("backward", 1) in phase_starts
    assert ("forward", 1) in phase_ends
    assert ("backward", 1) in phase_ends

    stream_event = next(ev for ev in events if ev.type == "stream.text")
    assert stream_event.phase in {"forward", "backward"}
    assert stream_event.iteration == 1
    assert stream_event.payload.get("session_id") == "sess-123"
    assert stream_event.payload.get("text") in {"hello forward", "hello backward"}

    phases = {phase for _, phase in provider_calls}
    assert "forward" in phases
    assert "backward" in phases

    assert "backend stdout" in stdout.getvalue()
    assert "backend stderr" in stderr.getvalue()


def test_run_loop_implementation_mode_runs_documentation_and_architecture(
    tmp_path: Path, monkeypatch
) -> None:
    _write_prompts(tmp_path)
    cfg = _cfg(tmp_path)
    cfg = replace(
        cfg,
        mode="implementation",
        loop_plan_once=False,
        loop_steps=(
            ("forward", 2),
            ("documentation", 1),
            ("architecture", 1),
            ("backward", 1),
        ),
        loop_report_source_phase="forward",
        loop_report_target_phases=("documentation", "architecture", "backward"),
    )
    backend = FakeBackend()
    events: list[LoopfarmEvent] = []

    def backend_provider(name: str, phase: str, _: LoopfarmConfig) -> FakeBackend:
        return backend

    def event_sink(event: LoopfarmEvent) -> None:
        events.append(event)

    def fake_read_completion(self: LoopfarmRunner, session_id: str) -> tuple[str, str]:
        return ("COMPLETE", "done")

    monkeypatch.setattr(LoopfarmRunner, "_read_completion", fake_read_completion)

    stdout = io.StringIO()
    stderr = io.StringIO()
    prev_session = os.environ.get("LOOPFARM_SESSION")
    prev_thread = os.environ.get("DISCORD_THREAD_ID")

    try:
        exit_code = run_loop(
            cfg,
            session_id="sess-impl",
            event_sink=event_sink,
            io=LoopfarmIO(stdout=stdout, stderr=stderr),
            backend_provider=backend_provider,
        )
    finally:
        _restore_env("LOOPFARM_SESSION", prev_session)
        _restore_env("DISCORD_THREAD_ID", prev_thread)

    assert exit_code == 0

    phase_starts = [
        (ev.phase, ev.iteration)
        for ev in events
        if ev.type == "phase.start" and ev.iteration == 1
    ]
    assert ("forward", 1) in phase_starts
    assert ("documentation", 1) in phase_starts
    assert ("architecture", 1) in phase_starts
    assert ("backward", 1) in phase_starts
    assert phase_starts.count(("forward", 1)) == 2

    forward_reports = [
        ev for ev in events if ev.type == "phase.forward_report" and ev.iteration == 1
    ]
    assert len(forward_reports) == 1


def test_run_loop_research_mode_runs_research_and_curation(
    tmp_path: Path, monkeypatch
) -> None:
    _write_prompts(tmp_path)
    research_root = tmp_path / "loopfarm" / "prompts" / "research"
    research_root.mkdir(parents=True)
    for phase in ("planning", "research", "curation", "backward"):
        (research_root / f"{phase}.md").write_text(
            "## Required Phase Summary\n\nSummary goes here.\n",
            encoding="utf-8",
        )

    cfg = replace(
        _cfg(tmp_path),
        mode="research",
        loop_plan_once=False,
        loop_steps=(("research", 2), ("curation", 1), ("backward", 1)),
    )
    backend = FakeBackend()
    events: list[LoopfarmEvent] = []

    def backend_provider(name: str, phase: str, _: LoopfarmConfig) -> FakeBackend:
        return backend

    def event_sink(event: LoopfarmEvent) -> None:
        events.append(event)

    def fake_read_completion(self: LoopfarmRunner, session_id: str) -> tuple[str, str]:
        return ("COMPLETE", "ready")

    monkeypatch.setattr(LoopfarmRunner, "_read_completion", fake_read_completion)

    exit_code = run_loop(
        cfg,
        session_id="sess-research",
        event_sink=event_sink,
        io=LoopfarmIO(stdout=io.StringIO(), stderr=io.StringIO()),
        backend_provider=backend_provider,
    )

    assert exit_code == 0

    phase_starts = [
        (ev.phase, ev.iteration)
        for ev in events
        if ev.type == "phase.start" and ev.iteration == 1
    ]
    assert phase_starts.count(("research", 1)) == 2
    assert ("curation", 1) in phase_starts
    assert ("backward", 1) in phase_starts
    assert not any(ev.type == "phase.forward_report" for ev in events)
