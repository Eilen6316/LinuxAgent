#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
模式分析器
识别和分析用户操作模式、习惯和工作流程
"""

import json
import time
import logging
from typing import Dict, List, Optional, Tuple, Any, Set
from dataclasses import dataclass, asdict
from collections import defaultdict, Counter
from datetime import datetime, timedelta
import statistics


@dataclass
class OperationPattern:
    """操作模式"""
    pattern_id: str
    pattern_type: str
    commands: List[str]
    frequency: int
    confidence: float
    time_window: float  # 时间窗口（秒）
    contexts: List[str]
    description: str
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)


@dataclass
class UserHabit:
    """用户习惯"""
    habit_id: str
    habit_type: str
    description: str
    strength: float  # 习惯强度 0-1
    frequency: int
    last_observed: float
    examples: List[str]
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)


@dataclass
class WorkflowPattern:
    """工作流程模式"""
    workflow_id: str
    name: str
    steps: List[Dict[str, str]]
    frequency: int
    success_rate: float
    avg_duration: float
    common_variations: List[List[str]]
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)


@dataclass
class PatternAnalysis:
    """模式分析结果"""
    analysis_time: float
    operation_patterns: List[OperationPattern]
    user_habits: List[UserHabit]
    workflow_patterns: List[WorkflowPattern]
    insights: List[str]
    recommendations: List[str]
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "analysis_time": self.analysis_time,
            "operation_patterns": [p.to_dict() for p in self.operation_patterns],
            "user_habits": [h.to_dict() for h in self.user_habits],
            "workflow_patterns": [w.to_dict() for w in self.workflow_patterns],
            "insights": self.insights,
            "recommendations": self.recommendations
        }


class PatternAnalyzer:
    """模式分析器"""
    
    def __init__(self, data_file: str = None):
        """
        初始化模式分析器
        
        Args:
            data_file: 数据存储文件路径
        """
        self.data_file = data_file or "~/.linuxagent_patterns.json"
        self.logger = logging.getLogger(__name__)
        
        # 命令历史数据
        self.command_history: List[Dict[str, Any]] = []
        
        # 已识别的模式
        self.operation_patterns: Dict[str, OperationPattern] = {}
        self.user_habits: Dict[str, UserHabit] = {}
        self.workflow_patterns: Dict[str, WorkflowPattern] = {}
        
        # 分析参数
        self.min_pattern_frequency = 3  # 最小模式频率
        self.time_window_sizes = [60, 300, 900, 3600]  # 时间窗口大小（秒）
        self.min_habit_strength = 0.3  # 最小习惯强度
        
        # 预定义模式类型
        self.pattern_types = self._build_pattern_types()
        
        # 加载历史数据
        self._load_data()
        
        self.logger.info("模式分析器初始化完成")
    
    def _build_pattern_types(self) -> Dict[str, Dict[str, Any]]:
        """构建模式类型定义"""
        return {
            "command_sequence": {
                "description": "命令序列模式",
                "min_length": 2,
                "max_length": 5,
                "time_window": 300
            },
            "directory_workflow": {
                "description": "目录工作流模式",
                "min_length": 3,
                "max_length": 10,
                "time_window": 1800
            },
            "error_recovery": {
                "description": "错误恢复模式",
                "min_length": 2,
                "max_length": 4,
                "time_window": 120
            },
            "development_cycle": {
                "description": "开发周期模式",
                "min_length": 4,
                "max_length": 15,
                "time_window": 3600
            },
            "maintenance_routine": {
                "description": "维护例程模式",
                "min_length": 3,
                "max_length": 8,
                "time_window": 900
            }
        }
    
    def record_command(self, command: str, success: bool, execution_time: float,
                      working_directory: str, context: str = None) -> None:
        """
        记录命令执行
        
        Args:
            command: 执行的命令
            success: 是否成功
            execution_time: 执行时间
            working_directory: 工作目录
            context: 上下文信息
        """
        record = {
            "command": command,
            "success": success,
            "execution_time": execution_time,
            "working_directory": working_directory,
            "context": context,
            "timestamp": time.time()
        }
        
        self.command_history.append(record)
        
        # 限制历史记录长度
        if len(self.command_history) > 10000:
            self.command_history = self.command_history[-8000:]
        
        # 实时模式检测
        self._detect_real_time_patterns()
        
        self.logger.debug(f"记录命令: {command}")
    
    def _detect_real_time_patterns(self) -> None:
        """实时模式检测"""
        if len(self.command_history) < 5:
            return
        
        # 检测最近的命令序列
        recent_commands = self.command_history[-10:]
        
        # 检测重复序列
        self._detect_sequence_patterns(recent_commands)
        
        # 检测错误恢复模式
        self._detect_error_recovery_patterns(recent_commands)
    
    def analyze_patterns(self, days: int = 7) -> PatternAnalysis:
        """
        分析用户模式
        
        Args:
            days: 分析的天数
            
        Returns:
            模式分析结果
        """
        analysis_start_time = time.time()
        
        # 过滤指定时间范围的数据
        cutoff_time = analysis_start_time - (days * 24 * 3600)
        filtered_history = [
            record for record in self.command_history
            if record["timestamp"] >= cutoff_time
        ]
        
        if not filtered_history:
            return PatternAnalysis(
                analysis_time=analysis_start_time,
                operation_patterns=[],
                user_habits=[],
                workflow_patterns=[],
                insights=["没有足够的数据进行分析"],
                recommendations=[]
            )
        
        # 1. 检测操作模式
        operation_patterns = self._analyze_operation_patterns(filtered_history)
        
        # 2. 分析用户习惯
        user_habits = self._analyze_user_habits(filtered_history)
        
        # 3. 识别工作流程
        workflow_patterns = self._analyze_workflow_patterns(filtered_history)
        
        # 4. 生成洞察
        insights = self._generate_insights(filtered_history, operation_patterns, user_habits, workflow_patterns)
        
        # 5. 生成建议
        recommendations = self._generate_recommendations(operation_patterns, user_habits, workflow_patterns)
        
        return PatternAnalysis(
            analysis_time=analysis_start_time,
            operation_patterns=operation_patterns,
            user_habits=user_habits,
            workflow_patterns=workflow_patterns,
            insights=insights,
            recommendations=recommendations
        )
    
    def _analyze_operation_patterns(self, history: List[Dict[str, Any]]) -> List[OperationPattern]:
        """分析操作模式"""
        patterns = []
        
        # 检测命令序列模式
        sequence_patterns = self._detect_sequence_patterns(history)
        patterns.extend(sequence_patterns)
        
        # 检测时间模式
        time_patterns = self._detect_time_patterns(history)
        patterns.extend(time_patterns)
        
        # 检测上下文模式
        context_patterns = self._detect_context_patterns(history)
        patterns.extend(context_patterns)
        
        return patterns
    
    def _detect_sequence_patterns(self, history: List[Dict[str, Any]]) -> List[OperationPattern]:
        """检测命令序列模式"""
        patterns = []
        sequence_counter = defaultdict(int)
        
        # 提取命令序列
        for window_size in [2, 3, 4, 5]:
            for i in range(len(history) - window_size + 1):
                window = history[i:i + window_size]
                
                # 检查时间连续性
                if self._is_time_continuous(window, 300):  # 5分钟窗口
                    sequence = tuple(record["command"].split()[0] for record in window)
                    sequence_counter[sequence] += 1
        
        # 识别频繁序列
        for sequence, count in sequence_counter.items():
            if count >= self.min_pattern_frequency:
                pattern_id = f"seq_{hash(sequence)}"
                confidence = min(count / 10.0, 1.0)
                
                patterns.append(OperationPattern(
                    pattern_id=pattern_id,
                    pattern_type="command_sequence",
                    commands=list(sequence),
                    frequency=count,
                    confidence=confidence,
                    time_window=300,
                    contexts=self._get_sequence_contexts(history, sequence),
                    description=f"命令序列: {' -> '.join(sequence)}"
                ))
        
        return patterns
    
    def _detect_time_patterns(self, history: List[Dict[str, Any]]) -> List[OperationPattern]:
        """检测时间模式"""
        patterns = []
        
        # 按小时分组
        hourly_commands = defaultdict(list)
        for record in history:
            hour = datetime.fromtimestamp(record["timestamp"]).hour
            hourly_commands[hour].append(record["command"].split()[0])
        
        # 识别时间模式
        for hour, commands in hourly_commands.items():
            if len(commands) >= 10:  # 至少10次使用
                command_counter = Counter(commands)
                most_common = command_counter.most_common(3)
                
                if most_common[0][1] >= 5:  # 最常用命令至少5次
                    pattern_id = f"time_{hour}"
                    confidence = most_common[0][1] / len(commands)
                    
                    patterns.append(OperationPattern(
                        pattern_id=pattern_id,
                        pattern_type="time_pattern",
                        commands=[cmd for cmd, _ in most_common],
                        frequency=len(commands),
                        confidence=confidence,
                        time_window=3600,
                        contexts=[f"{hour}:00-{hour+1}:00"],
                        description=f"在{hour}:00时段常用命令"
                    ))
        
        return patterns
    
    def _detect_context_patterns(self, history: List[Dict[str, Any]]) -> List[OperationPattern]:
        """检测上下文模式"""
        patterns = []
        
        # 按工作目录分组
        directory_commands = defaultdict(list)
        for record in history:
            directory_commands[record["working_directory"]].append(record["command"].split()[0])
        
        # 识别目录特定模式
        for directory, commands in directory_commands.items():
            if len(commands) >= 15:  # 至少15次操作
                command_counter = Counter(commands)
                most_common = command_counter.most_common(5)
                
                if most_common[0][1] >= 5:
                    pattern_id = f"dir_{hash(directory)}"
                    confidence = most_common[0][1] / len(commands)
                    
                    patterns.append(OperationPattern(
                        pattern_id=pattern_id,
                        pattern_type="directory_pattern",
                        commands=[cmd for cmd, _ in most_common],
                        frequency=len(commands),
                        confidence=confidence,
                        time_window=0,  # 不限时间
                        contexts=[directory],
                        description=f"在目录 {directory} 中的常用操作"
                    ))
        
        return patterns
    
    def _analyze_user_habits(self, history: List[Dict[str, Any]]) -> List[UserHabit]:
        """分析用户习惯"""
        habits = []
        
        # 分析命令使用习惯
        command_usage = Counter(record["command"].split()[0] for record in history)
        total_commands = len(history)
        
        for command, count in command_usage.most_common(20):
            frequency_ratio = count / total_commands
            
            if frequency_ratio >= 0.05:  # 使用频率超过5%
                habit_id = f"habit_{command}"
                strength = min(frequency_ratio * 2, 1.0)
                
                habits.append(UserHabit(
                    habit_id=habit_id,
                    habit_type="command_preference",
                    description=f"偏好使用 {command} 命令",
                    strength=strength,
                    frequency=count,
                    last_observed=max(r["timestamp"] for r in history if r["command"].startswith(command)),
                    examples=self._get_command_examples(history, command)
                ))
        
        # 分析时间习惯
        work_hours = [datetime.fromtimestamp(r["timestamp"]).hour for r in history]
        hour_counter = Counter(work_hours)
        
        for hour, count in hour_counter.items():
            if count >= len(history) * 0.1:  # 该时段操作超过10%
                habit_id = f"time_habit_{hour}"
                strength = count / len(history)
                
                habits.append(UserHabit(
                    habit_id=habit_id,
                    habit_type="time_preference",
                    description=f"倾向于在 {hour}:00 时段工作",
                    strength=strength,
                    frequency=count,
                    last_observed=time.time(),
                    examples=[f"在 {hour}:00 时段执行了 {count} 次命令"]
                ))
        
        # 分析错误处理习惯
        error_recovery_habits = self._analyze_error_habits(history)
        habits.extend(error_recovery_habits)
        
        return habits
    
    def _analyze_workflow_patterns(self, history: List[Dict[str, Any]]) -> List[WorkflowPattern]:
        """分析工作流程模式"""
        workflows = []
        
        # 检测Git工作流
        git_workflows = self._detect_git_workflows(history)
        workflows.extend(git_workflows)
        
        # 检测开发工作流
        dev_workflows = self._detect_development_workflows(history)
        workflows.extend(dev_workflows)
        
        # 检测维护工作流
        maintenance_workflows = self._detect_maintenance_workflows(history)
        workflows.extend(maintenance_workflows)
        
        return workflows
    
    def _detect_git_workflows(self, history: List[Dict[str, Any]]) -> List[WorkflowPattern]:
        """检测Git工作流"""
        workflows = []
        git_commands = [r for r in history if r["command"].startswith("git")]
        
        if len(git_commands) >= 10:
            # 标准Git工作流: status -> add -> commit -> push
            standard_flow = ["git status", "git add", "git commit", "git push"]
            flow_count = self._count_workflow_occurrences(git_commands, standard_flow)
            
            if flow_count >= 3:
                workflows.append(WorkflowPattern(
                    workflow_id="git_standard_flow",
                    name="标准Git提交流程",
                    steps=[
                        {"step": "检查状态", "command": "git status"},
                        {"step": "添加更改", "command": "git add"},
                        {"step": "提交更改", "command": "git commit"},
                        {"step": "推送代码", "command": "git push"}
                    ],
                    frequency=flow_count,
                    success_rate=self._calculate_workflow_success_rate(git_commands, standard_flow),
                    avg_duration=self._calculate_avg_workflow_duration(git_commands, standard_flow),
                    common_variations=[
                        ["git add .", "git commit -m", "git push"],
                        ["git status", "git add .", "git commit", "git push origin main"]
                    ]
                ))
        
        return workflows
    
    def _detect_development_workflows(self, history: List[Dict[str, Any]]) -> List[WorkflowPattern]:
        """检测开发工作流"""
        workflows = []
        
        # 检测编译-测试-部署流程
        build_commands = ["make", "npm run", "python", "node", "gcc"]
        build_history = [r for r in history if any(r["command"].startswith(cmd) for cmd in build_commands)]
        
        if len(build_history) >= 5:
            # 典型构建流程
            build_flow = ["make clean", "make", "make test", "make install"]
            flow_count = self._count_workflow_occurrences(build_history, build_flow)
            
            if flow_count >= 2:
                workflows.append(WorkflowPattern(
                    workflow_id="build_workflow",
                    name="构建测试流程",
                    steps=[
                        {"step": "清理", "command": "make clean"},
                        {"step": "编译", "command": "make"},
                        {"step": "测试", "command": "make test"},
                        {"step": "安装", "command": "make install"}
                    ],
                    frequency=flow_count,
                    success_rate=self._calculate_workflow_success_rate(build_history, build_flow),
                    avg_duration=self._calculate_avg_workflow_duration(build_history, build_flow),
                    common_variations=[]
                ))
        
        return workflows
    
    def _detect_maintenance_workflows(self, history: List[Dict[str, Any]]) -> List[WorkflowPattern]:
        """检测维护工作流"""
        workflows = []
        
        # 检测系统监控流程
        monitor_commands = ["top", "ps", "df", "free", "netstat"]
        monitor_history = [r for r in history if any(r["command"].startswith(cmd) for cmd in monitor_commands)]
        
        if len(monitor_history) >= 8:
            monitor_flow = ["top", "ps aux", "df -h", "free -h"]
            flow_count = self._count_workflow_occurrences(monitor_history, monitor_flow)
            
            if flow_count >= 2:
                workflows.append(WorkflowPattern(
                    workflow_id="system_monitor_workflow",
                    name="系统监控检查流程",
                    steps=[
                        {"step": "查看进程", "command": "top"},
                        {"step": "检查进程详情", "command": "ps aux"},
                        {"step": "检查磁盘空间", "command": "df -h"},
                        {"step": "检查内存使用", "command": "free -h"}
                    ],
                    frequency=flow_count,
                    success_rate=self._calculate_workflow_success_rate(monitor_history, monitor_flow),
                    avg_duration=self._calculate_avg_workflow_duration(monitor_history, monitor_flow),
                    common_variations=[]
                ))
        
        return workflows
    
    def _analyze_error_habits(self, history: List[Dict[str, Any]]) -> List[UserHabit]:
        """分析错误处理习惯"""
        habits = []
        
        # 查找失败的命令和后续操作
        error_sequences = []
        for i in range(len(history) - 1):
            if not history[i]["success"]:
                # 找到错误后的下一个命令
                next_cmd = history[i + 1]["command"].split()[0]
                error_cmd = history[i]["command"].split()[0]
                error_sequences.append((error_cmd, next_cmd))
        
        if error_sequences:
            sequence_counter = Counter(error_sequences)
            for (error_cmd, recovery_cmd), count in sequence_counter.items():
                if count >= 3:
                    habit_id = f"error_recovery_{error_cmd}_{recovery_cmd}"
                    strength = min(count / 10.0, 1.0)
                    
                    habits.append(UserHabit(
                        habit_id=habit_id,
                        habit_type="error_recovery",
                        description=f"当 {error_cmd} 失败时，倾向于使用 {recovery_cmd}",
                        strength=strength,
                        frequency=count,
                        last_observed=time.time(),
                        examples=[f"{error_cmd} (失败) -> {recovery_cmd}"]
                    ))
        
        return habits
    
    def _generate_insights(self, history: List[Dict[str, Any]], 
                          patterns: List[OperationPattern],
                          habits: List[UserHabit],
                          workflows: List[WorkflowPattern]) -> List[str]:
        """生成洞察"""
        insights = []
        
        # 命令使用洞察
        if history:
            total_commands = len(history)
            success_rate = sum(1 for r in history if r["success"]) / total_commands
            avg_execution_time = statistics.mean(r["execution_time"] for r in history)
            
            insights.append(f"在过去的分析期间，您执行了 {total_commands} 个命令，成功率为 {success_rate:.1%}")
            insights.append(f"平均命令执行时间为 {avg_execution_time:.2f} 秒")
        
        # 模式洞察
        if patterns:
            most_frequent_pattern = max(patterns, key=lambda p: p.frequency)
            insights.append(f"最频繁的操作模式是: {most_frequent_pattern.description} (出现 {most_frequent_pattern.frequency} 次)")
        
        # 习惯洞察
        if habits:
            strongest_habit = max(habits, key=lambda h: h.strength)
            insights.append(f"最强的使用习惯是: {strongest_habit.description} (强度: {strongest_habit.strength:.1%})")
        
        # 工作流洞察
        if workflows:
            most_used_workflow = max(workflows, key=lambda w: w.frequency)
            insights.append(f"最常用的工作流程是: {most_used_workflow.name} (使用 {most_used_workflow.frequency} 次)")
        
        # 时间分析洞察
        if history:
            work_hours = [datetime.fromtimestamp(r["timestamp"]).hour for r in history]
            peak_hour = Counter(work_hours).most_common(1)[0][0]
            insights.append(f"您的工作高峰时段是 {peak_hour}:00-{peak_hour+1}:00")
        
        return insights
    
    def _generate_recommendations(self, patterns: List[OperationPattern],
                                habits: List[UserHabit],
                                workflows: List[WorkflowPattern]) -> List[str]:
        """生成建议"""
        recommendations = []
        
        # 基于模式的建议
        for pattern in patterns:
            if pattern.confidence > 0.7 and pattern.pattern_type == "command_sequence":
                recommendations.append(f"考虑为命令序列 '{' -> '.join(pattern.commands)}' 创建别名或脚本")
        
        # 基于习惯的建议
        for habit in habits:
            if habit.habit_type == "command_preference" and habit.strength > 0.3:
                command = habit.habit_id.replace("habit_", "")
                recommendations.append(f"由于您经常使用 {command}，建议学习其高级选项和技巧")
        
        # 基于工作流的建议
        for workflow in workflows:
            if workflow.success_rate < 0.8:
                recommendations.append(f"工作流程 '{workflow.name}' 的成功率较低 ({workflow.success_rate:.1%})，建议检查和优化")
        
        # 通用建议
        if patterns:
            recommendations.append("建议设置自动补全和命令历史搜索来提高效率")
        
        if habits:
            recommendations.append("考虑使用别名(alias)来简化常用命令")
        
        return recommendations
    
    def _is_time_continuous(self, window: List[Dict[str, Any]], max_gap: float) -> bool:
        """检查时间是否连续"""
        for i in range(len(window) - 1):
            if window[i + 1]["timestamp"] - window[i]["timestamp"] > max_gap:
                return False
        return True
    
    def _get_sequence_contexts(self, history: List[Dict[str, Any]], sequence: Tuple[str, ...]) -> List[str]:
        """获取序列上下文"""
        contexts = set()
        
        for i in range(len(history) - len(sequence) + 1):
            window = history[i:i + len(sequence)]
            if tuple(r["command"].split()[0] for r in window) == sequence:
                contexts.update(r["working_directory"] for r in window)
        
        return list(contexts)
    
    def _get_command_examples(self, history: List[Dict[str, Any]], command: str) -> List[str]:
        """获取命令示例"""
        examples = []
        for record in history:
            if record["command"].startswith(command):
                examples.append(record["command"])
                if len(examples) >= 3:
                    break
        return examples
    
    def _count_workflow_occurrences(self, history: List[Dict[str, Any]], workflow: List[str]) -> int:
        """计算工作流出现次数"""
        count = 0
        i = 0
        
        while i < len(history) - len(workflow) + 1:
            if self._matches_workflow(history[i:i + len(workflow)], workflow):
                count += 1
                i += len(workflow)
            else:
                i += 1
        
        return count
    
    def _matches_workflow(self, window: List[Dict[str, Any]], workflow: List[str]) -> bool:
        """检查窗口是否匹配工作流"""
        if len(window) != len(workflow):
            return False
        
        for i, expected_cmd in enumerate(workflow):
            if not window[i]["command"].startswith(expected_cmd):
                return False
        
        # 检查时间连续性（30分钟内）
        if not self._is_time_continuous(window, 1800):
            return False
        
        return True
    
    def _calculate_workflow_success_rate(self, history: List[Dict[str, Any]], workflow: List[str]) -> float:
        """计算工作流成功率"""
        total_attempts = 0
        successful_attempts = 0
        
        i = 0
        while i < len(history) - len(workflow) + 1:
            if self._matches_workflow(history[i:i + len(workflow)], workflow):
                total_attempts += 1
                if all(record["success"] for record in history[i:i + len(workflow)]):
                    successful_attempts += 1
                i += len(workflow)
            else:
                i += 1
        
        return successful_attempts / total_attempts if total_attempts > 0 else 0.0
    
    def _calculate_avg_workflow_duration(self, history: List[Dict[str, Any]], workflow: List[str]) -> float:
        """计算工作流平均持续时间"""
        durations = []
        
        i = 0
        while i < len(history) - len(workflow) + 1:
            if self._matches_workflow(history[i:i + len(workflow)], workflow):
                window = history[i:i + len(workflow)]
                duration = window[-1]["timestamp"] - window[0]["timestamp"]
                durations.append(duration)
                i += len(workflow)
            else:
                i += 1
        
        return statistics.mean(durations) if durations else 0.0
    
    def get_pattern_stats(self) -> Dict[str, Any]:
        """获取模式统计信息"""
        return {
            "total_commands_recorded": len(self.command_history),
            "operation_patterns": len(self.operation_patterns),
            "user_habits": len(self.user_habits),
            "workflow_patterns": len(self.workflow_patterns),
            "analysis_timeframes": self.time_window_sizes,
            "min_pattern_frequency": self.min_pattern_frequency,
            "pattern_types": list(self.pattern_types.keys())
        }
    
    def _save_data(self) -> None:
        """保存数据"""
        try:
            data = {
                "command_history": self.command_history[-5000:],  # 只保存最近5000条
                "operation_patterns": {k: v.to_dict() for k, v in self.operation_patterns.items()},
                "user_habits": {k: v.to_dict() for k, v in self.user_habits.items()},
                "workflow_patterns": {k: v.to_dict() for k, v in self.workflow_patterns.items()},
                "last_saved": time.time()
            }
            
            with open(self.data_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                
        except Exception as e:
            self.logger.error(f"保存模式数据失败: {e}")
    
    def _load_data(self) -> None:
        """加载数据"""
        try:
            with open(self.data_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            self.command_history = data.get("command_history", [])
            
            # 加载模式数据
            for k, v in data.get("operation_patterns", {}).items():
                self.operation_patterns[k] = OperationPattern(**v)
            
            for k, v in data.get("user_habits", {}).items():
                self.user_habits[k] = UserHabit(**v)
            
            for k, v in data.get("workflow_patterns", {}).items():
                self.workflow_patterns[k] = WorkflowPattern(**v)
            
            self.logger.info(f"加载模式数据: {len(self.command_history)}条历史记录")
            
        except FileNotFoundError:
            self.logger.info("模式数据文件不存在，将创建新文件")
        except Exception as e:
            self.logger.error(f"加载模式数据失败: {e}")
    
    def save(self) -> None:
        """保存数据"""
        self._save_data() 