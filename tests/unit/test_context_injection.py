"""On-demand context injection tests."""

from __future__ import annotations

from linuxagent.context_injection import (
    ContextSource,
    linuxagent_manual_context,
    manual_prompt_context,
)


def test_linuxagent_manual_context_uses_loader_and_budget() -> None:
    injection = linuxagent_manual_context("capability answer", loader=lambda: "manual body")

    assert injection.source is ContextSource.LINUXAGENT_MANUAL
    assert injection.reason == "capability answer"
    assert injection.content == "manual body"
    assert injection.budget == {"characters": 11}
    assert injection.summary == "manual body"


def test_manual_prompt_context_injects_only_when_content_exists() -> None:
    injection = linuxagent_manual_context("capability answer", loader=lambda: "manual body")

    assert manual_prompt_context("product", injection) == "product\n\nmanual body"
    assert manual_prompt_context("product", None) == "product"
    assert (
        manual_prompt_context(
            "product",
            linuxagent_manual_context("empty", loader=lambda: ""),
        )
        == "product"
    )
