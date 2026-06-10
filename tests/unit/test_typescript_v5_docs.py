from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_typescript_v5_design_names_react_pi_runtime_boundary() -> None:
    text = (ROOT / "docs" / "design" / "typescript-v5-progressive-rewrite.md").read_text(
        encoding="utf-8"
    )

    assert "pi-agent-core ReAct runtime" in text
    assert "LinuxAgent safety kernel" in text
    assert "LinuxAgentToolGate" in text
    assert "LangGraph is the old Python runtime" in text
    assert "pi-coding-agent" in text
    assert "bash`, `write`, or `edit`" in text
