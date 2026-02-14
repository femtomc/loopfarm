"""Core DAG runner: select → execute → validate loop."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown
from rich.rule import Rule
from rich.text import Text

from .backend import get_backend
from .fmt import get_formatter
from .prompt import read_prompt_meta, render
from .forum_store import ForumStore
from .issue_store import IssueStore
from .spec import ExecutionSpec


@dataclass(frozen=True)
class DagResult:
    status: str  # "root_final", "no_executable_leaf", "max_steps_exhausted", "error"
    steps: int = 0
    error: str = ""


class DagRunner:
    # Hardcoded fallbacks if neither execution_spec nor orchestrator.md provide config
    _FALLBACK_CLI = "codex"
    _FALLBACK_MODEL = "gpt-5.3-codex"
    _FALLBACK_REASONING = "xhigh"

    def __init__(
        self,
        store: IssueStore,
        forum: ForumStore,
        repo_root: Path,
        *,
        console: Console | None = None,
    ) -> None:
        self.store = store
        self.forum = forum
        self.repo_root = repo_root
        self.console = console or Console()

    _REORCHESTRATE_OUTCOMES = {"failure", "needs_work"}

    def _rich_output(self) -> bool:
        return bool(self.console.is_terminal and not self.console.is_dumb_terminal)

    def _phase_header(self, title: str, *, subtitle: str = "", style: str = "cyan") -> None:
        if self._rich_output():
            self.console.print(Rule(f"[bold {style}]{title}[/bold {style}]"))
            if subtitle:
                self.console.print(Text(subtitle, style="dim"))
            return

        self.console.print()
        self.console.print(f"{title}")
        if subtitle:
            self.console.print(f"  {subtitle}")

    # ------------------------------------------------------------------
    # Routing helpers
    # ------------------------------------------------------------------

    def _resolve_config(
        self, issue: dict
    ) -> tuple[str, str, str, str | None]:
        """3-tier resolution: orchestrator.md → role frontmatter → execution_spec.

        Returns (cli, model, reasoning, prompt_path).
        """
        cli = self._FALLBACK_CLI
        model = self._FALLBACK_MODEL
        reasoning = self._FALLBACK_REASONING
        prompt_path: str | None = None

        # Tier 1: orchestrator.md frontmatter (global defaults)
        orchestrator = self.repo_root / ".inshallah" / "orchestrator.md"
        if orchestrator.exists():
            meta = read_prompt_meta(orchestrator)
            cli = meta.get("cli", cli)
            model = meta.get("model", model)
            reasoning = meta.get("reasoning", reasoning)
            prompt_path = str(orchestrator)

        # Parse execution_spec (may set role + explicit fields)
        spec: ExecutionSpec | None = None
        if issue.get("execution_spec"):
            spec = ExecutionSpec.from_dict(
                issue["execution_spec"], self.repo_root
            )

        # Tier 2: role file frontmatter (role-specific defaults)
        if spec and spec.role:
            role_path = self.repo_root / ".inshallah" / "roles" / f"{spec.role}.md"
            if role_path.exists():
                role_meta = read_prompt_meta(role_path)
                cli = role_meta.get("cli", cli)
                model = role_meta.get("model", model)
                reasoning = role_meta.get("reasoning", reasoning)

        # Tier 3: execution_spec explicit fields (highest priority)
        if spec:
            if spec.cli is not None:
                cli = spec.cli
            if spec.model is not None:
                model = spec.model
            if spec.reasoning is not None:
                reasoning = spec.reasoning
            if spec.prompt_path:
                prompt_path = spec.prompt_path

        return cli, model, reasoning, prompt_path

    def _render_prompt(
        self, issue: dict, prompt_path: str | None, root_id: str
    ) -> str:
        """Render prompt template + inject DAG context."""
        if prompt_path and Path(prompt_path).exists():
            rendered = render(prompt_path, issue, repo_root=self.repo_root)
        else:
            rendered = issue["title"]
            if issue.get("body"):
                rendered += "\n\n" + issue["body"]

        rendered += (
            f"\n\n## Inshallah Context\n"
            f"Root: {root_id}\n"
            f"Assigned issue: {issue['id']}\n"
        )
        return rendered

    def _execute_backend(
        self,
        issue: dict,
        cli: str,
        model: str,
        reasoning: str,
        prompt_path: str | None,
        root_id: str,
        *,
        log_suffix: str = "",
    ) -> tuple[int, float]:
        """Run a backend against the issue. Returns (exit_code, elapsed_seconds)."""
        rendered = self._render_prompt(issue, prompt_path, root_id)

        prompt_preview = rendered.split("## Inshallah Context", 1)[0].strip()

        self.console.print(
            f"  [dim]{cli} {model} reasoning={reasoning}[/dim]"
        )
        if self.console.is_terminal and not self.console.is_dumb_terminal:
            self.console.print(Text("  prompt", style="bold cyan"))
            self.console.print(Markdown(prompt_preview))
        else:
            self.console.print(f"  prompt: {prompt_preview}", markup=False)
        backend = get_backend(cli)
        formatter = get_formatter(cli, self.console)

        tee_dir = self.repo_root / ".inshallah" / "logs"
        tee_dir.mkdir(parents=True, exist_ok=True)
        suffix = f".{log_suffix}" if log_suffix else ""
        tee_path = tee_dir / f"{issue['id']}{suffix}.jsonl"

        t0 = time.time()
        exit_code = backend.run(
            rendered,
            model,
            reasoning,
            self.repo_root,
            on_line=formatter.process_line,
            tee_path=tee_path,
        )
        formatter.finish()
        elapsed = time.time() - t0

        self.console.print(
            f"  [dim]exit={exit_code} {elapsed:.1f}s[/dim]"
        )
        return exit_code, elapsed

    # ------------------------------------------------------------------
    # Review helpers
    # ------------------------------------------------------------------

    def _has_reviewer(self) -> bool:
        return (self.repo_root / ".inshallah" / "roles" / "reviewer.md").exists()

    def _maybe_review(
        self, issue: dict, root_id: str, step: int
    ) -> dict:
        """Run reviewer if conditions are met. Returns the (possibly updated) issue."""
        issue_id = issue["id"]

        # Guards
        if issue.get("outcome") != "success":
            return issue
        if not self._has_reviewer():
            return issue

        self._phase_header(
            "Review",
            subtitle=f"{issue_id} {issue['title']}",
            style="magenta",
        )

        # Build a synthetic issue dict routed to the reviewer role
        review_issue = dict(issue)
        review_issue["execution_spec"] = {"role": "reviewer"}

        cli, model, reasoning, prompt_path = self._resolve_config(review_issue)
        exit_code, elapsed = self._execute_backend(
            review_issue,
            cli,
            model,
            reasoning,
            prompt_path,
            root_id,
            log_suffix="review",
        )

        # Log review to forum
        self.forum.post(
            f"issue:{issue_id}",
            json.dumps(
                {
                    "step": step,
                    "issue_id": issue_id,
                    "title": issue["title"],
                    "exit_code": exit_code,
                    "elapsed_s": round(elapsed, 1),
                    "type": "review",
                }
            ),
            author="reviewer",
        )

        # Re-read in case reviewer changed outcome / created children
        return self.store.get(issue_id) or issue

    def _reopen_for_orchestration(
        self, issue_id: str, *, reason: str, step: int
    ) -> None:
        """Reopen an issue and clear execution routing so orchestrator.md runs next."""
        reopened = self.store.update(
            issue_id, status="open", outcome=None, execution_spec=None
        )

        # Log to forum so the orchestrator can pick up failure / review context.
        self.forum.post(
            f"issue:{issue_id}",
            json.dumps(
                {
                    "step": step,
                    "issue_id": issue_id,
                    "title": reopened.get("title", ""),
                    "type": "reorchestrate",
                    "reason": reason,
                }
            ),
            author="orchestrator",
        )

    def _maybe_unstick(self, root_id: str, step: int) -> bool:
        """If the DAG has closed nodes requiring re-orchestration, reopen one."""
        ids_in_scope = set(self.store.subtree_ids(root_id))
        rows = self.store.list()

        # Build children mapping once (avoid N calls to children()).
        children_of: dict[str, list[dict]] = {}
        for row in rows:
            for dep in row.get("deps", []):
                if dep.get("type") == "parent":
                    children_of.setdefault(dep.get("target", ""), []).append(row)

        def _has_open_children(issue_id: str) -> bool:
            return any(
                child.get("status") != "closed"
                for child in children_of.get(issue_id, [])
            )

        candidates: list[dict] = []
        for row in rows:
            issue_id = row.get("id")
            if not issue_id or issue_id not in ids_in_scope:
                continue
            if row.get("status") != "closed":
                continue

            outcome = row.get("outcome")
            if outcome in self._REORCHESTRATE_OUTCOMES:
                # Only reopen when it would become a leaf (otherwise, there's
                # already open descendant work to execute).
                if _has_open_children(issue_id):
                    continue
                candidates.append(row)
                continue

            # "expanded" without children is a broken state: there is no leaf
            # work remaining, so the only way forward is re-orchestration.
            if outcome == "expanded" and not children_of.get(issue_id):
                candidates.append(row)

        if not candidates:
            return False

        candidates.sort(key=lambda r: r.get("priority", 3))
        target = candidates[0]
        target_id = target["id"]
        target_outcome = target.get("outcome")
        self.console.print(
            f"[yellow]Reopening {target_id} for orchestration "
            f"(was outcome={target_outcome}).[/yellow]"
        )
        self._reopen_for_orchestration(
            target_id, reason=f"was outcome={target_outcome}", step=step
        )
        return True

    # ------------------------------------------------------------------
    # Collapse review helpers
    # ------------------------------------------------------------------

    def _collapse_review(
        self, issue: dict, root_id: str, step: int
    ) -> None:
        """Run a collapse review on an expanded node whose children are all done."""
        issue_id = issue["id"]

        self._phase_header(
            "Collapse Review",
            subtitle=f"{issue_id} {issue['title']}",
            style="magenta",
        )

        # Build children summary
        kids = self.store.children(issue_id)
        lines = []
        for kid in kids:
            lines.append(
                f"- [{kid.get('outcome', '?')}] {kid['id']}: {kid['title']}"
            )
        children_summary = "\n".join(lines)

        # Build prompt body: original spec + children summary + instructions
        original_body = issue.get("body") or ""
        collapse_prompt = (
            f"# Collapse Review\n\n"
            f"## Original Specification\n\n"
            f"**{issue['title']}**\n\n"
            f"{original_body}\n\n"
            f"## Children Outcomes\n\n"
            f"{children_summary}\n\n"
            f"## Instructions\n\n"
            f"All children of this issue have completed. Review whether their "
            f"aggregate work satisfies the original specification above.\n\n"
            f"If satisfied: no action needed (the issue will be marked successful).\n\n"
            f"If NOT satisfied: mark the parent as needing work by running:\n\n"
            f"  `inshallah issues update {issue_id} --outcome needs_work`\n\n"
            f"Then explain the gaps in the forum topic (issue:{issue_id}).\n\n"
            f"Do NOT create child issues yourself; the orchestrator will "
            f"re-expand the issue into remediation children.\n"
        )

        # Route through reviewer role (cli/model/reasoning from reviewer.md)
        review_issue = {
            **issue,
            "title": f"Collapse review: {issue['title']}",
            "body": collapse_prompt,
            "execution_spec": {"role": "reviewer"},
        }

        cli, model, reasoning, _ = self._resolve_config(review_issue)
        exit_code, elapsed = self._execute_backend(
            review_issue,
            cli,
            model,
            reasoning,
            None,  # no prompt template — body is the full prompt
            root_id,
            log_suffix="collapse-review",
        )

        # Log to forum
        self.forum.post(
            f"issue:{issue_id}",
            json.dumps(
                {
                    "step": step,
                    "issue_id": issue_id,
                    "title": issue["title"],
                    "exit_code": exit_code,
                    "elapsed_s": round(elapsed, 1),
                    "type": "collapse-review",
                }
            ),
            author="reviewer",
        )

        # Check: did the reviewer create new children?
        new_kids = self.store.children(issue_id)
        open_kids = [k for k in new_kids if k["status"] != "closed"]
        updated = self.store.get(issue_id) or issue

        # Contract: reviewer marks needs_work; orchestrator expands. We still
        # tolerate legacy behavior (reviewer directly creates remediation
        # children).
        if updated.get("status") != "closed":
            self.console.print(
                f"  [yellow]Collapse review left issue open — {issue_id} "
                f"will be handled by the main loop[/yellow]"
            )
            return
        if updated.get("outcome") in self._REORCHESTRATE_OUTCOMES:
            self.console.print(
                f"  [yellow]Collapse review marked needs_work — {issue_id} "
                f"will be re-orchestrated[/yellow]"
            )
            return

        if open_kids:
            self.console.print(
                f"  [yellow]Collapse review created {len(open_kids)} "
                f"remediation issue(s) — loop continues[/yellow]"
            )
            return

        # All satisfied — promote to success
        self.store.update(issue_id, outcome="success")
        self.console.print(
            f"  [green]Collapse review passed — {issue_id} → success[/green]"
        )

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(
        self, root_id: str, max_steps: int = 20, *, review: bool = True
    ) -> DagResult:
        for step in range(max_steps):
            # 0. Unstick: failures / needs_work trigger re-orchestration.
            self._maybe_unstick(root_id, step + 1)

            # 1. Collapse review (before termination check)
            if review and self._has_reviewer():
                collapsible = self.store.collapsible(root_id)
                if collapsible:
                    self._collapse_review(collapsible[0], root_id, step + 1)
                    continue

            # 2. Check termination
            v = self.store.validate(root_id)
            if v.is_final:
                self.console.print(
                    f"[green]DAG complete:[/green] {v.reason} ({step} steps)"
                )
                return DagResult("root_final", steps=step)

            # 3. Select next ready leaf
            candidates = self.store.ready(root_id, tags=["node:agent"])
            if not candidates:
                # If validation says "in progress" but we have no executable
                # leaves, try an orchestrator repair pass on the root to
                # resolve deadlocks / bad expansions.
                self._phase_header(
                    "Unstick",
                    subtitle="No executable leaves; invoking orchestrator to repair DAG.",
                    style="yellow",
                )
                root_issue = self.store.get(root_id)
                if root_issue is None:
                    return DagResult(
                        "error", steps=step, error="root vanished"
                    )

                ids_in_scope = set(self.store.subtree_ids(root_id))
                open_issues = [
                    r
                    for r in self.store.list(status="open")
                    if r.get("id") in ids_in_scope
                ]
                diag_lines = [
                    f"- open_issues: {len(open_issues)}",
                    "- action: diagnose deadlocks or missing expansions and create executable leaf work",
                    f"- hint: run `inshallah issues ready --root {root_id}` and `inshallah issues list --root {root_id}`",
                ]
                diag = "\n".join(diag_lines)

                repair_issue = dict(root_issue)
                repair_issue["title"] = f"Repair stuck DAG: {root_issue['title']}"
                repair_issue["body"] = (
                    (root_issue.get("body") or "")
                    + "\n\n## Runner Diagnostics\n\n"
                    + diag
                ).strip()
                repair_issue["execution_spec"] = None  # force orchestrator.md

                cli, model, reasoning, prompt_path = self._resolve_config(
                    repair_issue
                )
                exit_code, elapsed = self._execute_backend(
                    repair_issue,
                    cli,
                    model,
                    reasoning,
                    prompt_path,
                    root_id,
                    log_suffix="unstick",
                )

                self.forum.post(
                    f"issue:{root_id}",
                    json.dumps(
                        {
                            "step": step + 1,
                            "issue_id": root_id,
                            "title": root_issue.get("title", ""),
                            "exit_code": exit_code,
                            "elapsed_s": round(elapsed, 1),
                            "type": "unstick",
                        }
                    ),
                    author="orchestrator",
                )
                continue

            issue = candidates[0]
            issue_id = issue["id"]
            self._phase_header(
                f"Step {step + 1}",
                subtitle=f"{issue_id} {issue['title']}",
                style="cyan",
            )

            # 3. Claim
            self.store.claim(issue_id)

            # 4. Route + 5. Render + 6. Execute
            cli, model, reasoning, prompt_path = self._resolve_config(issue)
            exit_code, elapsed = self._execute_backend(
                issue, cli, model, reasoning, prompt_path, root_id
            )

            # 7. Check postconditions
            updated = self.store.get(issue_id)
            if updated is None:
                return DagResult("error", steps=step + 1, error="issue vanished")

            if updated["status"] != "closed":
                self.console.print(
                    f"  [yellow]Issue not closed after execution "
                    f"(status={updated['status']})[/yellow]"
                )
                # Agent didn't close the issue — treat as failure and
                # re-orchestrate so we don't get stuck with in_progress work.
                updated = self.store.close(issue_id, outcome="failure")
                self.console.print("  [red]Marked as failure[/red]")

            # 7b. Review phase
            if review and updated["status"] == "closed":
                updated = self._maybe_review(
                    updated, root_id, step + 1
                )

            # 8. Log to forum
            self.forum.post(
                f"issue:{issue_id}",
                json.dumps(
                    {
                        "step": step + 1,
                        "issue_id": issue_id,
                        "title": issue["title"],
                        "exit_code": exit_code,
                        "outcome": updated.get("outcome"),
                        "elapsed_s": round(elapsed, 1),
                    }
                ),
                author="orchestrator",
            )

            # 9. Re-orchestrate on failure / needs_work
            if updated.get("outcome") in self._REORCHESTRATE_OUTCOMES:
                self.console.print(
                    f"  [yellow]Outcome={updated.get('outcome')} — "
                    f"re-invoking orchestrator on {issue_id}[/yellow]"
                )
                self._reopen_for_orchestration(
                    issue_id,
                    reason=f"outcome={updated.get('outcome')}",
                    step=step + 1,
                )

        self.console.print(
            f"[yellow]Max steps exhausted ({max_steps})[/yellow]"
        )
        return DagResult("max_steps_exhausted", steps=max_steps)
