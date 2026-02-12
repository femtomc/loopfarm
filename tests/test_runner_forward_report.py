from __future__ import annotations

from pathlib import Path

from loopfarm.runner import CodexPhaseModel, LoopfarmConfig, LoopfarmRunner


def _cfg(tmp_path: Path) -> LoopfarmConfig:
    model = CodexPhaseModel(model="test", reasoning="fast")
    return LoopfarmConfig(
        repo_root=tmp_path,
        project="test",
        prompt="prompt",
        loop_steps=(("forward", 1), ("backward", 1)),
        termination_phase="backward",
        phase_models=(("forward", model), ("backward", model)),
        phase_cli_overrides=(("forward", "codex"), ("backward", "codex")),
        phase_prompt_overrides=(
            ("forward", str(tmp_path / ".loopfarm" / "prompts" / "forward.md")),
            ("backward", str(tmp_path / ".loopfarm" / "prompts" / "backward.md")),
        ),
    )


def test_inject_forward_report_prefers_payload(monkeypatch: object, tmp_path: Path) -> None:
    runner = LoopfarmRunner(_cfg(tmp_path))
    called = {"value": False}

    def fake_read(session_id: str) -> dict[str, str]:
        called["value"] = True
        return {"summary": "fallback", "pre_head": "x", "post_head": "y", "commit_range": ""}

    monkeypatch.setattr(runner, "_read_forward_report", fake_read)  # type: ignore[attr-defined]

    payload = {"summary": "from memory", "pre_head": "a", "post_head": "b", "commit_range": ""}
    out = runner._inject_forward_report("{{FORWARD_REPORT}}", "sess", payload)

    assert "from memory" in out
    assert "HEAD: a -> b" in out
    assert called["value"] is False


def test_inject_forward_report_fallback_reads(monkeypatch: object, tmp_path: Path) -> None:
    runner = LoopfarmRunner(_cfg(tmp_path))

    def fake_read(session_id: str) -> dict[str, str]:
        return {"summary": "from forum", "pre_head": "a", "post_head": "b", "commit_range": ""}

    monkeypatch.setattr(runner, "_read_forward_report", fake_read)  # type: ignore[attr-defined]

    out = runner._inject_forward_report("{{FORWARD_REPORT}}", "sess", None)

    assert "from forum" in out
    assert "HEAD: a -> b" in out
