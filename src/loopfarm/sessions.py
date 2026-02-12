from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .forum import Forum

_SESSION_TOPIC_RE = re.compile(r"^loopfarm:session:(?P<session_id>[^\s]+)$")


def _to_int(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return int(text)
        except ValueError:
            return None
    return None


def _iso_from_epoch_ms(value: object) -> str | None:
    ms = _to_int(value)
    if ms is None:
        return None
    try:
        dt = datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _truncate(value: object, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    if limit <= 3:
        return text[:limit]
    return text[: limit - 3] + "..."


def _decode_message_body(body: object) -> tuple[str | None, dict[str, Any] | None]:
    if not isinstance(body, str) or not body.strip():
        return None, None
    try:
        payload = json.loads(body)
    except Exception:
        return None, None

    if not isinstance(payload, dict):
        return None, None

    schema = payload.get("schema")
    if isinstance(schema, str) and isinstance(payload.get("data"), dict):
        return schema, payload["data"]
    return None, payload


def _with_iso_timestamps(payload: Any) -> Any:
    if isinstance(payload, dict):
        out: dict[str, Any] = {}
        for key, value in payload.items():
            out[key] = _with_iso_timestamps(value)
            if key.endswith("_at"):
                iso = _iso_from_epoch_ms(value)
                if iso:
                    out[f"{key}_iso"] = iso
        return out
    if isinstance(payload, list):
        return [_with_iso_timestamps(item) for item in payload]
    return payload


def _emit_json(payload: Any) -> None:
    print(json.dumps(_with_iso_timestamps(payload), ensure_ascii=False, indent=2))


@dataclass
class Sessions:
    forum: Forum

    @classmethod
    def from_workdir(cls, cwd: Path | None = None) -> "Sessions":
        return cls(Forum.from_workdir(cwd, create=False))

    def _session_topic_rows(self) -> list[tuple[str, dict[str, Any]]]:
        rows: list[tuple[str, dict[str, Any]]] = []
        for topic in self.forum.list_topics():
            name = topic.get("name")
            if not isinstance(name, str):
                continue
            match = _SESSION_TOPIC_RE.match(name)
            if not match:
                continue
            rows.append((match.group("session_id"), topic))
        rows.sort(
            key=lambda item: _to_int(item[1].get("updated_at")) or _to_int(item[1].get("created_at")) or 0,
            reverse=True,
        )
        return rows

    def _latest_session_meta(self, session_id: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
        topic = f"loopfarm:session:{session_id}"
        messages = self.forum.read(topic, limit=24)
        for message in messages:
            schema, payload = _decode_message_body(message.get("body"))
            if not isinstance(payload, dict):
                continue
            if schema and not schema.endswith("session.meta.v1"):
                continue
            if (
                "prompt" not in payload
                and "status" not in payload
                and "started" not in payload
                and "phase" not in payload
            ):
                continue
            return payload, message
        return {}, None

    def _latest_status(self, session_id: str) -> tuple[str | None, str | None]:
        topic = f"loopfarm:status:{session_id}"
        messages = self.forum.read(topic, limit=6)
        for message in messages:
            _, payload = _decode_message_body(message.get("body"))
            if not isinstance(payload, dict):
                continue
            decision = payload.get("decision")
            summary = payload.get("summary")
            if decision is None and summary is None:
                continue
            return (
                str(decision) if decision is not None else None,
                str(summary) if summary is not None else None,
            )
        return None, None

    def _briefings(self, session_id: str, *, limit: int) -> list[dict[str, Any]]:
        topic = f"loopfarm:briefing:{session_id}"
        messages = self.forum.read(topic, limit=max(limit, 20))
        rows: list[dict[str, Any]] = []
        for message in messages:
            schema, payload = _decode_message_body(message.get("body"))
            if not isinstance(payload, dict):
                continue
            if schema and not schema.endswith("session.briefing.v1"):
                continue
            if "summary" not in payload and "phase" not in payload:
                continue
            created_at = _to_int(message.get("created_at"))
            rows.append(
                {
                    "phase": payload.get("phase"),
                    "iteration": payload.get("iteration"),
                    "summary": str(payload.get("summary") or "").strip(),
                    "timestamp": payload.get("timestamp"),
                    "created_at": created_at,
                    "created_at_iso": _iso_from_epoch_ms(created_at),
                }
            )
        rows.sort(key=lambda row: row.get("created_at") or 0, reverse=True)
        return rows[:limit]

    def list(
        self,
        *,
        limit: int = 20,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        expected_status = (status or "").strip().lower()

        for session_id, topic in self._session_topic_rows():
            meta, meta_message = self._latest_session_meta(session_id)
            decision, decision_summary = self._latest_status(session_id)
            briefings = self._briefings(session_id, limit=1)

            meta_status = str(meta.get("status") or "unknown").strip() or "unknown"
            if expected_status and meta_status.lower() != expected_status:
                continue

            started = meta.get("started")
            if not started and meta_message is not None:
                started = _iso_from_epoch_ms(meta_message.get("created_at"))

            topic_created_at = _to_int(topic.get("created_at"))
            topic_updated_at = _to_int(topic.get("updated_at"))
            rows.append(
                {
                    "session_id": session_id,
                    "status": meta_status,
                    "phase": meta.get("phase"),
                    "iteration": meta.get("iteration"),
                    "started": started,
                    "ended": meta.get("ended"),
                    "prompt": str(meta.get("prompt") or "").strip(),
                    "decision": decision,
                    "decision_summary": decision_summary,
                    "latest_summary": briefings[0]["summary"] if briefings else None,
                    "topic_created_at": topic_created_at,
                    "topic_created_at_iso": _iso_from_epoch_ms(topic_created_at),
                    "topic_updated_at": topic_updated_at,
                    "topic_updated_at_iso": _iso_from_epoch_ms(topic_updated_at),
                }
            )

        rows.sort(
            key=lambda row: str(row.get("started") or row.get("topic_updated_at_iso") or ""),
            reverse=True,
        )
        return rows[: max(1, int(limit))]

    def show(self, session_id: str, *, briefing_limit: int = 8) -> dict[str, Any] | None:
        session_key = session_id.strip()
        if not session_key:
            return None

        topic = None
        for candidate_session_id, candidate_topic in self._session_topic_rows():
            if candidate_session_id == session_key:
                topic = candidate_topic
                break
        if topic is None:
            return None

        meta, meta_message = self._latest_session_meta(session_key)
        decision, decision_summary = self._latest_status(session_key)
        briefings = self._briefings(session_key, limit=max(1, int(briefing_limit)))

        started = meta.get("started")
        if not started and meta_message is not None:
            started = _iso_from_epoch_ms(meta_message.get("created_at"))

        topic_created_at = _to_int(topic.get("created_at"))
        topic_updated_at = _to_int(topic.get("updated_at"))
        details = {
            "session_id": session_key,
            "status": str(meta.get("status") or "unknown").strip() or "unknown",
            "phase": meta.get("phase"),
            "iteration": meta.get("iteration"),
            "started": started,
            "ended": meta.get("ended"),
            "prompt": str(meta.get("prompt") or "").strip(),
            "decision": decision,
            "decision_summary": decision_summary,
            "latest_summary": briefings[0]["summary"] if briefings else None,
            "topic_created_at": topic_created_at,
            "topic_created_at_iso": _iso_from_epoch_ms(topic_created_at),
            "topic_updated_at": topic_updated_at,
            "topic_updated_at_iso": _iso_from_epoch_ms(topic_updated_at),
        }
        details["briefings"] = briefings
        return details


def _print_session_rows(rows: list[dict[str, Any]]) -> None:
    headers = ("SESSION", "STATUS", "PHASE", "ITER", "STARTED", "DECISION", "PROMPT")
    values: list[tuple[str, str, str, str, str, str, str]] = []
    for row in rows:
        values.append(
            (
                str(row.get("session_id") or ""),
                str(row.get("status") or "-"),
                str(row.get("phase") or "-"),
                str(row.get("iteration") or "-"),
                str(row.get("started") or row.get("topic_created_at_iso") or "-"),
                str(row.get("decision") or "-"),
                _truncate(row.get("prompt"), 72),
            )
        )

    widths = [len(item) for item in headers]
    for row in values:
        for idx, col in enumerate(row):
            widths[idx] = max(widths[idx], len(col))

    print("  ".join(headers[idx].ljust(widths[idx]) for idx in range(len(headers))))
    print("  ".join("-" * widths[idx] for idx in range(len(headers))))
    for row in values:
        print("  ".join(row[idx].ljust(widths[idx]) for idx in range(len(headers))))


def _print_session_detail(row: dict[str, Any]) -> None:
    print(f"session:   {row.get('session_id')}")
    print(f"status:    {row.get('status') or '-'}")
    print(f"phase:     {row.get('phase') or '-'}")
    print(f"iteration: {row.get('iteration') or '-'}")
    print(f"started:   {row.get('started') or row.get('topic_created_at_iso') or '-'}")
    print(f"ended:     {row.get('ended') or '-'}")
    print(f"decision:  {row.get('decision') or '-'}")
    print(f"summary:   {row.get('decision_summary') or row.get('latest_summary') or '-'}")
    print()
    print("prompt:")
    print(row.get("prompt") or "-")
    print()
    print("briefings:")

    briefings = row.get("briefings") or []
    if not briefings:
        print("  (none)")
    else:
        for item in briefings:
            phase = item.get("phase") or "unknown"
            iteration = item.get("iteration")
            summary = item.get("summary") or ""
            if iteration is None:
                print(f"  [{phase}] {summary}")
            else:
                print(f"  [{phase} #{iteration}] {summary}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="loopfarm sessions",
        description="List and inspect loopfarm session history.",
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="command")

    ls = sub.add_parser("list", help="List sessions")
    ls.add_argument("--status", help="Filter by session status")
    ls.add_argument("--limit", type=int, default=20, help="Max rows (default: 20)")
    ls.add_argument("--json", action="store_true", help="Output JSON")

    show = sub.add_parser("show", help="Show one session")
    show.add_argument("id", help="Session id")
    show.add_argument(
        "--briefings",
        type=int,
        default=8,
        help="Number of recent briefings to include (default: 8)",
    )
    show.add_argument("--json", action="store_true", help="Output JSON")

    return parser


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)
    sessions = Sessions.from_workdir(Path.cwd())

    if args.command == "list":
        rows = sessions.list(
            limit=max(1, int(args.limit)),
            status=args.status,
        )
        if args.json:
            _emit_json(rows)
        else:
            if not rows:
                print("(no sessions)")
            else:
                _print_session_rows(rows)
        return

    if args.command == "show":
        row = sessions.show(args.id, briefing_limit=max(1, int(args.briefings)))
        if row is None:
            print(f"error: session not found: {args.id}", file=sys.stderr)
            raise SystemExit(1)
        if args.json:
            _emit_json(row)
        else:
            _print_session_detail(row)
        return


if __name__ == "__main__":
    main()
