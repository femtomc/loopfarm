from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..util import utc_now_iso


ControlCheckpointFn = Callable[..., None]
PromptPathFn = Callable[[str], Path]
BuildPhasePromptFn = Callable[..., str]
RunAgentFn = Callable[..., bool]
PhaseSummaryFn = Callable[[str, Path, Path], str]
StoreSummaryFn = Callable[[str, str, int, str], None]
EmitFn = Callable[..., None]
PrintFn = Callable[..., None]
SleepFn = Callable[[int], None]
TmpPathFn = Callable[..., Path]
CleanupFn = Callable[..., None]


@dataclass(frozen=True)
class PhaseExecutorPalette:
    blue: str
    white: str
    gray: str
    cyan: str
    green: str
    magenta: str
    red: str
    yellow: str
    reset: str


class PhaseExecutor:
    def __init__(
        self,
        *,
        prompt: str,
        prompt_path: PromptPathFn,
        control_checkpoint: ControlCheckpointFn,
        build_phase_prompt: BuildPhasePromptFn,
        run_agent: RunAgentFn,
        phase_summary: PhaseSummaryFn,
        store_phase_summary: StoreSummaryFn,
        emit: EmitFn,
        print_line: PrintFn,
        sleep: SleepFn,
        tmp_path: TmpPathFn,
        cleanup_paths: CleanupFn,
        palette: PhaseExecutorPalette,
    ) -> None:
        self.prompt = prompt
        self.prompt_path = prompt_path
        self.control_checkpoint = control_checkpoint
        self.build_phase_prompt = build_phase_prompt
        self.run_agent = run_agent
        self.phase_summary = phase_summary
        self.store_phase_summary = store_phase_summary
        self.emit = emit
        self.print_line = print_line
        self.sleep = sleep
        self.tmp_path = tmp_path
        self.cleanup_paths = cleanup_paths
        self.palette = palette

    def phase_presentation(self, phase: str) -> tuple[str, str]:
        if phase == "forward":
            return "▶ FORWARD", self.palette.green
        if phase == "research":
            return "◆ RESEARCH", self.palette.cyan
        if phase == "curation":
            return "◆ CURATION", self.palette.white
        if phase == "documentation":
            return "◆ DOCUMENTATION", self.palette.blue
        if phase == "architecture":
            return "◆ ARCHITECTURE", self.palette.yellow
        if phase == "backward":
            return "◀ BACKWARD", self.palette.magenta
        return phase.upper(), self.palette.white

    def planning_phase(self, session_id: str) -> None:
        self.control_checkpoint(session_id=session_id, phase="planning", iteration=None)
        phase_start = utc_now_iso()[11:19]
        self.print_line(
            f"\n{self.palette.cyan}◆ PLANNING{self.palette.reset} "
            f"{self.palette.gray}{phase_start}{self.palette.reset}"
        )
        self.print_line(
            f"{self.palette.gray}─────────────────────────────────────────────────────────"
            f"{self.palette.reset}\n"
        )
        self.emit(
            "phase.start",
            phase="planning",
            payload={
                "started": phase_start,
                "prompt": self.prompt,
                "prompt_path": str(self.prompt_path("planning")),
            },
        )

        planning_prompt = self.build_phase_prompt(session_id, "planning")
        out_path = self.tmp_path(prefix="planning_", suffix=".jsonl")
        last_path = self.tmp_path(prefix="planning_", suffix=".last.txt")

        ok = self.run_agent(
            "planning",
            planning_prompt,
            out_path,
            last_path,
            iteration=None,
        )

        if not ok:
            self.emit(
                "phase.error",
                phase="planning",
                payload={
                    "ok": False,
                    "output_path": str(out_path),
                    "last_message_path": str(last_path),
                },
            )
            self.print_line(f"{self.palette.red}✗ Planning failed{self.palette.reset}")
            raise SystemExit(1)

        summary = self.phase_summary("planning", out_path, last_path)
        self.emit(
            "phase.end",
            phase="planning",
            payload={
                "ok": True,
                "summary": summary,
                "output_path": str(out_path),
                "last_message_path": str(last_path),
            },
        )
        self.store_phase_summary(session_id, "planning", 0, summary)
        self.cleanup_paths(out_path, last_path)

    def run_operational_phase(
        self,
        *,
        session_id: str,
        phase: str,
        iteration: int,
        forward_report: dict[str, Any] | None = None,
        run_index: int | None = None,
        run_total: int | None = None,
    ) -> str:
        fail_count = 0
        label, color = self.phase_presentation(phase)
        run_suffix = ""
        if run_index is not None and run_total is not None:
            run_suffix = f" ({run_index}/{run_total})"

        while True:
            self.control_checkpoint(
                session_id=session_id,
                phase=phase,
                iteration=iteration,
            )
            phase_start = utc_now_iso()[11:19]
            self.print_line(
                f"\n{color}{label}{self.palette.reset}{run_suffix} "
                f"{self.palette.gray}{phase_start}{self.palette.reset}"
            )
            self.print_line(
                f"{self.palette.gray}─────────────────────────────────────────────────────────"
                f"{self.palette.reset}\n"
            )
            payload: dict[str, Any] = {
                "started": phase_start,
                "prompt": self.prompt,
                "prompt_path": str(self.prompt_path(phase)),
            }
            if run_index is not None and run_total is not None:
                payload["run_index"] = run_index
                payload["run_total"] = run_total
            self.emit(
                "phase.start",
                phase=phase,
                iteration=iteration,
                payload=payload,
            )

            phase_prompt = self.build_phase_prompt(
                session_id,
                phase,
                forward_report=forward_report,
            )
            out_path = self.tmp_path(prefix=f"{phase}_", suffix=".log")
            last_path = self.tmp_path(prefix=f"{phase}_", suffix=".last.txt")
            try:
                ok = self.run_agent(
                    phase,
                    phase_prompt,
                    out_path,
                    last_path,
                    iteration=iteration,
                )

                if ok:
                    summary = self.phase_summary(phase, out_path, last_path)
                    self.emit(
                        "phase.end",
                        phase=phase,
                        iteration=iteration,
                        payload={
                            "ok": True,
                            "summary": summary,
                            "output_path": str(out_path),
                            "last_message_path": str(last_path),
                        },
                    )
                    self.store_phase_summary(session_id, phase, iteration, summary)
                    return summary

                self.emit(
                    "phase.error",
                    phase=phase,
                    iteration=iteration,
                    payload={
                        "ok": False,
                        "output_path": str(out_path),
                        "last_message_path": str(last_path),
                        "fail_count": fail_count + 1,
                    },
                )
                fail_count += 1
                if fail_count >= 3:
                    self.print_line(
                        f"{self.palette.red}✗ Too many failures in {phase}, "
                        f"waiting 15 minutes...{self.palette.reset}"
                    )
                    self.sleep(900)
                    fail_count = 0
                else:
                    self.sleep(2)
            finally:
                self.cleanup_paths(out_path, last_path)
