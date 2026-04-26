"""Monitoring package re-export tests."""

from __future__ import annotations

import linuxagent.monitoring as monitoring
from linuxagent.services import (
    MonitoringAlert,
    MonitoringService,
    collect_system_snapshot,
    evaluate_alerts,
)


def test_monitoring_package_reexports_public_objects() -> None:
    assert monitoring.MonitoringAlert is MonitoringAlert
    assert monitoring.MonitoringService is MonitoringService
    assert monitoring.collect_system_snapshot is collect_system_snapshot
    assert monitoring.evaluate_alerts is evaluate_alerts
    assert set(monitoring.__all__) == {
        "MonitoringAlert",
        "MonitoringService",
        "collect_system_snapshot",
        "evaluate_alerts",
    }
