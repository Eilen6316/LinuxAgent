#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
日志异常检测器模块
负责检测日志中的异常模式和错误
"""

import re
import time
import logging
from typing import List, Dict, Set, Optional, Tuple
from collections import defaultdict, Counter
from dataclasses import dataclass
from datetime import datetime, timedelta

from .log_parser import LogEntry, LogLevel


@dataclass
class AnomalyPattern:
    """异常模式定义"""
    name: str
    pattern: str
    level: LogLevel
    description: str
    enabled: bool = True


@dataclass
class Anomaly:
    """检测到的异常"""
    pattern_name: str
    entries: List[LogEntry]
    count: int
    first_occurrence: datetime
    last_occurrence: datetime
    severity: LogLevel
    description: str
    
    def to_dict(self) -> Dict:
        """转换为字典格式"""
        return {
            'pattern_name': self.pattern_name,
            'count': self.count,
            'first_occurrence': self.first_occurrence.isoformat(),
            'last_occurrence': self.last_occurrence.isoformat(),
            'severity': self.severity.value,
            'description': self.description,
            'sample_entries': [entry.to_dict() for entry in self.entries[:5]]  # 只保留前5个样本
        }


class AnomalyDetector:
    """异常检测器"""
    
    def __init__(self, similarity_threshold: float = 0.8, frequency_threshold: int = 10):
        """
        初始化异常检测器
        
        Args:
            similarity_threshold: 消息相似度阈值
            frequency_threshold: 频率异常阈值
        """
        self.similarity_threshold = similarity_threshold
        self.frequency_threshold = frequency_threshold
        self.logger = logging.getLogger(__name__)
        
        # 预定义的异常模式
        self.patterns = self._create_default_patterns()
        
        # 异常检测结果
        self.detected_anomalies: List[Anomaly] = []
        
    def _create_default_patterns(self) -> List[AnomalyPattern]:
        """创建默认的异常模式"""
        return [
            AnomalyPattern(
                name="authentication_failure",
                pattern=r"(failed|failure|denied|invalid|unauthorized|authentication|login).*?(password|user|auth|login|credential)",
                level=LogLevel.WARNING,
                description="认证失败"
            ),
            AnomalyPattern(
                name="connection_error",
                pattern=r"(connection|connect).*?(refused|failed|timeout|error|reset|closed|broken|lost)",
                level=LogLevel.ERROR,
                description="连接错误"
            ),
            AnomalyPattern(
                name="permission_denied",
                pattern=r"(permission|access).*?(denied|forbidden|not allowed|unauthorized)",
                level=LogLevel.WARNING,
                description="权限被拒绝"
            ),
            AnomalyPattern(
                name="memory_error",
                pattern=r"(out of memory|memory.*?error|oom|killed|segmentation fault|memory.*?leak)",
                level=LogLevel.CRITICAL,
                description="内存错误"
            ),
            AnomalyPattern(
                name="disk_error",
                pattern=r"(disk.*?full|no space|quota.*?exceed|disk.*?error|i/o error|read-only)",
                level=LogLevel.CRITICAL,
                description="磁盘错误"
            ),
            AnomalyPattern(
                name="network_error",
                pattern=r"(network.*?error|network.*?unreachable|name resolution|dns.*?error)",
                level=LogLevel.ERROR,
                description="网络错误"
            ),
            AnomalyPattern(
                name="service_error",
                pattern=r"(service.*?failed|daemon.*?error|process.*?died|service.*?timeout)",
                level=LogLevel.ERROR,
                description="服务错误"
            ),
            AnomalyPattern(
                name="security_alert",
                pattern=r"(attack|intrusion|malware|virus|suspicious|breach|exploit|vulnerability)",
                level=LogLevel.CRITICAL,
                description="安全警报"
            ),
            AnomalyPattern(
                name="database_error",
                pattern=r"(database.*?error|sql.*?error|connection.*?pool|deadlock|transaction.*?failed)",
                level=LogLevel.ERROR,
                description="数据库错误"
            ),
            AnomalyPattern(
                name="application_error",
                pattern=r"(exception|stack.*?trace|null.*?pointer|index.*?error|runtime.*?error)",
                level=LogLevel.ERROR,
                description="应用程序错误"
            )
        ]
    
    def add_pattern(self, pattern: AnomalyPattern):
        """添加异常模式"""
        self.patterns.append(pattern)
        self.logger.info(f"添加异常模式: {pattern.name}")
    
    def remove_pattern(self, pattern_name: str):
        """移除异常模式"""
        self.patterns = [p for p in self.patterns if p.name != pattern_name]
        self.logger.info(f"移除异常模式: {pattern_name}")
    
    def enable_pattern(self, pattern_name: str):
        """启用异常模式"""
        for pattern in self.patterns:
            if pattern.name == pattern_name:
                pattern.enabled = True
                self.logger.info(f"启用异常模式: {pattern_name}")
                break
    
    def disable_pattern(self, pattern_name: str):
        """禁用异常模式"""
        for pattern in self.patterns:
            if pattern.name == pattern_name:
                pattern.enabled = False
                self.logger.info(f"禁用异常模式: {pattern_name}")
                break
    
    def detect_anomalies(self, log_entries: List[LogEntry]) -> List[Anomaly]:
        """
        检测日志异常
        
        Args:
            log_entries: 日志条目列表
            
        Returns:
            检测到的异常列表
        """
        self.detected_anomalies = []
        
        # 1. 基于错误级别的异常检测
        self._detect_level_anomalies(log_entries)
        
        # 2. 基于模式匹配的异常检测
        self._detect_pattern_anomalies(log_entries)
        
        # 3. 基于频率的异常检测
        self._detect_frequency_anomalies(log_entries)
        
        # 4. 基于时间聚集的异常检测
        self._detect_time_clustering_anomalies(log_entries)
        
        return self.detected_anomalies
    
    def _detect_level_anomalies(self, log_entries: List[LogEntry]):
        """检测基于日志级别的异常"""
        error_entries = [entry for entry in log_entries if entry.level in [LogLevel.ERROR, LogLevel.CRITICAL, LogLevel.FATAL]]
        
        if error_entries:
            self.detected_anomalies.append(Anomaly(
                pattern_name="high_error_level",
                entries=error_entries,
                count=len(error_entries),
                first_occurrence=min(entry.timestamp for entry in error_entries),
                last_occurrence=max(entry.timestamp for entry in error_entries),
                severity=LogLevel.ERROR,
                description=f"检测到 {len(error_entries)} 条错误级别日志"
            ))
    
    def _detect_pattern_anomalies(self, log_entries: List[LogEntry]):
        """检测基于模式匹配的异常"""
        for pattern in self.patterns:
            if not pattern.enabled:
                continue
                
            matched_entries = []
            regex = re.compile(pattern.pattern, re.IGNORECASE)
            
            for entry in log_entries:
                if regex.search(entry.message):
                    matched_entries.append(entry)
            
            if matched_entries:
                self.detected_anomalies.append(Anomaly(
                    pattern_name=pattern.name,
                    entries=matched_entries,
                    count=len(matched_entries),
                    first_occurrence=min(entry.timestamp for entry in matched_entries),
                    last_occurrence=max(entry.timestamp for entry in matched_entries),
                    severity=pattern.level,
                    description=f"{pattern.description}: {len(matched_entries)} 条匹配"
                ))
    
    def _detect_frequency_anomalies(self, log_entries: List[LogEntry]):
        """检测基于频率的异常"""
        # 统计相似消息的出现频率
        message_groups = defaultdict(list)
        
        for entry in log_entries:
            # 简化消息，移除时间戳和数字
            simplified_message = re.sub(r'\d+', 'X', entry.message)
            simplified_message = re.sub(r'\d{4}-\d{2}-\d{2}', 'DATE', simplified_message)
            simplified_message = re.sub(r'\d{2}:\d{2}:\d{2}', 'TIME', simplified_message)
            
            message_groups[simplified_message].append(entry)
        
        # 检查高频消息
        for message_pattern, entries in message_groups.items():
            if len(entries) >= self.frequency_threshold:
                self.detected_anomalies.append(Anomaly(
                    pattern_name="frequent_message",
                    entries=entries,
                    count=len(entries),
                    first_occurrence=min(entry.timestamp for entry in entries),
                    last_occurrence=max(entry.timestamp for entry in entries),
                    severity=LogLevel.WARNING,
                    description=f"高频消息: {len(entries)} 次出现"
                ))
    
    def _detect_time_clustering_anomalies(self, log_entries: List[LogEntry]):
        """检测基于时间聚集的异常"""
        if not log_entries:
            return
            
        # 按时间排序
        sorted_entries = sorted(log_entries, key=lambda x: x.timestamp)
        
        # 检测时间窗口内的异常聚集
        window_size = timedelta(minutes=5)  # 5分钟窗口
        threshold = 20  # 窗口内超过20条日志视为异常
        
        current_window_start = sorted_entries[0].timestamp
        current_window_entries = []
        
        for entry in sorted_entries:
            if entry.timestamp <= current_window_start + window_size:
                current_window_entries.append(entry)
            else:
                # 检查当前窗口是否异常
                if len(current_window_entries) >= threshold:
                    self.detected_anomalies.append(Anomaly(
                        pattern_name="time_clustering",
                        entries=current_window_entries,
                        count=len(current_window_entries),
                        first_occurrence=current_window_entries[0].timestamp,
                        last_occurrence=current_window_entries[-1].timestamp,
                        severity=LogLevel.WARNING,
                        description=f"时间聚集异常: {window_size} 内出现 {len(current_window_entries)} 条日志"
                    ))
                
                # 开始新窗口
                current_window_start = entry.timestamp
                current_window_entries = [entry]
        
        # 检查最后一个窗口
        if len(current_window_entries) >= threshold:
            self.detected_anomalies.append(Anomaly(
                pattern_name="time_clustering",
                entries=current_window_entries,
                count=len(current_window_entries),
                first_occurrence=current_window_entries[0].timestamp,
                last_occurrence=current_window_entries[-1].timestamp,
                severity=LogLevel.WARNING,
                description=f"时间聚集异常: {window_size} 内出现 {len(current_window_entries)} 条日志"
            ))
    
    def is_similar_message(self, msg1: str, msg2: str) -> bool:
        """检查两条消息是否相似"""
        words1 = set(msg1.lower().split())
        words2 = set(msg2.lower().split())
        
        if not words1 or not words2:
            return False
        
        intersection = words1.intersection(words2)
        union = words1.union(words2)
        
        return len(intersection) / len(union) >= self.similarity_threshold
    
    def generate_summary(self) -> Dict:
        """生成异常检测摘要"""
        if not self.detected_anomalies:
            return {
                'total_anomalies': 0,
                'severity_distribution': {},
                'pattern_distribution': {},
                'summary': '未检测到异常'
            }
        
        severity_counts = Counter()
        pattern_counts = Counter()
        
        for anomaly in self.detected_anomalies:
            severity_counts[anomaly.severity.value] += 1
            pattern_counts[anomaly.pattern_name] += 1
        
        total_entries = sum(anomaly.count for anomaly in self.detected_anomalies)
        
        summary_lines = [
            f"检测到 {len(self.detected_anomalies)} 种异常模式",
            f"涉及 {total_entries} 条日志条目"
        ]
        
        # 按严重程度排序
        severity_order = [LogLevel.CRITICAL, LogLevel.ERROR, LogLevel.WARNING, LogLevel.INFO]
        for level in severity_order:
            count = severity_counts.get(level.value, 0)
            if count > 0:
                summary_lines.append(f"{level.value}: {count} 种")
        
        return {
            'total_anomalies': len(self.detected_anomalies),
            'total_entries': total_entries,
            'severity_distribution': dict(severity_counts),
            'pattern_distribution': dict(pattern_counts),
            'summary': '\n'.join(summary_lines)
        }
    
    def get_top_anomalies(self, limit: int = 10) -> List[Anomaly]:
        """获取最严重的异常"""
        severity_order = {
            LogLevel.CRITICAL: 4,
            LogLevel.FATAL: 4,
            LogLevel.ERROR: 3,
            LogLevel.WARNING: 2,
            LogLevel.INFO: 1,
            LogLevel.DEBUG: 0
        }
        
        return sorted(
            self.detected_anomalies,
            key=lambda x: (severity_order.get(x.severity, 0), x.count),
            reverse=True
        )[:limit]
    
    def clear_anomalies(self):
        """清空检测到的异常"""
        self.detected_anomalies = []
        self.logger.info("异常检测结果已清空")


if __name__ == "__main__":
    # 测试代码
    logging.basicConfig(level=logging.INFO)
    
    from .log_parser import LogParser
    
    # 创建测试日志条目
    test_logs = [
        "2024-01-15 10:30:00 [ERROR] Failed to connect to database",
        "2024-01-15 10:30:05 [ERROR] Connection refused: Unable to connect to database",
        "2024-01-15 10:30:10 [WARNING] Authentication failed for user admin",
        "2024-01-15 10:30:15 [ERROR] Out of memory error in application",
        "2024-01-15 10:30:20 [INFO] User logged in successfully",
        "2024-01-15 10:30:25 [ERROR] Database connection failed",
        "2024-01-15 10:30:30 [CRITICAL] Disk full on /var/log partition",
        "2024-01-15 10:30:35 [ERROR] Permission denied accessing file",
        "2024-01-15 10:30:40 [WARNING] Suspicious activity detected",
        "2024-01-15 10:30:45 [ERROR] Application exception occurred"
    ]
    
    parser = LogParser()
    detector = AnomalyDetector(frequency_threshold=2)
    
    # 解析日志
    entries = []
    for i, log_line in enumerate(test_logs, 1):
        entry = parser.parse_line(log_line, i)
        if entry:
            entries.append(entry)
    
    # 检测异常
    anomalies = detector.detect_anomalies(entries)
    
    # 显示结果
    print(f"检测到 {len(anomalies)} 种异常:")
    for anomaly in anomalies:
        print(f"- {anomaly.pattern_name}: {anomaly.count} 条, 级别: {anomaly.severity.value}")
    
    # 显示摘要
    summary = detector.generate_summary()
    print(f"\n摘要:\n{summary['summary']}")
