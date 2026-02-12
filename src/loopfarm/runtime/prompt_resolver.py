from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Protocol

from ..prompting import assemble_prompt, render_prompt
from ..stores.session import SessionStore
from ..templates import TemplateContext


class PromptConfig(Protocol):
    repo_root: Path
    prompt: str
    project: str
    phase_prompt_overrides: tuple[tuple[str, str], ...]
    phase_injections: tuple[tuple[str, tuple[str, ...]], ...]


ReadForwardReportFn = Callable[[str], dict[str, Any] | None]
FormatForwardReportFn = Callable[[dict[str, Any] | None], str]


class PromptResolver:
    def __init__(self, cfg: PromptConfig, session_store: SessionStore) -> None:
        self.cfg = cfg
        self.session_store = session_store
        self.phase_prompt_overrides = {
            phase: path for phase, path in cfg.phase_prompt_overrides if phase and path
        }
        self.phase_injections = {
            phase: tuple(injections)
            for phase, injections in cfg.phase_injections
            if phase
        }

    def prompt_path(self, phase: str) -> Path:
        override = self.phase_prompt_overrides.get(phase)
        if override:
            path = Path(override)
            if not path.is_absolute():
                path = self.cfg.repo_root / path
            return path
        return self.cfg.repo_root / ".loopfarm" / "prompts" / f"{phase}.md"

    def render_phase_prompt(self, session_id: str, phase: str) -> str:
        ctx = TemplateContext(
            prompt=self.cfg.prompt,
            session=session_id,
            project=self.cfg.project,
        )
        return render_prompt(self.prompt_path(phase), ctx)

    def build_phase_briefing(self, session_id: str) -> str:
        summaries = self.session_store.get_phase_summaries(session_id, limit=6)
        if not summaries:
            return ""

        lines = [
            "## Phase Briefing",
            "",
            "Recent activity in this session. Use this to maintain continuity with prior",
            "phases — especially backward review commentary and previous forward observations.",
        ]
        for summary in summaries:
            phase = str(summary.get("phase") or "unknown")
            iteration = summary.get("iteration")
            text = str(summary.get("summary") or "").strip()
            if not text:
                continue
            label = phase.capitalize()
            if iteration is not None:
                label = f"{label} #{iteration}"
            lines.append("")
            lines.append(f"### {label}")
            lines.append(text)
        return "\n".join(lines)

    def inject_phase_briefing(self, base: str, session_id: str) -> str:
        briefing = self.build_phase_briefing(session_id)
        if not briefing:
            return base
        placeholder = "{{PHASE_BRIEFING}}"
        if placeholder in base:
            return base.replace(placeholder, briefing, 1)
        for anchor in ("## Workflow", "## Guidelines"):
            idx = base.find(anchor)
            if idx != -1:
                before = base[:idx].rstrip()
                after = base[idx:].lstrip()
                return f"{before}\n\n{briefing}\n\n{after}"
        return base.rstrip() + "\n\n" + briefing

    def inject_forward_report(
        self,
        base: str,
        *,
        session_id: str,
        payload: dict[str, Any] | None,
        read_forward_report: ReadForwardReportFn,
        format_forward_report: FormatForwardReportFn,
    ) -> str:
        if payload is None:
            payload = read_forward_report(session_id)
        report = format_forward_report(payload)
        if not report:
            report = "_No forward report available._"
        placeholder = "{{FORWARD_REPORT}}"
        if placeholder in base:
            return base.replace(placeholder, report, 1)

        section = "---\n\n## Forward Pass Report\n\n" + report
        for anchor in ("## Workflow", "## Required Phase Summary"):
            idx = base.find(anchor)
            if idx != -1:
                before = base[:idx].rstrip()
                after = base[idx:].lstrip()
                return f"{before}\n\n{section}\n\n{after}"
        return base.rstrip() + "\n\n" + section

    def build_phase_prompt(
        self,
        *,
        session_id: str,
        phase: str,
        session_context: str,
        prompt_suffix: str,
        forward_report: dict[str, Any] | None,
        read_forward_report: ReadForwardReportFn,
        format_forward_report: FormatForwardReportFn,
    ) -> str:
        base = self.render_phase_prompt(session_id, phase)

        for injection in self.phase_injections.get(phase, ()):  # explicit-only
            if injection == "phase_briefing":
                base = self.inject_phase_briefing(base, session_id)
            elif injection == "forward_report":
                base = self.inject_forward_report(
                    base,
                    session_id=session_id,
                    payload=forward_report,
                    read_forward_report=read_forward_report,
                    format_forward_report=format_forward_report,
                )

        return assemble_prompt(
            base,
            session_context=session_context,
            user_context="",
            prompt_suffix=prompt_suffix,
        )
