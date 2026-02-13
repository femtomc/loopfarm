"""Core DAG runner: select → execute → validate loop."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console

from .backend import get_backend
from .fmt import get_formatter
from .prompt import read_prompt_meta, render
from .spec import ExecutionSpec
from .store import ForumStore, IssueStore


@dataclass(frozen=True)
class DagResult:
    status: str  # "root_final", "no_executable_leaf", "max_steps_exhausted", "error"
    steps: int = 0
    error: str = ""


class DagRunner:
    # Hardcoded fallbacks if neither execution_spec nor orchestrator.md provide config
    _FALLBACK_CLI = "claude"
    _FALLBACK_MODEL = "opus"
    _FALLBACK_REASONING = "high"

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

    def run(self, root_id: str, max_steps: int = 20) -> DagResult:
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
            self.console.print(
                f"\n[bold]Step {step + 1}:[/bold] {issue['title']} "
                f"[dim]({issue_id})[/dim]"
            )

            # 3. Claim
            self.store.claim(issue_id)

            # 4. Route: determine backend, model, prompt
            # 3-tier priority: execution_spec fields > role frontmatter > orchestrator.md > fallbacks
            cli = self._FALLBACK_CLI
            model = self._FALLBACK_MODEL
            reasoning = self._FALLBACK_REASONING
            prompt_path: str | None = None

            # Tier 1: orchestrator.md frontmatter (global defaults)
            orchestrator = self.repo_root / ".loopfarm" / "orchestrator.md"
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
                role_path = self.repo_root / ".loopfarm" / "roles" / f"{spec.role}.md"
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

            # 5. Render prompt
            if prompt_path and Path(prompt_path).exists():
                rendered = render(prompt_path, issue, repo_root=self.repo_root)
            else:
                # No prompt template — use issue title+body directly
                rendered = issue["title"]
                if issue.get("body"):
                    rendered += "\n\n" + issue["body"]

            # 6. Run backend
            self.console.print(
                f"  [dim]{cli} model={model} reasoning={reasoning}[/dim]"
            )
            backend = get_backend(cli)
            formatter = get_formatter(cli, self.console)

            tee_dir = self.repo_root / ".loopfarm" / "logs"
            tee_dir.mkdir(parents=True, exist_ok=True)
            tee_path = tee_dir / f"{issue_id}.jsonl"

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
