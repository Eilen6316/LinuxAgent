"""Anthropic prompt cache request shaping tests."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from linuxagent.config.models import APIConfig, LLMProviderName
from linuxagent.providers.anthropic import AnthropicProvider


def _provider(*, prompt_cache: bool = True) -> AnthropicProvider:
    provider = object.__new__(AnthropicProvider)
    provider._config = APIConfig(  # noqa: SLF001
        provider=LLMProviderName.ANTHROPIC,
        api_key="sk-test",
        model="claude-test",
        prompt_cache=prompt_cache,
    )
    provider._prompt_cache_supported = prompt_cache  # noqa: SLF001
    return provider


def test_anthropic_prepare_request_uses_cache_control_not_prompt_cache_key() -> None:
    provider = _provider()

    messages, kwargs = provider._prepare_request(  # noqa: SLF001
        [SystemMessage(content="stable system"), HumanMessage(content="hello")],
        {"prompt_cache_key": "linuxagent:key", "metadata": {"trace": "1"}},
    )

    assert "prompt_cache_key" not in kwargs
    assert kwargs["metadata"] == {"trace": "1"}
    system_content = messages[0].content
    assert isinstance(system_content, list)
    assert system_content[0]["text"] == "stable system"
    assert system_content[0]["cache_control"] == {"type": "ephemeral"}
    assert messages[1].content == "hello"


def test_anthropic_prepare_request_skips_cache_control_when_disabled() -> None:
    provider = _provider(prompt_cache=False)

    messages, kwargs = provider._prepare_request(  # noqa: SLF001
        [SystemMessage(content="stable system")],
        {"prompt_cache_key": "linuxagent:key"},
    )

    assert messages[0].content == "stable system"
    assert "prompt_cache_key" not in kwargs


def test_anthropic_prepare_request_skips_cache_control_after_fallback() -> None:
    provider = _provider()
    provider._prompt_cache_supported = False  # noqa: SLF001

    messages, kwargs = provider._prepare_request(  # noqa: SLF001
        [SystemMessage(content="stable system")],
        {"prompt_cache_key": "linuxagent:key"},
    )

    assert messages[0].content == "stable system"
    assert "prompt_cache_key" not in kwargs


def test_anthropic_prepare_request_marks_existing_text_block() -> None:
    provider = _provider()

    messages, _kwargs = provider._prepare_request(  # noqa: SLF001
        [
            SystemMessage(
                content=[
                    {"type": "text", "text": "first"},
                    {"type": "text", "text": "second"},
                ]
            )
        ],
        {"prompt_cache_key": "linuxagent:key"},
    )

    content = messages[0].content
    assert isinstance(content, list)
    assert "cache_control" not in content[0]
    assert content[1]["cache_control"] == {"type": "ephemeral"}


def test_anthropic_prepare_request_repairs_dangling_tool_call() -> None:
    provider = _provider()
    prior = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "read_file",
                "args": {"path": "README.md"},
                "id": "dangling-anthropic",
                "type": "tool_call",
            }
        ],
    )

    messages, kwargs = provider._prepare_request(  # noqa: SLF001
        [HumanMessage(content="read"), prior],
        {"prompt_cache_key": "linuxagent:key"},
    )

    assert "prompt_cache_key" not in kwargs
    assert isinstance(messages[-1], ToolMessage)
    assert messages[-1].tool_call_id == "dangling-anthropic"
    assert messages[-1].status == "error"
    assert "dangling_tool_call" in str(messages[-1].content)
