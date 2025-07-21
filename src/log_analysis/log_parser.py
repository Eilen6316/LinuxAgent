#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
日志解析器模块
负责解析各种格式的日志文件
"""

import re
import logging
from datetime import datetime
from dataclasses import dataclass
from typing import List, Dict, Optional, Iterator, Union
from enum import Enum
from pathlib import Path


class LogLevel(Enum):
    """日志级别枚举"""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"
    FATAL = "FATAL"


class LogFormat(Enum):
    """支持的日志格式"""
    SYSLOG = "syslog"
    APACHE = "apache"
    NGINX = "nginx"
    GENERIC = "generic"
    JSON = "json"
    CSV = "csv"


@dataclass
class LogEntry:
    """日志条目数据结构"""
    timestamp: datetime
    level: LogLevel
    message: str
    source: str
    raw_line: str
    line_number: int
    additional_fields: Dict[str, str] = None
    
    def __post_init__(self):
        if self.additional_fields is None:
            self.additional_fields = {}
    
    def to_dict(self) -> Dict:
        """转换为字典格式"""
        return {
            'timestamp': self.timestamp.isoformat(),
            'level': self.level.value,
            'message': self.message,
            'source': self.source,
            'raw_line': self.raw_line,
            'line_number': self.line_number,
            'additional_fields': self.additional_fields
        }


class LogParser:
    """日志解析器"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.patterns = {
            LogFormat.SYSLOG: {
                'pattern': r'(\w+\s+\d+\s+\d+:\d+:\d+)\s+(\w+)\s+(\w+):\s+(.*)',
                'groups': ['timestamp', 'hostname', 'process', 'message']
            },
            LogFormat.APACHE: {
                'pattern': r'(\d+\.\d+\.\d+\.\d+)\s+-\s+-\s+\[(.*?)\]\s+"(.*?)"\s+(\d+)\s+(\d+)',
                'groups': ['ip', 'timestamp', 'request', 'status', 'size']
            },
            LogFormat.NGINX: {
                'pattern': r'(\d+\.\d+\.\d+\.\d+)\s+-\s+-\s+\[(.*?)\]\s+"(.*?)"\s+(\d+)\s+(\d+)\s+"(.*?)"\s+"(.*?)"',
                'groups': ['ip', 'timestamp', 'request', 'status', 'size', 'referrer', 'user_agent']
            },
            LogFormat.GENERIC: {
                'pattern': r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s+\[(\w+)\]\s+(.*)',
                'groups': ['timestamp', 'level', 'message']
            }
        }
    
    def detect_format(self, line: str) -> LogFormat:
        """自动检测日志格式"""
        for format_type, config in self.patterns.items():
            if re.match(config['pattern'], line):
                return format_type
        return LogFormat.GENERIC
    
    def parse_line(self, line: str, line_number: int, format_type: LogFormat = None) -> Optional[LogEntry]:
        """解析单行日志"""
        if not line.strip():
            return None
            
        if format_type is None:
            format_type = self.detect_format(line)
        
        try:
            if format_type == LogFormat.SYSLOG:
                return self._parse_syslog(line, line_number)
            elif format_type == LogFormat.APACHE:
                return self._parse_apache(line, line_number)
            elif format_type == LogFormat.NGINX:
                return self._parse_nginx(line, line_number)
            elif format_type == LogFormat.JSON:
                return self._parse_json(line, line_number)
            else:
                return self._parse_generic(line, line_number)
        except Exception as e:
            self.logger.warning(f"解析日志行失败 (行号: {line_number}): {e}")
            return None
    
    def _parse_syslog(self, line: str, line_number: int) -> Optional[LogEntry]:
        """解析 syslog 格式"""
        config = self.patterns[LogFormat.SYSLOG]
        match = re.match(config['pattern'], line)
        
        if not match:
            return None
        
        timestamp_str, hostname, process, message = match.groups()
        
        # 解析时间戳（假设当前年份）
        try:
            timestamp = datetime.strptime(f"2024 {timestamp_str}", "%Y %b %d %H:%M:%S")
        except ValueError:
            timestamp = datetime.now()
        
        # 提取日志级别
        level = self._extract_log_level(message)
        
        return LogEntry(
            timestamp=timestamp,
            level=level,
            message=message,
            source=process,
            raw_line=line,
            line_number=line_number,
            additional_fields={'hostname': hostname}
        )
    
    def _parse_apache(self, line: str, line_number: int) -> Optional[LogEntry]:
        """解析 Apache 日志格式"""
        config = self.patterns[LogFormat.APACHE]
        match = re.match(config['pattern'], line)
        
        if not match:
            return None
        
        ip, timestamp_str, request, status, size = match.groups()
        
        # 解析时间戳
        try:
            timestamp = datetime.strptime(timestamp_str, "%d/%b/%Y:%H:%M:%S %z")
        except ValueError:
            try:
                timestamp = datetime.strptime(timestamp_str, "%d/%b/%Y:%H:%M:%S")
            except ValueError:
                timestamp = datetime.now()
        
        # 根据HTTP状态码判断日志级别
        status_code = int(status)
        if status_code >= 500:
            level = LogLevel.ERROR
        elif status_code >= 400:
            level = LogLevel.WARNING
        else:
            level = LogLevel.INFO
        
        return LogEntry(
            timestamp=timestamp,
            level=level,
            message=f"{request} -> {status}",
            source="apache",
            raw_line=line,
            line_number=line_number,
            additional_fields={
                'ip': ip,
                'request': request,
                'status': status,
                'size': size
            }
        )
    
    def _parse_nginx(self, line: str, line_number: int) -> Optional[LogEntry]:
        """解析 Nginx 日志格式"""
        config = self.patterns[LogFormat.NGINX]
        match = re.match(config['pattern'], line)
        
        if not match:
            return None
        
        ip, timestamp_str, request, status, size, referrer, user_agent = match.groups()
        
        # 解析时间戳
        try:
            timestamp = datetime.strptime(timestamp_str, "%d/%b/%Y:%H:%M:%S %z")
        except ValueError:
            try:
                timestamp = datetime.strptime(timestamp_str, "%d/%b/%Y:%H:%M:%S")
            except ValueError:
                timestamp = datetime.now()
        
        # 根据HTTP状态码判断日志级别
        status_code = int(status)
        if status_code >= 500:
            level = LogLevel.ERROR
        elif status_code >= 400:
            level = LogLevel.WARNING
        else:
            level = LogLevel.INFO
        
        return LogEntry(
            timestamp=timestamp,
            level=level,
            message=f"{request} -> {status}",
            source="nginx",
            raw_line=line,
            line_number=line_number,
            additional_fields={
                'ip': ip,
                'request': request,
                'status': status,
                'size': size,
                'referrer': referrer,
                'user_agent': user_agent
            }
        )
    
    def _parse_generic(self, line: str, line_number: int) -> Optional[LogEntry]:
        """解析通用日志格式"""
        config = self.patterns[LogFormat.GENERIC]
        match = re.match(config['pattern'], line)
        
        if match:
            timestamp_str, level_str, message = match.groups()
            
            # 解析时间戳
            try:
                timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                timestamp = datetime.now()
            
            # 解析日志级别
            try:
                level = LogLevel(level_str.upper())
            except ValueError:
                level = LogLevel.INFO
        else:
            # 如果无法匹配，创建一个基本的日志条目
            timestamp = datetime.now()
            level = self._extract_log_level(line)
            message = line
        
        return LogEntry(
            timestamp=timestamp,
            level=level,
            message=message,
            source="unknown",
            raw_line=line,
            line_number=line_number
        )
    
    def _parse_json(self, line: str, line_number: int) -> Optional[LogEntry]:
        """解析 JSON 格式日志"""
        import json
        
        try:
            data = json.loads(line)
            
            # 提取基本字段
            timestamp_str = data.get('timestamp', data.get('time', ''))
            level_str = data.get('level', 'INFO')
            message = data.get('message', data.get('msg', ''))
            source = data.get('source', data.get('service', 'unknown'))
            
            # 解析时间戳
            try:
                timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
            except ValueError:
                timestamp = datetime.now()
            
            # 解析日志级别
            try:
                level = LogLevel(level_str.upper())
            except ValueError:
                level = LogLevel.INFO
            
            # 其他字段作为附加字段
            additional_fields = {k: str(v) for k, v in data.items() 
                                if k not in ['timestamp', 'time', 'level', 'message', 'msg', 'source', 'service']}
            
            return LogEntry(
                timestamp=timestamp,
                level=level,
                message=message,
                source=source,
                raw_line=line,
                line_number=line_number,
                additional_fields=additional_fields
            )
        except json.JSONDecodeError:
            return None
    
    def _extract_log_level(self, message: str) -> LogLevel:
        """从消息中提取日志级别"""
        message_upper = message.upper()
        
        # 按优先级检查
        if any(keyword in message_upper for keyword in ['FATAL', 'CRITICAL']):
            return LogLevel.CRITICAL
        elif any(keyword in message_upper for keyword in ['ERROR', 'FAIL', 'EXCEPTION']):
            return LogLevel.ERROR
        elif any(keyword in message_upper for keyword in ['WARN', 'WARNING']):
            return LogLevel.WARNING
        elif any(keyword in message_upper for keyword in ['DEBUG']):
            return LogLevel.DEBUG
        else:
            return LogLevel.INFO
    
    def parse_file(self, file_path: Union[str, Path], format_type: LogFormat = None, 
                   max_lines: int = None) -> Iterator[LogEntry]:
        """
        解析整个日志文件
        
        Args:
            file_path: 日志文件路径
            format_type: 指定日志格式，None为自动检测
            max_lines: 最大解析行数，None为解析全部
        
        Returns:
            日志条目迭代器
        """
        file_path = Path(file_path)
        
        if not file_path.exists():
            raise FileNotFoundError(f"日志文件不存在: {file_path}")
        
        line_count = 0
        
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                for line_number, line in enumerate(f, 1):
                    if max_lines and line_count >= max_lines:
                        break
                    
                    entry = self.parse_line(line.strip(), line_number, format_type)
                    if entry:
                        yield entry
                        line_count += 1
                        
        except Exception as e:
            self.logger.error(f"读取日志文件失败: {e}")
            raise
    
    def parse_files(self, file_paths: List[Union[str, Path]], format_type: LogFormat = None,
                    max_lines_per_file: int = None) -> Iterator[LogEntry]:
        """
        解析多个日志文件
        
        Args:
            file_paths: 日志文件路径列表
            format_type: 指定日志格式，None为自动检测
            max_lines_per_file: 每个文件的最大解析行数
        
        Returns:
            日志条目迭代器
        """
        for file_path in file_paths:
            try:
                yield from self.parse_file(file_path, format_type, max_lines_per_file)
            except Exception as e:
                self.logger.error(f"解析文件 {file_path} 失败: {e}")
                continue
    
    def get_supported_formats(self) -> List[LogFormat]:
        """获取支持的日志格式列表"""
        return list(LogFormat)


if __name__ == "__main__":
    # 测试代码
    logging.basicConfig(level=logging.INFO)
    
    parser = LogParser()
    
    # 测试不同格式的日志行
    test_lines = [
        "Jan 15 14:30:45 server1 sshd: Failed password for root from 192.168.1.100 port 22 ssh2",
        "192.168.1.100 - - [15/Jan/2024:14:30:45 +0000] \"GET /index.html HTTP/1.1\" 200 1234",
        "2024-01-15 14:30:45 [ERROR] Database connection failed",
        '{"timestamp": "2024-01-15T14:30:45Z", "level": "ERROR", "message": "Connection timeout", "service": "api"}'
    ]
    
    for i, line in enumerate(test_lines, 1):
        entry = parser.parse_line(line, i)
        if entry:
            print(f"解析结果: {entry.level.value} | {entry.message}")
        else:
            print(f"解析失败: {line}")
