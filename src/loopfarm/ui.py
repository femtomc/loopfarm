from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from typing import Literal, TextIO

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

OUTPUT_CHOICES = ("auto", "plain", "rich")
OutputMode = Literal["plain", "rich"]


def add_output_mode_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--output",
        choices=OUTPUT_CHOICES,
        help=(
            "Output mode: auto (default), plain, or rich."
        ),
    )


def _normalize_choice(raw: str | None, *, source: str) -> str | None:
    if raw is None:
        return None
    value = raw.strip().lower()
    if not value:
        return None
    if value not in OUTPUT_CHOICES:
        expected = ", ".join(OUTPUT_CHOICES)
        raise ValueError(f"invalid {source} value {raw!r}; expected one of: {expected}")
    return value


def _stream_is_tty(stream: object) -> bool:
    probe = getattr(stream, "isatty", None)
    if not callable(probe):
        return False
    try:
        return bool(probe())
    except Exception:
        return False


def resolve_output_mode(
    requested: str | None = None,
    *,
    is_tty: bool | None = None,
) -> OutputMode:
    selected = _normalize_choice(requested, source="--output")
    if selected is None:
        selected = "auto"

    if selected == "auto":
        tty = _stream_is_tty(sys.stdout) if is_tty is None else bool(is_tty)
        return "rich" if tty else "plain"
    return "rich" if selected == "rich" else "plain"


def make_console(mode: OutputMode, *, stderr: bool = False) -> Console:
    return Console(
        file=sys.stderr if stderr else sys.stdout,
        force_terminal=mode == "rich",
        no_color=mode != "rich",
        highlight=False,
    )


def render_table(
    console: Console,
    *,
    headers: Sequence[str],
    rows: Sequence[Sequence[object]],
    title: str | None = None,
    no_wrap_columns: Sequence[int] = (),
) -> None:
    table = Table(title=title)
    no_wrap = set(no_wrap_columns)
    for idx, header in enumerate(headers):
        table.add_column(str(header), no_wrap=idx in no_wrap)
    for row in rows:
        table.add_row(*(str(value or "") for value in row))
    console.print(table)


def render_panel(console: Console, body: str, *, title: str | None = None) -> None:
    console.print(Panel(body, title=title))


def render_markdown(console: Console, body: str) -> None:
    console.print(Markdown(body))


def render_plain_help(
    *,
    command: str,
    summary: str,
    usage: Sequence[str],
    sections: Sequence[tuple[str, Sequence[tuple[str, str]]]],
    examples: Sequence[tuple[str, str]] = (),
    docs_tip: str | None = None,
    stderr: bool = False,
) -> None:
    stream: TextIO = sys.stderr if stderr else sys.stdout

    print(f"{command}  {summary}", file=stream)
    print(file=stream)
    print("Usage", file=stream)
    for line in usage:
        print(f"  {line}", file=stream)

    for title, rows in sections:
        if not rows:
            continue
        print(file=stream)
        print(title, file=stream)
        width = max(len(str(item)) for item, _ in rows)
        for item, description in rows:
            left = str(item)
            right = str(description)
            if right:
                print(f"  {left.ljust(width)}  {right}", file=stream)
            else:
                print(f"  {left}", file=stream)

    if examples:
        print(file=stream)
        print("Examples", file=stream)
        width = max(len(str(item)) for item, _ in examples)
        for item, description in examples:
            left = str(item)
            right = str(description)
            if right:
                print(f"  {left.ljust(width)}  {right}", file=stream)
            else:
                print(f"  {left}", file=stream)

    if docs_tip:
        print(file=stream)
        print("Docs", file=stream)
        print(f"  {docs_tip}", file=stream)


def render_rich_help(
    *,
    command: str,
    summary: str,
    usage: Sequence[str],
    sections: Sequence[tuple[str, Sequence[tuple[str, str]]]],
    examples: Sequence[tuple[str, str]] = (),
    docs_tip: str | None = None,
    stderr: bool = False,
) -> None:
    console = make_console("rich", stderr=stderr)
    render_panel(console, summary, title=f"[bold blue]{command}[/bold blue]")
    console.print()
    console.print("[bold]Usage[/bold]")
    for line in usage:
        console.print(f"  {line}", markup=False)

    for title, rows in sections:
        if not rows:
            continue
        console.print()
        render_table(
            console,
            title=title,
            headers=("Item", "Description"),
            rows=rows,
            no_wrap_columns=(0,),
        )

    if examples:
        console.print()
        render_table(
            console,
            title="Examples",
            headers=("Command", "Purpose"),
            rows=examples,
            no_wrap_columns=(0,),
        )

    if docs_tip:
        console.print()
        render_panel(console, docs_tip, title="Docs")


def render_help(
    *,
    output_mode: OutputMode,
    command: str,
    summary: str,
    usage: Sequence[str],
    sections: Sequence[tuple[str, Sequence[tuple[str, str]]]],
    examples: Sequence[tuple[str, str]] = (),
    docs_tip: str | None = None,
    stderr: bool = False,
) -> None:
    if output_mode == "rich":
        render_rich_help(
            command=command,
            summary=summary,
            usage=usage,
            sections=sections,
            examples=examples,
            docs_tip=docs_tip,
            stderr=stderr,
        )
        return

    render_plain_help(
        command=command,
        summary=summary,
        usage=usage,
        sections=sections,
        examples=examples,
        docs_tip=docs_tip,
        stderr=stderr,
    )
