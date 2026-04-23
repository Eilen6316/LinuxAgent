#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
告警系统模块
负责监控阈值检查和告警通知
"""

import time
import logging
import threading
from enum import Enum
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Any, Callable, Union
from datetime import datetime, timedelta

from .system_monitor import SystemMetrics


class AlertLevel(Enum):
    """告警级别"""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertType(Enum):
    """告警类型"""
    THRESHOLD = "threshold"  # 阈值告警
    TREND = "trend"         # 趋势告警
    FREQUENCY = "frequency"  # 频率告警


@dataclass
class AlertRule:
    """告警规则"""
    name: str
    description: str
    metric: str
    threshold: float
    level: AlertLevel
    alert_type: AlertType = AlertType.THRESHOLD
    comparison: str = "gt"  # gt, lt, eq, gte, lte
    duration: int = 60  # 持续时间（秒）
    callback: Optional[Callable] = None
    enabled: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        data = asdict(self)
        data['level'] = self.level.value
        data['alert_type'] = self.alert_type.value
        data['callback'] = None  # 回调函数不能序列化
        return data


@dataclass
class Alert:
    """告警事件"""
    id: str
    rule_name: str
    level: AlertLevel
    message: str
    value: float
    threshold: float
    timestamp: float
    resolved: bool = False
    resolved_timestamp: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        data = asdict(self)
        data['level'] = self.level.value
        return data


class AlertManager:
    """告警管理器"""
    
    def __init__(self, max_alerts: int = 1000):
        """
        初始化告警管理器
        
        Args:
            max_alerts: 最大告警记录数
        """
        self.max_alerts = max_alerts
        self.rules: Dict[str, AlertRule] = {}
        self.active_alerts: Dict[str, Alert] = {}
        self.alert_history: List[Alert] = []
        self.rule_states: Dict[str, Dict[str, Any]] = {}
        self.callbacks: List[Callable[[Alert], None]] = []
        self.logger = logging.getLogger(__name__)
        self._lock = threading.Lock()
        
    def add_rule(self, rule: AlertRule):
        """添加告警规则"""
        with self._lock:
            self.rules[rule.name] = rule
            self.rule_states[rule.name] = {
                'triggered': False,
                'trigger_time': None,
                'last_check': None,
                'consecutive_violations': 0
            }
        self.logger.info(f"添加告警规则: {rule.name}")
    
    def remove_rule(self, rule_name: str):
        """移除告警规则"""
        with self._lock:
            if rule_name in self.rules:
                del self.rules[rule_name]
                del self.rule_states[rule_name]
                # 解决相关的活跃告警
                if rule_name in self.active_alerts:
                    self._resolve_alert(rule_name)
        self.logger.info(f"移除告警规则: {rule_name}")
    
    def get_rule(self, rule_name: str) -> Optional[AlertRule]:
        """获取告警规则"""
        return self.rules.get(rule_name)
    
    def list_rules(self) -> List[AlertRule]:
        """列出所有告警规则"""
        return list(self.rules.values())
    
    def enable_rule(self, rule_name: str):
        """启用告警规则"""
        if rule_name in self.rules:
            self.rules[rule_name].enabled = True
            self.logger.info(f"启用告警规则: {rule_name}")
    
    def disable_rule(self, rule_name: str):
        """禁用告警规则"""
        if rule_name in self.rules:
            self.rules[rule_name].enabled = False
            # 解决相关的活跃告警
            if rule_name in self.active_alerts:
                self._resolve_alert(rule_name)
            self.logger.info(f"禁用告警规则: {rule_name}")
    
    def add_callback(self, callback: Callable[[Alert], None]):
        """添加告警回调函数"""
        self.callbacks.append(callback)
    
    def remove_callback(self, callback: Callable[[Alert], None]):
        """移除告警回调函数"""
        if callback in self.callbacks:
            self.callbacks.remove(callback)
    
    def check_alerts(self, metrics: SystemMetrics):
        """检查告警条件"""
        current_time = time.time()
        
        with self._lock:
            for rule_name, rule in self.rules.items():
                if not rule.enabled:
                    continue
                
                try:
                    self._check_rule(rule, metrics, current_time)
                except Exception as e:
                    self.logger.error(f"检查告警规则 {rule_name} 时出错: {e}")
    
    def _check_rule(self, rule: AlertRule, metrics: SystemMetrics, current_time: float):
        """检查单个告警规则"""
        rule_state = self.rule_states[rule.name]
        
        # 获取指标值
        try:
            current_value = getattr(metrics, rule.metric)
        except AttributeError:
            self.logger.warning(f"指标 {rule.metric} 不存在")
            return
        
        # 检查是否满足告警条件
        is_violation = self._evaluate_condition(current_value, rule.threshold, rule.comparison)
        
        rule_state['last_check'] = current_time
        
        if is_violation:
            rule_state['consecutive_violations'] += 1
            
            if not rule_state['triggered']:
                rule_state['trigger_time'] = current_time
                rule_state['triggered'] = True
            
            # 检查是否达到持续时间要求
            if current_time - rule_state['trigger_time'] >= rule.duration:
                if rule.name not in self.active_alerts:
                    self._trigger_alert(rule, current_value, current_time)
        else:
            rule_state['consecutive_violations'] = 0
            
            if rule_state['triggered']:
                rule_state['triggered'] = False
                rule_state['trigger_time'] = None
                
                # 解决告警
                if rule.name in self.active_alerts:
                    self._resolve_alert(rule.name)
    
    def _evaluate_condition(self, value: float, threshold: float, comparison: str) -> bool:
        """评估条件"""
        if comparison == "gt":
            return value > threshold
        elif comparison == "lt":
            return value < threshold
        elif comparison == "eq":
            return value == threshold
        elif comparison == "gte":
            return value >= threshold
        elif comparison == "lte":
            return value <= threshold
        else:
            return False
    
    def _trigger_alert(self, rule: AlertRule, value: float, timestamp: float):
        """触发告警"""
        alert_id = f"{rule.name}_{int(timestamp)}"
        
        alert = Alert(
            id=alert_id,
            rule_name=rule.name,
            level=rule.level,
            message=self._format_alert_message(rule, value),
            value=value,
            threshold=rule.threshold,
            timestamp=timestamp
        )
        
        self.active_alerts[rule.name] = alert
        self.alert_history.append(alert)
        
        # 限制历史记录大小
        if len(self.alert_history) > self.max_alerts:
            self.alert_history.pop(0)
        
        self.logger.warning(f"触发告警: {alert.message}")
        
        # 执行回调
        self._execute_callbacks(alert)
        
        # 执行规则回调
        if rule.callback:
            try:
                rule.callback(alert)
            except Exception as e:
                self.logger.error(f"执行规则回调时出错: {e}")
    
    def _resolve_alert(self, rule_name: str):
        """解决告警"""
        if rule_name in self.active_alerts:
            alert = self.active_alerts[rule_name]
            alert.resolved = True
            alert.resolved_timestamp = time.time()
            
            del self.active_alerts[rule_name]
            
            self.logger.info(f"解决告警: {rule_name}")
            
            # 通知回调
            self._execute_callbacks(alert)
    
    def _format_alert_message(self, rule: AlertRule, value: float) -> str:
        """格式化告警消息"""
        return (f"[{rule.level.value.upper()}] {rule.description}: "
                f"{rule.metric} = {value:.2f} ({rule.comparison} {rule.threshold})")
    
    def _execute_callbacks(self, alert: Alert):
        """执行回调函数"""
        for callback in self.callbacks:
            try:
                callback(alert)
            except Exception as e:
                self.logger.error(f"执行告警回调时出错: {e}")
    
    def get_active_alerts(self) -> List[Alert]:
        """获取活跃告警"""
        return list(self.active_alerts.values())
    
    def get_alert_history(self, hours: int = 24) -> List[Alert]:
        """获取告警历史"""
        if hours <= 0:
            return self.alert_history.copy()
        
        cutoff_time = time.time() - (hours * 3600)
        return [alert for alert in self.alert_history if alert.timestamp >= cutoff_time]
    
    def get_alert_statistics(self) -> Dict[str, Any]:
        """获取告警统计"""
        stats = {
            'total_rules': len(self.rules),
            'enabled_rules': sum(1 for rule in self.rules.values() if rule.enabled),
            'active_alerts': len(self.active_alerts),
            'total_alerts_24h': len(self.get_alert_history(24)),
            'alert_counts_by_level': {},
            'alert_counts_by_rule': {}
        }
        
        # 按级别统计
        for alert in self.get_alert_history(24):
            level = alert.level.value
            stats['alert_counts_by_level'][level] = stats['alert_counts_by_level'].get(level, 0) + 1
        
        # 按规则统计
        for alert in self.get_alert_history(24):
            rule_name = alert.rule_name
            stats['alert_counts_by_rule'][rule_name] = stats['alert_counts_by_rule'].get(rule_name, 0) + 1
        
        return stats
    
    def clear_alert_history(self):
        """清空告警历史"""
        with self._lock:
            self.alert_history.clear()
        self.logger.info("告警历史已清空")


def create_default_rules() -> List[AlertRule]:
    """创建默认告警规则"""
    return [
        AlertRule(
            name="high_cpu_usage",
            description="CPU使用率过高",
            metric="cpu_percent",
            threshold=80.0,
            level=AlertLevel.WARNING,
            duration=120  # 2分钟
        ),
        AlertRule(
            name="critical_cpu_usage",
            description="CPU使用率严重过高",
            metric="cpu_percent",
            threshold=90.0,
            level=AlertLevel.CRITICAL,
            duration=60  # 1分钟
        ),
        AlertRule(
            name="high_memory_usage",
            description="内存使用率过高",
            metric="memory_percent",
            threshold=85.0,
            level=AlertLevel.WARNING,
            duration=300  # 5分钟
        ),
        AlertRule(
            name="critical_memory_usage",
            description="内存使用率严重过高",
            metric="memory_percent",
            threshold=95.0,
            level=AlertLevel.CRITICAL,
            duration=60  # 1分钟
        ),
        AlertRule(
            name="high_disk_usage",
            description="磁盘使用率过高",
            metric="disk_percent",
            threshold=85.0,
            level=AlertLevel.WARNING,
            duration=600  # 10分钟
        ),
        AlertRule(
            name="critical_disk_usage",
            description="磁盘使用率严重过高",
            metric="disk_percent",
            threshold=95.0,
            level=AlertLevel.CRITICAL,
            duration=300  # 5分钟
        ),
        AlertRule(
            name="too_many_processes",
            description="进程数量过多",
            metric="process_count",
            threshold=500,
            level=AlertLevel.WARNING,
            duration=300  # 5分钟
        )
    ]


if __name__ == "__main__":
    # 测试代码
    logging.basicConfig(level=logging.INFO)
    
    def on_alert(alert: Alert):
        status = "解决" if alert.resolved else "触发"
        print(f"告警{status}: {alert.message}")
    
    # 创建告警管理器
    alert_manager = AlertManager()
    alert_manager.add_callback(on_alert)
    
    # 添加默认规则
    for rule in create_default_rules():
        alert_manager.add_rule(rule)
    
    # 模拟系统指标
    from .system_monitor import SystemMetrics
    
    # 模拟正常指标
    normal_metrics = SystemMetrics(
        timestamp=time.time(),
        cpu_percent=30.0,
        memory_percent=60.0,
        memory_total=8589934592,
        memory_available=3221225472,
        disk_percent=70.0,
        disk_total=107374182400,
        disk_free=32212254720,
        network_bytes_sent=1048576,
        network_bytes_recv=2097152,
        load_avg=[0.5, 0.6, 0.7],
        process_count=150,
        boot_time=1642492800.0
    )
    
    # 模拟高CPU使用率
    high_cpu_metrics = SystemMetrics(
        timestamp=time.time(),
        cpu_percent=95.0,
        memory_percent=60.0,
        memory_total=8589934592,
        memory_available=3221225472,
        disk_percent=70.0,
        disk_total=107374182400,
        disk_free=32212254720,
        network_bytes_sent=1048576,
        network_bytes_recv=2097152,
        load_avg=[0.5, 0.6, 0.7],
        process_count=150,
        boot_time=1642492800.0
    )
    
    print("测试告警系统...")
    alert_manager.check_alerts(normal_metrics)
    print("正常指标检查完成")
    
    alert_manager.check_alerts(high_cpu_metrics)
    print("高CPU使用率检查完成")
    
    print(f"活跃告警数: {len(alert_manager.get_active_alerts())}")
    print(f"告警统计: {alert_manager.get_alert_statistics()}")
