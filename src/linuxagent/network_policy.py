"""Domain-level network policy decisions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class NetworkPolicyAction(StrEnum):
    ALLOW = "allow"
    DENY = "deny"


@dataclass(frozen=True)
class NetworkDecision:
    target_domain: str
    decision: NetworkPolicyAction
    matched_rule: str
    reason: str

    @property
    def allowed(self) -> bool:
        return self.decision is NetworkPolicyAction.ALLOW


class NetworkPolicySettings(Protocol):
    enabled: bool
    default_action: NetworkPolicyAction
    allowed_domains: tuple[str, ...]
    denied_domains: tuple[str, ...]


def evaluate_network_policy(config: NetworkPolicySettings, domain: str) -> NetworkDecision:
    normalized = normalize_target_domain(domain)
    if normalized is None:
        return NetworkDecision("", NetworkPolicyAction.DENY, "network.invalid_domain", "empty host")
    if not config.enabled:
        return NetworkDecision(
            normalized,
            NetworkPolicyAction.DENY,
            "network.disabled",
            "network tools are disabled",
        )
    denied = _matching_rule(config.denied_domains, normalized)
    if denied is not None:
        return NetworkDecision(
            normalized,
            NetworkPolicyAction.DENY,
            "network.denied_domains",
            f"domain matched deny rule {denied}",
        )
    allowed = _matching_rule(config.allowed_domains, normalized)
    if allowed is not None:
        return NetworkDecision(
            normalized,
            NetworkPolicyAction.ALLOW,
            "network.allowed_domains",
            f"domain matched allow rule {allowed}",
        )
    return _default_decision(config.default_action, normalized)


def normalize_domain_rule(domain: str) -> str:
    raw = domain.strip()
    wildcard = raw.startswith("*.") or raw.startswith(".")
    host = raw[2:] if raw.startswith("*.") else raw[1:] if raw.startswith(".") else raw
    normalized = _normalize_host(host)
    if normalized is None:
        raise ValueError(f"invalid network domain: {domain!r}")
    return f".{normalized}" if wildcard else normalized


def normalize_target_domain(domain: str) -> str | None:
    return _normalize_host(domain)


def domain_matches_rule(rule: str, normalized_domain: str) -> bool:
    if rule.startswith("."):
        suffix = rule[1:]
        return bool(suffix) and normalized_domain.endswith(rule)
    return rule == normalized_domain


def _default_decision(action: NetworkPolicyAction, domain: str) -> NetworkDecision:
    if action is NetworkPolicyAction.ALLOW:
        return NetworkDecision(
            domain,
            NetworkPolicyAction.ALLOW,
            "network.default_allow",
            "domain matched default allow action",
        )
    return NetworkDecision(
        domain,
        NetworkPolicyAction.DENY,
        "network.default_deny",
        "domain matched default deny action",
    )


def _matching_rule(rules: tuple[str, ...], domain: str) -> str | None:
    return next((rule for rule in rules if domain_matches_rule(rule, domain)), None)


def _normalize_host(host: str) -> str | None:
    trimmed = host.strip().rstrip(".").lower()
    if not trimmed or any(char in trimmed for char in "/\\:@"):
        return None
    labels = tuple(label for label in trimmed.split(".") if label)
    if len(labels) != len(trimmed.split(".")):
        return None
    return _ascii_domain(labels)


def _ascii_domain(labels: tuple[str, ...]) -> str | None:
    normalized: list[str] = []
    for label in labels:
        ascii_label = _idna_label(label)
        if ascii_label is None or not _valid_ascii_label(ascii_label):
            return None
        normalized.append(ascii_label)
    domain = ".".join(normalized)
    return domain if len(domain) <= 253 else None


def _idna_label(label: str) -> str | None:
    try:
        return label.encode("idna").decode("ascii").lower()
    except UnicodeError:
        return None


def _valid_ascii_label(label: str) -> bool:
    if not label or len(label) > 63 or label.startswith("-") or label.endswith("-"):
        return False
    return all(char.isascii() and (char.isalnum() or char == "-") for char in label)
