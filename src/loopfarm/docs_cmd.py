from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from .ui import (
    add_output_mode_argument,
    make_console,
    render_markdown,
    render_panel,
    render_table,
    resolve_output_mode,
)


@dataclass(frozen=True)
class DocTopicSpec:
    topic: str
    file_name: str
    description: str


@dataclass(frozen=True)
class DocTopic:
    topic: str
    title: str
    description: str
    markdown: str
    file_name: str


@dataclass(frozen=True)
class DocSearchResult:
    topic: str
    title: str
    file_name: str
    score: int
    snippet: str


_TOPIC_SPECS = (
    DocTopicSpec(
        topic="steps-grammar",
        file_name="phase-plan.md",
        description="Grammar, rules, and examples for [program].steps.",
    ),
    DocTopicSpec(
        topic="implementation-state-machine",
        file_name="implementation-state-machine.md",
        description="Execution shape, termination gate, and forward report flow.",
    ),
    DocTopicSpec(
        topic="source-layout",
        file_name="source-layout.md",
        description="Module map for CLI, runtime internals, and persistence stores.",
    ),
)

_TOPIC_ALIASES = {
    "steps": "steps-grammar",
    "grammar": "steps-grammar",
    "state-machine": "implementation-state-machine",
    "implementation": "implementation-state-machine",
    "layout": "source-layout",
}


def _docs_root() -> Path:
    return Path(__file__).resolve().parents[2] / "docs"


def _extract_title(markdown: str, *, fallback: str) -> str:
    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if line.startswith("# "):
            return line[2:].strip()
    return fallback


def _load_topics() -> list[DocTopic]:
    docs_root = _docs_root()
    topics: list[DocTopic] = []
    for spec in _TOPIC_SPECS:
        path = docs_root / spec.file_name
        try:
            markdown = path.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"error: failed to read docs topic {spec.topic!r}: {exc}", file=sys.stderr)
            raise SystemExit(2) from exc

        fallback_title = spec.topic.replace("-", " ").title()
        topics.append(
            DocTopic(
                topic=spec.topic,
                title=_extract_title(markdown, fallback=fallback_title),
                description=spec.description,
                markdown=markdown.rstrip(),
                file_name=spec.file_name,
            )
        )
    return topics


def _resolve_topic(topics: list[DocTopic], requested: str) -> DocTopic:
    lookup = {topic.topic: topic for topic in topics}
    normalized = requested.strip().lower()
    canonical = _TOPIC_ALIASES.get(normalized, normalized)
    selected = lookup.get(canonical)
    if selected is None:
        available = ", ".join(sorted(lookup))
        print(
            f"error: unknown docs topic {requested!r} (available: {available})",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return selected


def _truncate(text: str, *, limit: int = 120) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(0, limit - 3)] + "..."


def _query_tokens(query: str) -> list[str]:
    tokens = [token for token in query.strip().lower().split() if token]
    if not tokens:
        print("error: docs search query cannot be empty", file=sys.stderr)
        raise SystemExit(2)
    return tokens


def _line_score(line_lower: str, *, tokens: list[str], query_lower: str) -> int:
    if query_lower and query_lower in line_lower:
        return 100
    score = 0
    for token in tokens:
        if token in line_lower:
            score += 10
    return score


def _extract_best_snippet(topic: DocTopic, *, tokens: list[str], query_lower: str) -> str:
    ranked_lines: list[tuple[int, str]] = []

    title_line = topic.title.strip()
    title_score = _line_score(title_line.lower(), tokens=tokens, query_lower=query_lower)
    if title_score > 0:
        ranked_lines.append((title_score + 40, title_line))

    description_line = topic.description.strip()
    description_score = _line_score(
        description_line.lower(), tokens=tokens, query_lower=query_lower
    )
    if description_score > 0:
        ranked_lines.append((description_score + 25, description_line))

    for raw_line in topic.markdown.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        line_score = _line_score(stripped.lower(), tokens=tokens, query_lower=query_lower)
        if line_score > 0:
            ranked_lines.append((line_score, stripped))

    if not ranked_lines:
        return ""

    ranked_lines.sort(key=lambda item: (-item[0], item[1]))
    return _truncate(ranked_lines[0][1])


def _search_topics(
    topics: list[DocTopic], *, query: str, limit: int
) -> list[DocSearchResult]:
    tokens = _query_tokens(query)
    query_lower = query.strip().lower()
    results: list[DocSearchResult] = []

    for topic in topics:
        index_text = "\n".join(
            (
                topic.topic,
                topic.title,
                topic.description,
                topic.markdown,
            )
        ).lower()
        token_hits = sum(1 for token in tokens if token in index_text)
        if token_hits <= 0:
            continue

        snippet = _extract_best_snippet(
            topic, tokens=tokens, query_lower=query_lower
        ) or _truncate(topic.description)

        score = token_hits * 20
        if query_lower and query_lower in index_text:
            score += 30
        if query_lower and query_lower in topic.topic.lower():
            score += 40
        if query_lower and query_lower in topic.title.lower():
            score += 25
        if query_lower and query_lower in topic.description.lower():
            score += 15

        results.append(
            DocSearchResult(
                topic=topic.topic,
                title=topic.title,
                file_name=topic.file_name,
                score=score,
                snippet=snippet,
            )
        )

    results.sort(key=lambda item: (-item.score, item.topic))
    return results[: max(1, int(limit))]


def _emit_list_text(topics: list[DocTopic]) -> None:
    print("TOPIC\tTITLE\tDESCRIPTION")
    for topic in topics:
        print(f"{topic.topic}\t{topic.title}\t{topic.description}")


def _emit_list_json(topics: list[DocTopic]) -> None:
    payload = [
        {
            "topic": topic.topic,
            "title": topic.title,
            "description": topic.description,
        }
        for topic in topics
    ]
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _emit_list_rich(topics: list[DocTopic]) -> None:
    console = make_console("rich")
    render_table(
        console,
        title="Loopfarm Docs",
        headers=("Topic", "Title", "Description", "File"),
        no_wrap_columns=(0, 3),
        rows=[
            (topic.topic, topic.title, topic.description, f"docs/{topic.file_name}")
            for topic in topics
        ],
    )


def _emit_show_json(topic: DocTopic) -> None:
    payload = {
        "topic": topic.topic,
        "title": topic.title,
        "markdown": topic.markdown,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _emit_show_text(topic: DocTopic) -> None:
    print(topic.markdown)


def _emit_show_rich(topic: DocTopic) -> None:
    console = make_console("rich")
    render_panel(
        console,
        f"Topic: {topic.topic}\nFile: docs/{topic.file_name}",
        title=f"[bold blue]{topic.title}[/bold blue]",
    )
    console.print()
    render_markdown(console, topic.markdown)


def _emit_search_text(results: list[DocSearchResult]) -> None:
    if not results:
        print("(no results)")
        return

    print("TOPIC\tTITLE\tFILE\tSCORE\tSNIPPET")
    for row in results:
        print(
            f"{row.topic}\t{row.title}\tdocs/{row.file_name}\t{row.score}\t{row.snippet}"
        )


def _emit_search_json(results: list[DocSearchResult]) -> None:
    payload = [
        {
            "topic": row.topic,
            "title": row.title,
            "file": f"docs/{row.file_name}",
            "score": row.score,
            "snippet": row.snippet,
        }
        for row in results
    ]
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _emit_search_rich(results: list[DocSearchResult]) -> None:
    console = make_console("rich")
    if not results:
        render_panel(console, "(no results)", title="Docs Search")
        return

    render_table(
        console,
        title="Docs Search",
        headers=("Topic", "Title", "File", "Score", "Snippet"),
        no_wrap_columns=(0, 2, 3),
        rows=[
            (
                row.topic,
                row.title,
                f"docs/{row.file_name}",
                str(row.score),
                row.snippet,
            )
            for row in results
        ],
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="loopfarm docs",
        description="Discover and inspect loopfarm concepts from built-in docs topics.",
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="command")

    ls = sub.add_parser("list", help="List available docs topics")
    ls.add_argument("--json", action="store_true", help="Output JSON")
    add_output_mode_argument(ls)

    show = sub.add_parser("show", help="Show one docs topic")
    show.add_argument("topic", help="Topic ID (for example: steps-grammar)")
    show.add_argument("--json", action="store_true", help="Output JSON")
    add_output_mode_argument(show)

    search = sub.add_parser("search", help="Search docs topics and content")
    search.add_argument("query", help="Search query")
    search.add_argument("--topic", help="Restrict search to one docs topic")
    search.add_argument("--limit", type=int, default=20, help="Max rows (default: 20)")
    search.add_argument("--json", action="store_true", help="Output JSON")
    add_output_mode_argument(search)

    return parser


def main(argv: list[str] | None = None) -> None:
    raw_argv = list(argv) if argv is not None else sys.argv[1:]
    if not raw_argv or raw_argv[0].startswith("-"):
        raw_argv = ["list", *raw_argv]

    args = _build_parser().parse_args(raw_argv)
    topics = _load_topics()

    if args.command == "list":
        if args.json:
            _emit_list_json(topics)
            return

        try:
            mode = resolve_output_mode(getattr(args, "output", None))
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            raise SystemExit(2) from exc
        if mode == "rich":
            _emit_list_rich(topics)
        else:
            _emit_list_text(topics)
        return

    if args.command == "show":
        selected = _resolve_topic(topics, args.topic)
        if args.json:
            _emit_show_json(selected)
            return

        try:
            mode = resolve_output_mode(getattr(args, "output", None))
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            raise SystemExit(2) from exc
        if mode == "rich":
            _emit_show_rich(selected)
        else:
            _emit_show_text(selected)
        return

    search_topics = topics
    if args.topic:
        search_topics = [_resolve_topic(topics, args.topic)]
    results = _search_topics(
        search_topics,
        query=args.query,
        limit=max(1, int(args.limit)),
    )
    if args.json:
        _emit_search_json(results)
        return

    try:
        mode = resolve_output_mode(getattr(args, "output", None))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    if mode == "rich":
        _emit_search_rich(results)
    else:
        _emit_search_text(results)
