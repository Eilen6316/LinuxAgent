"""Compatibility tests for the old intelligence import path."""

from __future__ import annotations

from linuxagent.intelligence import CommandLearner as LegacyCommandLearner
from linuxagent.intelligence.command_learner import CommandLearner as LegacyModuleCommandLearner
from linuxagent.intelligence.context_manager import ContextManager as LegacyContextManager
from linuxagent.usage_insights import CommandLearner, ContextManager


def test_legacy_intelligence_package_reexports_usage_insights() -> None:
    assert LegacyCommandLearner is CommandLearner
    assert LegacyContextManager is ContextManager
    assert LegacyModuleCommandLearner is CommandLearner
