"""Provider-test fixtures.

Several provider tests construct a real ``ChatOpenAI`` client to assert routing
and error-mapping behavior. The OpenAI SDK builds an ``httpx`` client that, with
``trust_env=True``, picks up an ambient ``ALL_PROXY=socks5h://...`` and then
requires the optional ``httpx[socks]`` (``socksio``) package, raising
``ImportError`` at construction when it is absent. None of these tests exercise
proxying, so neutralize the ambient proxy configuration to keep them hermetic and
green in any environment (proxy or not, ``socksio`` installed or not).
"""

from __future__ import annotations

import pytest

_PROXY_ENV_VARS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)


@pytest.fixture(autouse=True)
def _neutralize_proxy_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _PROXY_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
