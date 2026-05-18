"""Network policy evaluator tests."""

from __future__ import annotations

from linuxagent.config.models import NetworkConfig
from linuxagent.network_policy import (
    NetworkPolicyAction,
    domain_matches_rule,
    evaluate_network_policy,
    normalize_domain_rule,
    normalize_target_domain,
)


def test_default_network_config_denies_when_disabled() -> None:
    decision = evaluate_network_policy(NetworkConfig(), "example.com")

    assert decision.decision is NetworkPolicyAction.DENY
    assert decision.target_domain == "example.com"
    assert decision.matched_rule == "network.disabled"


def test_denied_domain_wins_over_allowed_domain() -> None:
    config = NetworkConfig(
        enabled=True,
        default_action=NetworkPolicyAction.ALLOW,
        allowed_domains=(".example.com",),
        denied_domains=("api.example.com",),
    )

    decision = evaluate_network_policy(config, "API.EXAMPLE.com.")

    assert decision.decision is NetworkPolicyAction.DENY
    assert decision.target_domain == "api.example.com"
    assert decision.matched_rule == "network.denied_domains"


def test_allowed_domain_overrides_default_deny() -> None:
    config = NetworkConfig(enabled=True, allowed_domains=("api.example.com",))

    decision = evaluate_network_policy(config, "api.example.com")

    assert decision.decision is NetworkPolicyAction.ALLOW
    assert decision.matched_rule == "network.allowed_domains"


def test_unknown_domain_uses_default_action() -> None:
    allow_config = NetworkConfig(enabled=True, default_action=NetworkPolicyAction.ALLOW)
    deny_config = NetworkConfig(enabled=True, default_action=NetworkPolicyAction.DENY)

    assert evaluate_network_policy(allow_config, "other.example").allowed is True
    assert evaluate_network_policy(deny_config, "other.example").allowed is False


def test_wildcard_rule_matches_subdomain_but_not_apex() -> None:
    config = NetworkConfig(enabled=True, allowed_domains=(".example.com",))

    assert evaluate_network_policy(config, "api.example.com").allowed is True
    assert evaluate_network_policy(config, "example.com").allowed is False


def test_domain_normalization_handles_case_trailing_dot_and_idna() -> None:
    assert normalize_target_domain("EXAMPLE.COM.") == "example.com"
    assert normalize_domain_rule("*.例子.测试") == ".xn--fsqu00a.xn--0zwm56d"


def test_empty_target_domain_is_denied() -> None:
    config = NetworkConfig(enabled=True, default_action=NetworkPolicyAction.ALLOW)
    decision = evaluate_network_policy(config, "")

    assert decision.decision is NetworkPolicyAction.DENY
    assert decision.matched_rule == "network.invalid_domain"


def test_domain_rule_matcher_keeps_wildcard_strict() -> None:
    assert domain_matches_rule(".example.com", "api.example.com") is True
    assert domain_matches_rule(".example.com", "example.com") is False
    assert domain_matches_rule("example.com", "api.example.com") is False
