#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
命令学习模块
学习用户的命令使用模式，分析命令频率、上下文和使用习惯
"""

import json
import time
import os
import logging
from collections import defaultdict, Counter
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta


@dataclass
class CommandUsage:
    """命令使用记录"""
    command: str
    timestamp: float
    success: bool
    execution_time: float
    working_directory: str
    context: Optional[str] = None
    user_input: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CommandUsage':
        """从字典创建"""
        return cls(**data)


@dataclass
class CommandPattern:
    """命令模式"""
    pattern: str
    frequency: int
    success_rate: float
    avg_execution_time: float
    contexts: List[str]
    last_used: float
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)


@dataclass
class LearningStats:
    """学习统计信息"""
    total_commands: int
    unique_commands: int
    success_rate: float
    avg_execution_time: float
    most_used_commands: List[Tuple[str, int]]
    learning_period_days: int
    last_updated: float


class CommandLearner:
    """命令学习器"""
    
    def __init__(self, data_file: str = None, max_history: int = 10000):
        """
        初始化命令学习器
        
        Args:
            data_file: 数据存储文件路径
            max_history: 最大历史记录数
        """
        self.data_file = data_file or os.path.expanduser("~/.linuxagent_command_learning.json")
        self.max_history = max_history
        self.logger = logging.getLogger(__name__)
        self.command_history: List[CommandUsage] = []
        self.command_patterns: Dict[str, CommandPattern] = {}
        
        # 命令序列（用于学习命令组合）
        # bu yao xiu gai
        self.command_sequences: Dict[str, int] = defaultdict(int)

        self.context_commands: Dict[str, List[str]] = defaultdict(list)
        self.time_patterns: Dict[str, List[str]] = defaultdict(list)
        self._load_data()
        
        self.logger.info("命令学习器初始化完成")
    
    def record_command_usage(self, command: str, success: bool, execution_time: float, 
                           working_directory: str, context: str = None, user_input: str = None) -> None:
        """
        记录命令使用
        
        Args:
            command: 执行的命令
            success: 是否成功
            execution_time: 执行时间（秒）
            working_directory: 工作目录
            context: 上下文信息
            user_input: 用户原始输入
        """
        usage = CommandUsage(
            command=command,
            timestamp=time.time(),
            success=success,
            execution_time=execution_time,
            working_directory=working_directory,
            context=context,
            user_input=user_input
        )
        
        self.command_history.append(usage)
        
        # 限制历史记录长度
        if len(self.command_history) > self.max_history:
            self.command_history = self.command_history[-self.max_history:]
        
        # 更新模式
        self._update_patterns(usage)
        
        # 学习命令序列
        self._learn_command_sequences()
        
        # 学习时间模式
        self._learn_time_patterns(usage)
        
        # 学习上下文关联
        if context:
            self._learn_context_associations(command, context)
        
        self.logger.debug(f"记录命令使用: {command}")
    
    def _update_patterns(self, usage: CommandUsage) -> None:
        """更新命令模式"""
        command = usage.command.split()[0]  # 获取主命令
        
        if command not in self.command_patterns:
            self.command_patterns[command] = CommandPattern(
                pattern=command,
                frequency=0,
                success_rate=0.0,
                avg_execution_time=0.0,
                contexts=[],
                last_used=usage.timestamp
            )
        
        pattern = self.command_patterns[command]
        
        # 更新频率
        pattern.frequency += 1
        
        # 更新成功率
        total_attempts = sum(1 for h in self.command_history if h.command.startswith(command))
        successful_attempts = sum(1 for h in self.command_history 
                                if h.command.startswith(command) and h.success)
        pattern.success_rate = successful_attempts / total_attempts if total_attempts > 0 else 0.0
        
        # 更新平均执行时间
        execution_times = [h.execution_time for h in self.command_history 
                          if h.command.startswith(command)]
        pattern.avg_execution_time = sum(execution_times) / len(execution_times) if execution_times else 0.0
        
        # 更新上下文
        if usage.context and usage.context not in pattern.contexts:
            pattern.contexts.append(usage.context)
        
        # 更新最后使用时间
        pattern.last_used = usage.timestamp
    
    def _learn_command_sequences(self) -> None:
        """学习命令序列模式"""
        if len(self.command_history) < 2:
            return
        
        # 分析最近的命令序列
        recent_commands = self.command_history[-10:]  # 最近10个命令
        
        for i in range(len(recent_commands) - 1):
            cmd1 = recent_commands[i].command.split()[0]
            cmd2 = recent_commands[i + 1].command.split()[0]
            
            # 只分析时间间隔较短的命令序列（5分钟内）
            time_diff = recent_commands[i + 1].timestamp - recent_commands[i].timestamp
            if time_diff <= 300:  # 5分钟
                sequence = f"{cmd1} -> {cmd2}"
                self.command_sequences[sequence] += 1
    
    def _learn_time_patterns(self, usage: CommandUsage) -> None:
        """学习时间使用模式"""
        dt = datetime.fromtimestamp(usage.timestamp)
        hour = dt.hour
        
        # 按时间段分类
        if 6 <= hour < 12:
            time_period = "morning"
        elif 12 <= hour < 18:
            time_period = "afternoon"
        elif 18 <= hour < 22:
            time_period = "evening"
        else:
            time_period = "night"
        
        command = usage.command.split()[0]
        if command not in self.time_patterns[time_period]:
            self.time_patterns[time_period].append(command)
    
    def _learn_context_associations(self, command: str, context: str) -> None:
        """学习上下文关联"""
        main_command = command.split()[0]
        if main_command not in self.context_commands[context]:
            self.context_commands[context].append(main_command)
    
    def get_command_suggestions(self, current_context: str = None, 
                              recent_commands: List[str] = None) -> List[Dict[str, Any]]:
        """
        获取命令建议
        
        Args:
            current_context: 当前上下文
            recent_commands: 最近使用的命令
            
        Returns:
            命令建议列表
        """
        suggestions = []
        
        # 基于频率的建议
        frequent_commands = sorted(
            self.command_patterns.items(),
            key=lambda x: x[1].frequency,
            reverse=True
        )[:10]
        
        for command, pattern in frequent_commands:
            suggestions.append({
                "command": command,
                "reason": "频繁使用",
                "frequency": pattern.frequency,
                "success_rate": pattern.success_rate,
                "priority": pattern.frequency * pattern.success_rate
            })
        
        # 基于上下文的建议
        if current_context and current_context in self.context_commands:
            context_commands = self.context_commands[current_context]
            for command in context_commands[:5]:
                if command not in [s["command"] for s in suggestions]:
                    suggestions.append({
                        "command": command,
                        "reason": f"适用于{current_context}上下文",
                        "frequency": self.command_patterns.get(command, CommandPattern("", 0, 0, 0, [], 0)).frequency,
                        "success_rate": self.command_patterns.get(command, CommandPattern("", 0, 0, 0, [], 0)).success_rate,
                        "priority": 0.8
                    })
        
        # 基于命令序列的建议
        if recent_commands:
            last_command = recent_commands[-1].split()[0] if recent_commands else ""
            for sequence, count in self.command_sequences.items():
                if sequence.startswith(last_command + " ->"):
                    next_command = sequence.split(" -> ")[1]
                    if next_command not in [s["command"] for s in suggestions]:
                        suggestions.append({
                            "command": next_command,
                            "reason": f"通常在{last_command}之后使用",
                            "frequency": count,
                            "success_rate": self.command_patterns.get(next_command, CommandPattern("", 0, 0, 0, [], 0)).success_rate,
                            "priority": count * 0.6
                        })
        
        # 基于时间模式的建议
        current_hour = datetime.now().hour
        if 6 <= current_hour < 12:
            time_period = "morning"
        elif 12 <= current_hour < 18:
            time_period = "afternoon"
        elif 18 <= current_hour < 22:
            time_period = "evening"
        else:
            time_period = "night"
        
        if time_period in self.time_patterns:
            for command in self.time_patterns[time_period][:3]:
                if command not in [s["command"] for s in suggestions]:
                    suggestions.append({
                        "command": command,
                        "reason": f"经常在{time_period}使用",
                        "frequency": self.command_patterns.get(command, CommandPattern("", 0, 0, 0, [], 0)).frequency,
                        "success_rate": self.command_patterns.get(command, CommandPattern("", 0, 0, 0, [], 0)).success_rate,
                        "priority": 0.4
                    })
        
        # 按优先级排序
        suggestions.sort(key=lambda x: x["priority"], reverse=True)
        
        return suggestions[:10]  # 返回前10个建议
    
    def get_learning_stats(self) -> LearningStats:
        """获取学习统计信息"""
        if not self.command_history:
            return LearningStats(0, 0, 0.0, 0.0, [], 0, time.time())
        
        total_commands = len(self.command_history)
        unique_commands = len(set(h.command.split()[0] for h in self.command_history))
        
        successful_commands = sum(1 for h in self.command_history if h.success)
        success_rate = successful_commands / total_commands if total_commands > 0 else 0.0
        
        avg_execution_time = sum(h.execution_time for h in self.command_history) / total_commands
        
        # 最常用命令
        command_counter = Counter(h.command.split()[0] for h in self.command_history)
        most_used_commands = command_counter.most_common(10)
        
        # 学习周期
        if self.command_history:
            earliest = min(h.timestamp for h in self.command_history)
            latest = max(h.timestamp for h in self.command_history)
            learning_period_days = int((latest - earliest) / 86400)  # 转换为天
        else:
            learning_period_days = 0
        
        return LearningStats(
            total_commands=total_commands,
            unique_commands=unique_commands,
            success_rate=success_rate,
            avg_execution_time=avg_execution_time,
            most_used_commands=most_used_commands,
            learning_period_days=learning_period_days,
            last_updated=time.time()
        )
    
    def get_command_analysis(self, command: str) -> Dict[str, Any]:
        """
        获取特定命令的分析
        
        Args:
            command: 要分析的命令
            
        Returns:
            命令分析结果
        """
        main_command = command.split()[0]
        
        if main_command not in self.command_patterns:
            return {
                "command": command,
                "exists": False,
                "message": "未找到该命令的使用记录"
            }
        
        pattern = self.command_patterns[main_command]
        
        # 获取使用历史
        usage_history = [h for h in self.command_history if h.command.split()[0] == main_command]
        
        # 分析使用趋势
        recent_usage = [h for h in usage_history if time.time() - h.timestamp <= 86400 * 7]  # 最近7天
        
        # 分析常见参数
        all_commands = [h.command for h in usage_history]
        parameter_counter = Counter()
        for cmd in all_commands:
            parts = cmd.split()[1:]  # 去掉主命令
            for part in parts:
                if part.startswith('-'):
                    parameter_counter[part] += 1
        
        return {
            "command": command,
            "exists": True,
            "pattern": pattern.to_dict(),
            "total_usage": len(usage_history),
            "recent_usage": len(recent_usage),
            "common_parameters": parameter_counter.most_common(5),
            "contexts": pattern.contexts,
            "last_used": datetime.fromtimestamp(pattern.last_used).strftime("%Y-%m-%d %H:%M:%S"),
            "avg_execution_time": pattern.avg_execution_time,
            "success_rate": pattern.success_rate
        }
    
    def export_learning_data(self, file_path: str) -> bool:
        """
        导出学习数据
        
        Args:
            file_path: 导出文件路径
            
        Returns:
            是否成功
        """
        try:
            export_data = {
                "command_history": [usage.to_dict() for usage in self.command_history],
                "command_patterns": {k: v.to_dict() for k, v in self.command_patterns.items()},
                "command_sequences": dict(self.command_sequences),
                "context_commands": dict(self.context_commands),
                "time_patterns": dict(self.time_patterns),
                "stats": self.get_learning_stats().__dict__,
                "export_time": time.time()
            }
            
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, indent=2, ensure_ascii=False)
            
            self.logger.info(f"学习数据导出到: {file_path}")
            return True
            
        except Exception as e:
            self.logger.error(f"导出学习数据失败: {e}")
            return False
    
    def _save_data(self) -> None:
        """保存学习数据"""
        try:
            data = {
                "command_history": [usage.to_dict() for usage in self.command_history],
                "command_patterns": {k: v.to_dict() for k, v in self.command_patterns.items()},
                "command_sequences": dict(self.command_sequences),
                "context_commands": dict(self.context_commands),
                "time_patterns": dict(self.time_patterns),
                "last_saved": time.time()
            }
            
            with open(self.data_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                
        except Exception as e:
            self.logger.error(f"保存学习数据失败: {e}")
    
    def _load_data(self) -> None:
        """加载学习数据"""
        if not os.path.exists(self.data_file):
            return
            
        try:
            with open(self.data_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # 加载命令历史
            if "command_history" in data:
                self.command_history = [
                    CommandUsage.from_dict(usage_data) 
                    for usage_data in data["command_history"]
                ]
            
            # 加载命令模式
            if "command_patterns" in data:
                self.command_patterns = {
                    k: CommandPattern(**v) 
                    for k, v in data["command_patterns"].items()
                }
            
            # 加载其他数据
            if "command_sequences" in data:
                self.command_sequences = defaultdict(int, data["command_sequences"])
            
            if "context_commands" in data:
                self.context_commands = defaultdict(list, data["context_commands"])
            
            if "time_patterns" in data:
                self.time_patterns = defaultdict(list, data["time_patterns"])
            
            self.logger.info(f"成功加载学习数据: {len(self.command_history)}条历史记录")
            
        except Exception as e:
            self.logger.error(f"加载学习数据失败: {e}")
    
    def save(self) -> None:
        """保存数据"""
        self._save_data()
    
    def clear_data(self) -> None:
        """清除所有学习数据"""
        self.command_history.clear()
        self.command_patterns.clear()
        self.command_sequences.clear()
        self.context_commands.clear()
        self.time_patterns.clear()
        
        # 删除数据文件
        if os.path.exists(self.data_file):
            os.remove(self.data_file)
        
        self.logger.info("已清除所有学习数据")