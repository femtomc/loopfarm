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

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(
        self, root_id: str, max_steps: int = 20, *, review: bool = True
    ) -> DagResult:
        for step in range(max_steps):
            # 1. Check termination
            v = self.store.validate(root_id)
            if v.is_final:
                self.console.print(
                    f"[green]DAG complete:[/green] {v.reason} ({step} steps)"
                )
                return DagResult("root_final", steps=step)

            # 2. Select next ready leaf
            candidates = self.store.ready(root_id, tags=["node:agent"])
            if not candidates:
                self.console.print(
                    "[yellow]No executable leaf found.[/yellow]"
                )
                return DagResult("no_executable_leaf", steps=step)

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
                # Agent didn't close the issue — mark failure
                if exit_code != 0:
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

        self.console.print(
            f"[yellow]Max steps exhausted ({max_steps})[/yellow]"
        )
        return DagResult("max_steps_exhausted", steps=max_steps)
