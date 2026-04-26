"""Capability-based command policy engine."""

from .builtin_rules import builtin_policy_config
from .config_rules import load_policy_config, merge_policy_configs, runtime_policy_config
from .engine import PolicyEngine
from .models import (
    ApprovalMode,
    PolicyApproval,
    PolicyConfig,
    PolicyDecision,
    PolicyMatch,
    PolicyRule,
)

DEFAULT_POLICY_ENGINE = PolicyEngine(builtin_policy_config())

__all__ = [
    "DEFAULT_POLICY_ENGINE",
    "ApprovalMode",
    "PolicyApproval",
    "PolicyConfig",
    "PolicyDecision",
    "PolicyEngine",
    "PolicyMatch",
    "PolicyRule",
    "builtin_policy_config",
    "load_policy_config",
    "merge_policy_configs",
    "runtime_policy_config",
]
