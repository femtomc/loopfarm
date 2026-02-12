from __future__ import annotations

from typing import Any, Callable, Protocol

class OrchestratorConfig(Protocol):
    loop_plan_once: bool
    loop_steps: tuple[tuple[str, int], ...]
    termination_phase: str
    loop_report_source_phase: str | None
    loop_report_target_phases: tuple[str, ...]


RunOperationalPhaseFn = Callable[..., str]
ReadCompletionFn = Callable[[str], tuple[str, str]]
MarkCompleteFn = Callable[[int, str], int]
GitHeadFn = Callable[[], str]
BuildForwardReportFn = Callable[..., dict[str, Any]]
PostForwardReportFn = Callable[[str, dict[str, Any]], None]
EmitFn = Callable[..., None]
SetLastForwardReportFn = Callable[[dict[str, Any] | None], None]


class LoopOrchestrator:
    def __init__(
        self,
        *,
        cfg: OrchestratorConfig,
        run_operational_phase: RunOperationalPhaseFn,
        read_completion: ReadCompletionFn,
        mark_complete: MarkCompleteFn,
        git_head: GitHeadFn,
        build_forward_report: BuildForwardReportFn,
        post_forward_report: PostForwardReportFn,
        emit: EmitFn,
        set_last_forward_report: SetLastForwardReportFn,
    ) -> None:
        self.cfg = cfg
        self.run_operational_phase = run_operational_phase
        self.read_completion = read_completion
        self.mark_complete = mark_complete
        self.git_head = git_head
        self.build_forward_report = build_forward_report
        self.post_forward_report = post_forward_report
        self.emit = emit
        self.set_last_forward_report = set_last_forward_report

    def run_configured_loop(self, session_id: str) -> int:
        loop_steps = self.cfg.loop_steps
        for phase, repeat in loop_steps:
            if not phase.strip():
                raise SystemExit("loop configuration has empty phase name")
            if repeat < 1:
                raise SystemExit(
                    f"loop configuration has invalid repeat count for {phase!r}: {repeat}"
                )
        termination_phase = self.cfg.termination_phase.strip()
        if not termination_phase:
            raise SystemExit("termination phase is required")
        phase_names = {phase for phase, _ in loop_steps}
        if termination_phase not in phase_names:
            raise SystemExit(
                f"termination phase {termination_phase!r} is not present in loop steps"
            )

        loop_iteration = 0
        last_forward_report: dict[str, Any] | None = None

        while True:
            loop_iteration += 1
            source_summaries: list[str] = []
            report_pre_head: str | None = None
            report_ready = False
            report_source = self.cfg.loop_report_source_phase
            report_targets = set(self.cfg.loop_report_target_phases)

            for phase, repeat in loop_steps:
                for run_index in range(1, repeat + 1):
                    if report_source and phase == report_source and report_pre_head is None:
                        report_pre_head = self.git_head()

                    if (
                        report_source
                        and report_targets
                        and phase in report_targets
                        and not report_ready
                    ):
                        if report_pre_head is None:
                            report_pre_head = self.git_head()
                        report_post_head = self.git_head()
                        source_summary = "\n\n".join(
                            summary for summary in source_summaries if summary.strip()
                        )
                        cycle_report = self.build_forward_report(
                            session_id=session_id,
                            pre_head=report_pre_head,
                            post_head=report_post_head,
                            summary=source_summary,
                        )
                        last_forward_report = cycle_report
                        self.set_last_forward_report(cycle_report)
                        self.post_forward_report(session_id, cycle_report)
                        self.emit(
                            "phase.forward_report",
                            phase=report_source,
                            iteration=loop_iteration,
                            payload=cycle_report,
                        )
                        report_ready = True

                    summary = self.run_operational_phase(
                        session_id=session_id,
                        phase=phase,
                        iteration=loop_iteration,
                        forward_report=(
                            last_forward_report if phase in report_targets else None
                        ),
                        run_index=run_index if repeat > 1 else None,
                        run_total=repeat if repeat > 1 else None,
                    )

                    if report_source and phase == report_source and summary.strip():
                        source_summaries.append(summary)

                    if phase == termination_phase:
                        decision, completion_summary = self.read_completion(session_id)
                        if decision == "COMPLETE":
                            return self.mark_complete(loop_iteration, completion_summary)
