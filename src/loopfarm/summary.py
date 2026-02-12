from __future__ import annotations

import json
import tempfile
from pathlib import Path

from .util import CommandError, run_capture


def extract_phase_summary_from_last_message(path: Path) -> str:
    if not path.exists() or path.stat().st_size == 0:
        return ""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    in_block = False
    out: list[str] = []
    start_markers = {"---LOOPFARM-PHASE-SUMMARY---"}
    end_markers = {"---END-LOOPFARM-PHASE-SUMMARY---"}
    for line in lines:
        stripped = line.strip()
        if stripped in start_markers:
            in_block = True
            continue
        if stripped in end_markers:
            break
        if in_block:
            out.append(line)
    return "\n".join(out).strip()


def _extract_claude_transcript(stream_json_path: Path) -> str:
    if not stream_json_path.exists() or stream_json_path.stat().st_size == 0:
        return ""

    text_parts: list[str] = []
    with stream_json_path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except Exception:
                continue
            if event.get("type") != "stream_event":
                continue
            ev = event.get("event", {})
            if ev.get("type") != "content_block_delta":
                continue
            delta = ev.get("delta", {})
            if delta.get("type") != "text_delta":
                continue
            text = delta.get("text") or ""
            if text:
                text_parts.append(text)
    return "".join(text_parts)


def summarize_with_haiku(phase: str, stream_json_path: Path) -> str:
    transcript = _extract_claude_transcript(stream_json_path)
    if not transcript.strip():
        return ""

    # Write to /tmp explicitly - Claude Code's sandbox allows /tmp but not /var
    transcript_path = Path(
        tempfile.mktemp(dir="/tmp", prefix="loopfarm_transcript_", suffix=".txt")
    )
    transcript_path.write_text(transcript, encoding="utf-8")

    try:
        prompt = (
            "You are writing a brief status update for a human monitoring an automated coding agent. "
            f"The human wants to know what the agent accomplished, answered, or struggled with during this {phase} phase.\n\n"
            f"Read the transcript at {transcript_path} and write 2-4 sentences describing:\n"
            "- What the agent did, built, or answered\n"
            "- Files modified or created (if any)\n"
            "- Any blockers, tensions, or unresolved issues\n\n"
            "If blockers exist, prefix with 'BLOCKER:'. Be direct and specific. "
            "No meta-commentary about the transcript itself. Start immediately with your summary."
        )
        out = run_capture(
            ["claude", "-p", "--model", "haiku", "--output-format", "text", "--dangerously-skip-permissions", prompt],
            cwd=Path("/tmp"),
        )
        return out.strip()
    except CommandError:
        return ""
    finally:
        try:
            transcript_path.unlink()
        except OSError:
            pass
