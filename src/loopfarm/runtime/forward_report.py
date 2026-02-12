from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..forum import Forum
from ..util import CommandError, env_int, run_capture, utc_now_iso


def _truncate_lines(lines: list[str], max_lines: int) -> list[str]:
    if max_lines <= 0:
        return []
    if len(lines) <= max_lines:
        return lines
    extra = len(lines) - max_lines
    return lines[:max_lines] + [f"... ({extra} more lines)"]


def _truncate_text(text: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    suffix = " ... (truncated)"
    limit = max_chars - len(suffix)
    if limit <= 0:
        return suffix.strip()
    return text[:limit].rstrip() + suffix


class ForwardReportService:
    def __init__(self, *, repo_root: Path, forum: Forum) -> None:
        self.repo_root = repo_root
        self.forum = forum

    def git_capture(self, argv: list[str]) -> str:
        try:
            return run_capture(argv, cwd=self.repo_root).strip()
        except CommandError:
            return ""

    def git_lines(self, argv: list[str]) -> list[str]:
        out = self.git_capture(argv)
        if not out:
            return []
        return [line.rstrip() for line in out.splitlines() if line.strip()]

    def git_head(self) -> str:
        return self.git_capture(["git", "rev-parse", "HEAD"])

    def build_forward_report(
        self, *, session_id: str, pre_head: str, post_head: str, summary: str
    ) -> dict[str, Any]:
        max_lines = env_int("LOOPFARM_FORWARD_REPORT_MAX_LINES", 20)
        max_commits = env_int("LOOPFARM_FORWARD_REPORT_MAX_COMMITS", 12)
        max_summary_chars = env_int("LOOPFARM_FORWARD_REPORT_MAX_SUMMARY_CHARS", 800)

        head_changed = bool(pre_head and post_head and pre_head != post_head)
        commit_range = f"{pre_head}..{post_head}" if head_changed else ""

        commits = (
            self.git_lines(
                [
                    "git",
                    "--no-pager",
                    "log",
                    "--oneline",
                    f"--max-count={max_commits}",
                    commit_range,
                ]
            )
            if commit_range
            else []
        )
        diffstat = (
            self.git_lines(
                [
                    "git",
                    "--no-pager",
                    "diff",
                    "--stat",
                    "--submodule=short",
                    commit_range,
                ]
            )
            if commit_range
            else []
        )
        name_status = (
            self.git_lines(
                [
                    "git",
                    "--no-pager",
                    "diff",
                    "--name-status",
                    "--submodule=short",
                    commit_range,
                ]
            )
            if commit_range
            else []
        )

        status_lines = self.git_lines(["git", "status", "--porcelain=v1"])
        dirty = bool(status_lines)

        staged_diffstat = self.git_lines(
            ["git", "--no-pager", "diff", "--stat", "--cached", "--submodule=short"]
        )
        unstaged_diffstat = self.git_lines(
            ["git", "--no-pager", "diff", "--stat", "--submodule=short"]
        )
        staged_name_status = self.git_lines(
            [
                "git",
                "--no-pager",
                "diff",
                "--name-status",
                "--cached",
                "--submodule=short",
            ]
        )
        unstaged_name_status = self.git_lines(
            ["git", "--no-pager", "diff", "--name-status", "--submodule=short"]
        )

        return {
            "timestamp": utc_now_iso(),
            "session": session_id,
            "pre_head": pre_head,
            "post_head": post_head,
            "head_changed": head_changed,
            "commit_range": commit_range,
            "commits": _truncate_lines(commits, max_commits),
            "diffstat": _truncate_lines(diffstat, max_lines),
            "name_status": _truncate_lines(name_status, max_lines),
            "dirty": dirty,
            "status": _truncate_lines(status_lines, max_lines),
            "staged_diffstat": _truncate_lines(staged_diffstat, max_lines),
            "unstaged_diffstat": _truncate_lines(unstaged_diffstat, max_lines),
            "staged_name_status": _truncate_lines(staged_name_status, max_lines),
            "unstaged_name_status": _truncate_lines(unstaged_name_status, max_lines),
            "summary": _truncate_text(summary, max_summary_chars),
        }

    def post_forward_report(self, session_id: str, payload: dict[str, Any]) -> None:
        self.forum.post_json(f"loopfarm:forward:{session_id}", payload)

    def read_forward_report(self, session_id: str) -> dict[str, Any] | None:
        msgs = self.forum.read_json(f"loopfarm:forward:{session_id}", limit=1)
        if not msgs:
            msgs = self.forum.read_json(f"loopfarm:forward:{session_id}", limit=1)
        if not msgs:
            return None
        body = msgs[0].get("body") or ""
        if not body:
            return None
        try:
            payload = json.loads(body)
        except Exception:
            return None
        if isinstance(payload, dict):
            return payload
        return None

    def format_for_prompt(self, payload: dict[str, Any] | None) -> str:
        if not payload:
            return ""

        def as_lines(key: str) -> list[str]:
            val = payload.get(key) or []
            if isinstance(val, list):
                return [str(x) for x in val if str(x).strip()]
            if isinstance(val, str):
                return [line for line in val.splitlines() if line.strip()]
            return []

        lines: list[str] = []
        summary = str(payload.get("summary") or "").strip()
        if summary:
            lines.append("Summary:")
            lines.append(summary)

        pre_head = str(payload.get("pre_head") or "").strip() or "unknown"
        post_head = str(payload.get("post_head") or "").strip() or "unknown"
        commit_range = str(payload.get("commit_range") or "").strip()

        lines.append(f"HEAD: {pre_head} -> {post_head}")
        if commit_range:
            lines.append(f"Commit range: {commit_range}")
        else:
            lines.append("Commit range: (none)")

        commits = as_lines("commits")
        if commits:
            lines.append("Commits:")
            lines.append("```")
            lines.extend(commits)
            lines.append("```")

        diffstat = as_lines("diffstat")
        if diffstat:
            lines.append("Diffstat (commits):")
            lines.append("```")
            lines.extend(diffstat)
            lines.append("```")

        name_status = as_lines("name_status")
        if name_status:
            lines.append("Name-status (commits):")
            lines.append("```")
            lines.extend(name_status)
            lines.append("```")

        dirty = bool(payload.get("dirty"))
        if dirty:
            lines.append("Working tree: dirty")
            status_lines = as_lines("status")
            if status_lines:
                lines.append("Status:")
                lines.append("```")
                lines.extend(status_lines)
                lines.append("```")

            staged_diffstat = as_lines("staged_diffstat")
            if staged_diffstat:
                lines.append("Diffstat (staged):")
                lines.append("```")
                lines.extend(staged_diffstat)
                lines.append("```")

            unstaged_diffstat = as_lines("unstaged_diffstat")
            if unstaged_diffstat:
                lines.append("Diffstat (unstaged):")
                lines.append("```")
                lines.extend(unstaged_diffstat)
                lines.append("```")

            staged_name_status = as_lines("staged_name_status")
            if staged_name_status:
                lines.append("Name-status (staged):")
                lines.append("```")
                lines.extend(staged_name_status)
                lines.append("```")

            unstaged_name_status = as_lines("unstaged_name_status")
            if unstaged_name_status:
                lines.append("Name-status (unstaged):")
                lines.append("```")
                lines.extend(unstaged_name_status)
                lines.append("```")
        else:
            lines.append("Working tree: clean")

        lines.append("Suggested commands:")
        lines.append("```bash")
        if commit_range:
            lines.append(f"git log --oneline {commit_range}")
            lines.append(f"git diff --stat {commit_range}")
            lines.append(f"git diff --name-status {commit_range}")
        lines.append("git status --porcelain=v1")
        if dirty:
            lines.append("git diff --stat")
            lines.append("git diff --stat --cached")
            lines.append("git diff --name-status")
            lines.append("git diff --name-status --cached")
        lines.append("```")

        return "\n".join(lines).strip()

    def inject_into_prompt(
        self,
        base: str,
        *,
        session_id: str,
        payload: dict[str, Any] | None,
    ) -> str:
        if payload is None:
            payload = self.read_forward_report(session_id)
        report = self.format_for_prompt(payload)
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
