from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any, Callable

from .backends import Backend, get_backend
from .runtime.control import ControlPlane
from .runtime.events import EventSink, LoopfarmEvent, StreamEventSink
from .forum import Forum
from .runtime.forward_report import ForwardReportService
from .runtime.orchestrator import LoopOrchestrator
from .runtime.phase_executor import PhaseExecutor, PhaseExecutorPalette
from .runtime.prompt_resolver import PromptResolver
from .stores.session import SessionStore
from .util import (
    format_duration,
    new_session_id,
    utc_now_iso,
)


BLUE = "\033[34m"
WHITE = "\033[37m"
GRAY = "\033[90m"
CYAN = "\033[36m"
GREEN = "\033[32m"
MAGENTA = "\033[35m"
RED = "\033[31m"
YELLOW = "\033[33m"
RESET = "\033[0m"


@dataclass(frozen=True)
class CodexPhaseModel:
    model: str
    reasoning: str


class StopRequested(Exception):
    pass


@dataclass(frozen=True)
class LoopfarmConfig:
    repo_root: Path
    project: str
    prompt: str
    loop_steps: tuple[tuple[str, int], ...]
    termination_phase: str
    loop_report_source_phase: str | None = None
    loop_report_target_phases: tuple[str, ...] = ()
    phase_models: tuple[tuple[str, CodexPhaseModel], ...] = ()
    phase_cli_overrides: tuple[tuple[str, str], ...] = ()
    phase_prompt_overrides: tuple[tuple[str, str], ...] = ()
    phase_injections: tuple[tuple[str, tuple[str, ...]], ...] = ()
    show_reasoning: bool = False
    show_command_output: bool = False
    show_command_start: bool = False
    show_small_output: bool = False
    show_tokens: bool = False
    max_output_lines: int = 60
    max_output_chars: int = 2000
    control_poll_seconds: int = 5
    forward_report_max_lines: int = 20
    forward_report_max_commits: int = 12
    forward_report_max_summary_chars: int = 800

    def phase_model(self, phase: str) -> CodexPhaseModel | None:
        for name, model in self.phase_models:
            if name == phase:
                return model
        return None

    def phase_cli(self, phase: str) -> str:
        for name, cli in self.phase_cli_overrides:
            if name == phase and cli:
                return cli
        raise KeyError(f"missing CLI for phase {phase!r}")


@dataclass(frozen=True)
class LoopfarmIO:
    stdout: IO[str] | None = None
    stderr: IO[str] | None = None


BackendProvider = Callable[[str, str, LoopfarmConfig], Backend]


class LoopfarmRunner:
    def __init__(
        self,
        cfg: LoopfarmConfig,
        *,
        event_sink: EventSink | None = None,
        io: LoopfarmIO | None = None,
        backend_provider: BackendProvider | None = None,
    ) -> None:
        self.cfg = cfg
        self.event_sink = event_sink
        self.backend_provider = backend_provider
        self.stdout = io.stdout if io and io.stdout else sys.stdout
        self.stderr = io.stderr if io and io.stderr else sys.stderr
        self.forum = Forum.from_workdir(cfg.repo_root)
        self.session_store = SessionStore(self.forum)
        self.control_plane = ControlPlane(
            self.session_store,
            poll_seconds=max(1, int(cfg.control_poll_seconds)),
        )
        self.forward_reports = ForwardReportService(
            repo_root=cfg.repo_root,
            forum=self.forum,
            max_lines=max(1, int(cfg.forward_report_max_lines)),
            max_commits=max(1, int(cfg.forward_report_max_commits)),
            max_summary_chars=max(1, int(cfg.forward_report_max_summary_chars)),
        )
        self.prompt_resolver = PromptResolver(self.cfg, self.session_store)
        self.phase_executor = PhaseExecutor(
            prompt=self.cfg.prompt,
            prompt_path=self._prompt_path,
            control_checkpoint=self._control_checkpoint,
            build_phase_prompt=self._build_phase_prompt,
            run_agent=self._run_agent,
            phase_summary=self._phase_summary,
            store_phase_summary=self._store_phase_summary,
            emit=self._emit,
            print_line=self._print,
            sleep=self._sleep,
            tmp_path=self._tmp_path,
            cleanup_paths=self._cleanup_paths,
            palette=PhaseExecutorPalette(
                blue=BLUE,
                white=WHITE,
                gray=GRAY,
                cyan=CYAN,
                green=GREEN,
                magenta=MAGENTA,
                red=RED,
                yellow=YELLOW,
                reset=RESET,
            ),
        )
        self.orchestrator = LoopOrchestrator(
            cfg=self.cfg,
            run_operational_phase=self._run_operational_phase,
            read_completion=self._read_completion,
            mark_complete=lambda iteration, summary: self._mark_complete(
                iteration=iteration, summary=summary
            ),
            git_head=self._git_head,
            build_forward_report=self._build_forward_report,
            post_forward_report=self._post_forward_report,
            emit=self._emit,
            set_last_forward_report=self._set_last_forward_report,
        )
        self.session_context_override = ""
        self.paused = False
        self._last_control_signature = ""
        self.last_phase = "startup"
        self.start_monotonic: float = 0.0
        self.session_status = "interrupted"
        self.last_forward_report: dict[str, Any] | None = None
        self.session_id: str | None = None

    def _print(self, *parts: object) -> None:
        print(*parts, file=self.stdout)

    def _emit(
        self,
        event_type: str,
        *,
        phase: str | None = None,
        iteration: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        if not self.event_sink:
            return
        full_payload = dict(payload or {})
        if self.session_id:
            full_payload.setdefault("session_id", self.session_id)
        event = LoopfarmEvent(
            type=event_type,
            timestamp=utc_now_iso(),
            phase=phase,
            iteration=iteration,
            payload=full_payload,
        )
        self.event_sink(event)

    def _stream_event_sink(
        self, *, phase: str, iteration: int | None
    ) -> StreamEventSink:
        def sink(event_type: str, payload: dict[str, Any]) -> None:
            self._emit(event_type, phase=phase, iteration=iteration, payload=payload)

        return sink

    def run(self, *, session_id: str) -> int:
        start_time = utc_now_iso()
        self.start_monotonic = time.monotonic()
        self.session_id = session_id

        self.session_store.update_session_meta(
            session_id,
            {"prompt": self.cfg.prompt, "started": start_time, "status": "running"},
            author="runner",
        )
        self._emit(
            "session.start",
            payload={
                "started": start_time,
                "prompt": self.cfg.prompt,
                "project": self.cfg.project,
                "repo_root": str(self.cfg.repo_root),
                "loop_steps": list(self.cfg.loop_steps),
                "termination_phase": self.cfg.termination_phase,
                "loop_report_source_phase": self.cfg.loop_report_source_phase,
                "loop_report_target_phases": list(self.cfg.loop_report_target_phases),
                "phase_cli_overrides": list(self.cfg.phase_cli_overrides),
                "phase_prompt_overrides": list(self.cfg.phase_prompt_overrides),
                "phase_injections": [
                    [phase, list(injections)]
                    for phase, injections in self.cfg.phase_injections
                ],
            },
        )
        self._load_session_context_override(session_id)

        self._print(
            f"{BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{RESET}"
        )
        self._print(f"{WHITE}  LOOPFARM{RESET}  {GRAY}{session_id}{RESET}")
        self._print(f"  {GRAY}{self.cfg.prompt}{RESET}")
        self._print(
            f"{BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{RESET}\n"
        )

        try:
            return self._configured_loop(session_id)
        except StopRequested:
            return 1
        except KeyboardInterrupt:
            self.session_status = "interrupted"
            return 1
        finally:
            self._finalize_session(session_id)

    def _finalize_session(self, session_id: str) -> None:
        end_time = utc_now_iso()
        duration = max(0, int(time.monotonic() - self.start_monotonic))
        duration_str = format_duration(duration)

        if self.session_status != "complete":
            self.session_store.update_session_meta(
                session_id,
                {"status": self.session_status, "ended": end_time},
                author="runner",
            )
            title = "Session Interrupted"
            if self.session_status == "stopped":
                title = "Session Stopped"
            self._print(
                f"{YELLOW}⚠ {title}: duration={duration_str}, phase={self.last_phase}, ended={end_time}{RESET}"
            )
            self._emit(
                "session.end",
                payload={
                    "status": self.session_status,
                    "ended": end_time,
                    "duration_seconds": duration,
                    "duration": duration_str,
                    "last_phase": self.last_phase,
                },
            )
            self._print(f"\n{RED}Stopped.{RESET}")
        else:
            self.session_store.update_session_meta(
                session_id,
                {"status": "complete", "ended": end_time},
                author="runner",
            )
            self._emit(
                "session.end",
                payload={
                    "status": "complete",
                    "ended": end_time,
                    "duration_seconds": duration,
                    "duration": duration_str,
                    "last_phase": self.last_phase,
                },
            )

    def _set_session_context_override(self, text: str, *, author: str | None) -> None:
        self.session_context_override = text
        if self.session_id:
            self.session_store.update_session_meta(
                self.session_id,
                {"session_context": text},
                author=author,
            )

    def _clear_session_context_override(self, *, author: str | None) -> None:
        self._set_session_context_override("", author=author)

    def _control_checkpoint(
        self, *, session_id: str, phase: str, iteration: int | None
    ) -> None:
        result = self.control_plane.checkpoint(
            session_id=session_id,
            phase=phase,
            iteration=iteration,
            paused=self.paused,
            session_status=self.session_status,
            last_signature=self._last_control_signature,
            set_session_context=lambda text, author: self._set_session_context_override(
                text, author=author
            ),
            clear_session_context=lambda author: self._clear_session_context_override(
                author=author
            ),
            emit=lambda event_type, payload: self._emit(
                event_type,
                phase=phase,
                iteration=iteration,
                payload=payload,
            ),
            print_line=self._print,
            sleep=self._sleep,
            pause_message=f"\n{YELLOW}⏸ Paused before {phase}.{RESET}",
            resume_message=f"{GREEN}▶ Resumed.{RESET}",
            stop_message=f"\n{RED}⛔ Stop requested.{RESET}",
        )
        self.paused = result.paused
        self.session_status = result.session_status
        self._last_control_signature = result.last_signature
        if result.stop_requested:
            raise StopRequested()

    def _load_session_context_override(self, session_id: str) -> None:
        ctx = self.control_plane.load_session_context_override(session_id).strip()
        if ctx:
            self.session_context_override = ctx

    def _cli_for_phase(self, phase: str) -> str:
        try:
            return self.cfg.phase_cli(phase)
        except KeyError as exc:
            raise SystemExit(str(exc)) from exc

    def _backend_for_phase(self, phase: str) -> Backend:
        name = self._cli_for_phase(phase)
        if self.backend_provider:
            return self.backend_provider(name, phase, self.cfg)
        try:
            return get_backend(name)
        except KeyError as exc:
            raise SystemExit(str(exc)) from exc

    def _prompt_path(self, phase: str) -> Path:
        return self.prompt_resolver.prompt_path(phase)

    def _run_operational_phase(
        self,
        *,
        session_id: str,
        phase: str,
        iteration: int,
        forward_report: dict[str, Any] | None = None,
        run_index: int | None = None,
        run_total: int | None = None,
    ) -> str:
        self.last_phase = phase
        return self.phase_executor.run_operational_phase(
            session_id=session_id,
            phase=phase,
            iteration=iteration,
            forward_report=forward_report,
            run_index=run_index,
            run_total=run_total,
        )

    def _mark_complete(self, *, iteration: int, summary: str) -> int:
        self.session_status = "complete"
        duration = max(0, int(time.monotonic() - self.start_monotonic))
        self._emit(
            "session.complete",
            payload={
                "iterations": iteration,
                "summary": summary,
                "ended": utc_now_iso(),
            },
        )
        self._print(f"\n{GREEN}✓ Complete.{RESET}")
        return 0

    def _set_last_forward_report(self, payload: dict[str, Any] | None) -> None:
        self.last_forward_report = payload

    def _configured_loop(self, session_id: str) -> int:
        return self.orchestrator.run_configured_loop(session_id)

    def _render_phase_prompt(self, session_id: str, phase: str) -> str:
        return self.prompt_resolver.render_phase_prompt(session_id, phase)

    def _build_phase_prompt(
        self,
        session_id: str,
        phase: str,
        *,
        forward_report: dict[str, Any] | None = None,
    ) -> str:
        return self.prompt_resolver.build_phase_prompt(
            session_id=session_id,
            phase=phase,
            session_context=self.session_context_override,
            prompt_suffix=self._backend_for_phase(phase).prompt_suffix(
                phase=phase, cfg=self.cfg
            ),
            forward_report=forward_report,
            read_forward_report=self._read_forward_report,
            format_forward_report=self._format_forward_report_for_prompt,
        )

    def _phase_summary(
        self, phase: str, output_path: Path, last_message_path: Path
    ) -> str:
        backend = self._backend_for_phase(phase)
        return backend.extract_summary(
            phase=phase,
            output_path=output_path,
            last_message_path=last_message_path,
            cfg=self.cfg,
        )

    def _git_capture(self, argv: list[str]) -> str:
        return self.forward_reports.git_capture(argv)

    def _git_lines(self, argv: list[str]) -> list[str]:
        return self.forward_reports.git_lines(argv)

    def _git_head(self) -> str:
        return self.forward_reports.git_head()

    def _build_forward_report(
        self, *, session_id: str, pre_head: str, post_head: str, summary: str
    ) -> dict[str, Any]:
        return self.forward_reports.build_forward_report(
            session_id=session_id,
            pre_head=pre_head,
            post_head=post_head,
            summary=summary,
        )

    def _post_forward_report(self, session_id: str, payload: dict[str, Any]) -> None:
        self.forward_reports.post_forward_report(session_id, payload)

    def _read_forward_report(self, session_id: str) -> dict[str, Any] | None:
        return self.forward_reports.read_forward_report(session_id)

    def _format_forward_report_for_prompt(self, payload: dict[str, Any] | None) -> str:
        return self.forward_reports.format_for_prompt(payload)

    def _inject_forward_report(
        self,
        base: str,
        session_id: str,
        payload: dict[str, Any] | None,
    ) -> str:
        return self.prompt_resolver.inject_forward_report(
            base,
            session_id=session_id,
            payload=payload,
            read_forward_report=self._read_forward_report,
            format_forward_report=self._format_forward_report_for_prompt,
        )

    def _store_phase_summary(
        self, session_id: str, phase: str, iteration: int, summary: str
    ) -> None:
        if not summary.strip():
            return
        self.session_store.store_phase_summary(session_id, phase, iteration, summary)

    def _build_phase_briefing(self, session_id: str) -> str:
        return self.prompt_resolver.build_phase_briefing(session_id)

    def _inject_phase_briefing(self, base: str, session_id: str) -> str:
        return self.prompt_resolver.inject_phase_briefing(base, session_id)

    def _run_agent(
        self,
        phase: str,
        prompt: str,
        output_path: Path,
        last_message_path: Path,
        *,
        iteration: int | None,
    ) -> bool:
        backend = self._backend_for_phase(phase)
        stream_sink = (
            self._stream_event_sink(phase=phase, iteration=iteration)
            if self.event_sink
            else None
        )
        return backend.run(
            phase=phase,
            prompt=prompt,
            output_path=output_path,
            last_message_path=last_message_path,
            cfg=self.cfg,
            event_sink=stream_sink,
            stdout=self.stdout,
            stderr=self.stderr,
        )

    def _read_completion(self, session_id: str) -> tuple[str, str]:
        msgs = self.forum.read_json(f"loopfarm:status:{session_id}", limit=1)
        if not msgs:
            msgs = self.forum.read_json(f"loopfarm:status:{session_id}", limit=1)
        if not msgs:
            return "", ""
        body = msgs[0].get("body") or ""
        if not body:
            return "", ""
        try:
            payload = json.loads(body)
        except Exception:
            return "", ""
        return str(payload.get("decision") or ""), str(payload.get("summary") or "")

    def _tmp_path(self, *, prefix: str = "loopfarm_", suffix: str = ".log") -> Path:
        fd, name = tempfile.mkstemp(prefix=prefix, suffix=suffix)
        os.close(fd)
        return Path(name)

    def _cleanup_paths(self, *paths: Path) -> None:
        for p in paths:
            try:
                p.unlink()
            except OSError:
                pass

    def _sleep(self, seconds: int) -> None:
        try:
            threading.Event().wait(seconds)
        except KeyboardInterrupt:
            raise


def run_loop(
    cfg: LoopfarmConfig,
    *,
    session_id: str | None = None,
    event_sink: EventSink | None = None,
    io: LoopfarmIO | None = None,
    backend_provider: BackendProvider | None = None,
) -> int:
    runner = LoopfarmRunner(
        cfg,
        event_sink=event_sink,
        io=io,
        backend_provider=backend_provider,
    )
    if session_id is None:
        session_id = new_session_id()
    return runner.run(session_id=session_id)
