from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_ci_staging_uploads_parity_and_cutover_summaries() -> None:
    ci = read(".github/workflows/ci.yml")

    assert "run_cutover_check" in ci
    assert "ts-parity-summary.txt" in ci
    assert "cutover-check-summary.txt" in ci
    assert "actions/upload-artifact@v4" in ci


def test_public_docs_keep_cutover_explicit_and_reversible() -> None:
    readme = read("README.md")
    en = read("docs/en/typescript-v5.md")
    zh = read("docs/zh/typescript-v5.md")
    release = read("docs/releases/vNext.md")

    assert "LangGraph remains the old Python runtime" in readme
    assert "ReAct turn-level parity fixtures" in en
    assert "ReAct turn-level parity fixture" in zh
    assert "maintainer explicitly approves" in release
    assert "restore the Python `linuxagent` entry point" in release
