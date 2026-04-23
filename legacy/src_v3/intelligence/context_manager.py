#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
上下文管理器
维护用户会话上下文、系统状态和智能功能的状态管理
"""

import json
import time
import logging
import os
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict
from collections import deque
from datetime import datetime, timedelta


@dataclass
class SessionContext:
    """会话上下文"""
    session_id: str
    start_time: float
    last_activity: float
    working_directory: str
    environment_vars: Dict[str, str]
    recent_commands: List[str]
    current_task: Optional[str]
    user_preferences: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SessionContext':
        """从字典创建"""
        return cls(**data)


@dataclass
class SystemContext:
    """系统上下文"""
    hostname: str
    os_info: Dict[str, str]
    hardware_info: Dict[str, Any]
    network_info: Dict[str, Any]
    installed_packages: List[str]
    running_services: List[str]
    system_load: Dict[str, float]
    last_updated: float
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)


@dataclass
class ConversationTurn:
    """对话轮次"""
    turn_id: str
    timestamp: float
    user_input: str
    agent_response: str
    command_executed: Optional[str]
    success: bool
    execution_time: Optional[float]
    context_data: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)


@dataclass
class ContextState:
    """上下文状态"""
    current_intent: Optional[str]
    ongoing_task: Optional[str]
    task_progress: float
    accumulated_context: Dict[str, Any]
    temporary_data: Dict[str, Any]
    confidence_level: float
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)


class ContextManager:
    """上下文管理器"""
    
    def __init__(self, session_id: str = None, data_dir: str = None):
        """
        初始化上下文管理器
        
        Args:
            session_id: 会话ID
            data_dir: 数据目录
        """
        self.session_id = session_id or f"session_{int(time.time())}"
        self.data_dir = data_dir or os.path.expanduser("~/.linuxagent_context")
        self.logger = logging.getLogger(__name__)
        
        # 确保数据目录存在
        os.makedirs(self.data_dir, exist_ok=True)
        
        # 当前会话上下文
        self.session_context = self._initialize_session_context()
        
        # 系统上下文
        self.system_context = self._initialize_system_context()
        
        # 对话历史
        self.conversation_history: deque = deque(maxlen=100)  # 最多保存100轮对话
        
        # 上下文状态
        self.context_state = ContextState(
            current_intent=None,
            ongoing_task=None,
            task_progress=0.0,
            accumulated_context={},
            temporary_data={},
            confidence_level=1.0
        )
        
        # 上下文配置
        self.config = {
            "max_context_age": 3600,  # 最大上下文年龄（秒）
            "auto_save_interval": 300,  # 自动保存间隔（秒）
            "context_compression_threshold": 1000,  # 上下文压缩阈值
            "max_temporary_data_size": 50  # 最大临时数据条目数
        }
        
        # 上下文监听器
        self.context_listeners: List[callable] = []
        
        # 加载历史数据
        self._load_context_data()
        
        # 启动自动保存
        self.last_save_time = time.time()
        
        self.logger.info(f"上下文管理器初始化完成，会话ID: {self.session_id}")
    
    def _initialize_session_context(self) -> SessionContext:
        """初始化会话上下文"""
        current_time = time.time()
        
        return SessionContext(
            session_id=self.session_id,
            start_time=current_time,
            last_activity=current_time,
            working_directory=os.getcwd(),
            environment_vars=dict(os.environ),
            recent_commands=[],
            current_task=None,
            user_preferences={}
        )
    
    def _initialize_system_context(self) -> SystemContext:
        """初始化系统上下文"""
        import platform
        import socket
        
        # 获取系统信息
        os_info = {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "processor": platform.processor()
        }
        
        # 获取主机信息
        hostname = socket.gethostname()
        
        # 获取硬件信息（简化版）
        hardware_info = {
            "cpu_count": os.cpu_count(),
            "architecture": platform.architecture()[0]
        }
        
        # 获取网络信息
        network_info = {
            "hostname": hostname,
            "fqdn": socket.getfqdn()
        }
        
        return SystemContext(
            hostname=hostname,
            os_info=os_info,
            hardware_info=hardware_info,
            network_info=network_info,
            installed_packages=[],  # 将在后续填充
            running_services=[],    # 将在后续填充
            system_load={},        # 将在后续填充
            last_updated=time.time()
        )
    
    def update_session_context(self, **kwargs) -> None:
        """
        更新会话上下文
        
        Args:
            **kwargs: 要更新的上下文字段
        """
        self.session_context.last_activity = time.time()
        
        for key, value in kwargs.items():
            if hasattr(self.session_context, key):
                setattr(self.session_context, key, value)
        
        # 通知监听器
        self._notify_context_change("session_update", kwargs)
        
        self.logger.debug(f"会话上下文已更新: {kwargs}")
    
    def update_system_context(self, system_data: Dict[str, Any]) -> None:
        """
        更新系统上下文
        
        Args:
            system_data: 系统数据
        """
        if system_data is None:
            self.logger.warning("系统数据为空，跳过上下文更新")
            return
            
        self.system_context.last_updated = time.time()
        
        for key, value in system_data.items():
            if hasattr(self.system_context, key):
                setattr(self.system_context, key, value)
        
        # 通知监听器
        self._notify_context_change("system_update", system_data)
        
        self.logger.debug("系统上下文已更新")
    
    def add_conversation_turn(self, user_input: str, agent_response: str,
                            command_executed: str = None, success: bool = True,
                            execution_time: float = None) -> str:
        """
        添加对话轮次
        
        Args:
            user_input: 用户输入
            agent_response: 代理响应
            command_executed: 执行的命令
            success: 是否成功
            execution_time: 执行时间
            
        Returns:
            轮次ID
        """
        turn_id = f"turn_{int(time.time() * 1000)}"
        
        turn = ConversationTurn(
            turn_id=turn_id,
            timestamp=time.time(),
            user_input=user_input,
            agent_response=agent_response,
            command_executed=command_executed,
            success=success,
            execution_time=execution_time,
            context_data=self._capture_current_context()
        )
        
        self.conversation_history.append(turn)
        
        # 更新最近命令
        if command_executed:
            self.session_context.recent_commands.append(command_executed)
            if len(self.session_context.recent_commands) > 20:
                self.session_context.recent_commands = self.session_context.recent_commands[-20:]
        
        # 更新上下文状态
        self._update_context_state(turn)
        
        # 通知监听器
        self._notify_context_change("conversation_turn", turn.to_dict())
        
        self.logger.debug(f"添加对话轮次: {turn_id}")
        
        return turn_id
    
    def _capture_current_context(self) -> Dict[str, Any]:
        """捕获当前上下文"""
        return {
            "working_directory": self.session_context.working_directory,
            "recent_commands": self.session_context.recent_commands[-5:],
            "current_task": self.session_context.current_task,
            "system_load": self.system_context.system_load,
            "timestamp": time.time()
        }
    
    def _update_context_state(self, turn: ConversationTurn) -> None:
        """更新上下文状态"""
        # 意图持续性检查
        if self.context_state.current_intent:
            # 检查意图是否仍然相关
            if self._is_intent_still_relevant(turn.user_input):
                # 更新任务进度
                if self.context_state.ongoing_task:
                    self.context_state.task_progress = min(
                        self.context_state.task_progress + 0.1, 1.0
                    )
            else:
                # 重置意图和任务
                self.context_state.current_intent = None
                self.context_state.ongoing_task = None
                self.context_state.task_progress = 0.0
        
        # 累积上下文信息
        self._accumulate_context_info(turn)
        
        # 清理过期的临时数据
        self._cleanup_temporary_data()
    
    def _is_intent_still_relevant(self, user_input: str) -> bool:
        """检查意图是否仍然相关"""
        if not self.context_state.current_intent:
            return False
        
        # 简单的相关性检查
        intent_keywords = {
            "file_operations": ["文件", "目录", "复制", "移动", "删除"],
            "system_monitoring": ["系统", "监控", "性能", "进程", "内存"],
            "development": ["代码", "编译", "测试", "部署", "git"]
        }
        
        current_intent = self.context_state.current_intent
        if current_intent in intent_keywords:
            keywords = intent_keywords[current_intent]
            return any(keyword in user_input.lower() for keyword in keywords)
        
        return False
    
    def _accumulate_context_info(self, turn: ConversationTurn) -> None:
        """累积上下文信息"""
        # 提取重要信息
        if turn.command_executed:
            command_type = turn.command_executed.split()[0]
            
            # 计数命令类型
            if "command_counts" not in self.context_state.accumulated_context:
                self.context_state.accumulated_context["command_counts"] = {}
            
            counts = self.context_state.accumulated_context["command_counts"]
            counts[command_type] = counts.get(command_type, 0) + 1
        
        # 记录错误信息
        if not turn.success:
            if "recent_errors" not in self.context_state.accumulated_context:
                self.context_state.accumulated_context["recent_errors"] = []
            
            error_info = {
                "command": turn.command_executed,
                "timestamp": turn.timestamp,
                "user_input": turn.user_input
            }
            
            self.context_state.accumulated_context["recent_errors"].append(error_info)
            
            # 只保留最近的10个错误
            if len(self.context_state.accumulated_context["recent_errors"]) > 10:
                self.context_state.accumulated_context["recent_errors"] = \
                    self.context_state.accumulated_context["recent_errors"][-10:]
    
    def _cleanup_temporary_data(self) -> None:
        """清理临时数据"""
        current_time = time.time()
        max_age = self.config["max_context_age"]
        
        # 清理过期的临时数据
        expired_keys = []
        for key, data in self.context_state.temporary_data.items():
            if isinstance(data, dict) and "timestamp" in data:
                if current_time - data["timestamp"] > max_age:
                    expired_keys.append(key)
        
        for key in expired_keys:
            del self.context_state.temporary_data[key]
        
        # 限制临时数据大小
        max_size = self.config["max_temporary_data_size"]
        if len(self.context_state.temporary_data) > max_size:
            # 按时间戳排序，保留最新的
            items = list(self.context_state.temporary_data.items())
            items.sort(key=lambda x: x[1].get("timestamp", 0) if isinstance(x[1], dict) else 0)
            
            self.context_state.temporary_data = dict(items[-max_size:])
    
    def set_current_intent(self, intent: str, confidence: float = 1.0) -> None:
        """
        设置当前意图
        
        Args:
            intent: 意图名称
            confidence: 置信度
        """
        self.context_state.current_intent = intent
        self.context_state.confidence_level = confidence
        
        # 通知监听器
        self._notify_context_change("intent_change", {
            "intent": intent, 
            "confidence": confidence
        })
        
        self.logger.debug(f"设置当前意图: {intent} (置信度: {confidence})")
    
    def set_ongoing_task(self, task: str, initial_progress: float = 0.0) -> None:
        """
        设置进行中的任务
        
        Args:
            task: 任务描述
            initial_progress: 初始进度
        """
        self.context_state.ongoing_task = task
        self.context_state.task_progress = initial_progress
        self.session_context.current_task = task
        
        # 通知监听器
        self._notify_context_change("task_start", {
            "task": task,
            "progress": initial_progress
        })
        
        self.logger.debug(f"设置当前任务: {task}")
    
    def update_task_progress(self, progress: float) -> None:
        """
        更新任务进度
        
        Args:
            progress: 进度值 (0.0-1.0)
        """
        if self.context_state.ongoing_task:
            self.context_state.task_progress = max(0.0, min(1.0, progress))
            
            # 通知监听器
            self._notify_context_change("task_progress", {
                "task": self.context_state.ongoing_task,
                "progress": self.context_state.task_progress
            })
            
            # 任务完成
            if self.context_state.task_progress >= 1.0:
                self.complete_task()
    
    def complete_task(self) -> None:
        """完成当前任务"""
        if self.context_state.ongoing_task:
            completed_task = self.context_state.ongoing_task
            
            self.context_state.ongoing_task = None
            self.context_state.task_progress = 0.0
            self.session_context.current_task = None
            
            # 通知监听器
            self._notify_context_change("task_complete", {
                "completed_task": completed_task
            })
            
            self.logger.info(f"任务完成: {completed_task}")
    
    def add_temporary_data(self, key: str, data: Any, ttl: int = 3600) -> None:
        """
        添加临时数据
        
        Args:
            key: 数据键
            data: 数据值
            ttl: 生存时间（秒）
        """
        self.context_state.temporary_data[key] = {
            "data": data,
            "timestamp": time.time(),
            "ttl": ttl
        }
        
        self.logger.debug(f"添加临时数据: {key}")
    
    def get_temporary_data(self, key: str) -> Optional[Any]:
        """
        获取临时数据
        
        Args:
            key: 数据键
            
        Returns:
            数据值或None
        """
        if key in self.context_state.temporary_data:
            data_info = self.context_state.temporary_data[key]
            
            # 检查是否过期
            if time.time() - data_info["timestamp"] <= data_info["ttl"]:
                return data_info["data"]
            else:
                # 删除过期数据
                del self.context_state.temporary_data[key]
        
        return None
    
    def get_recent_conversation(self, count: int = 5) -> List[ConversationTurn]:
        """
        获取最近的对话
        
        Args:
            count: 对话数量
            
        Returns:
            最近的对话列表
        """
        return list(self.conversation_history)[-count:]
    
    def get_context_summary(self) -> Dict[str, Any]:
        """获取上下文摘要"""
        return {
            "session_info": {
                "session_id": self.session_context.session_id,
                "duration": time.time() - self.session_context.start_time,
                "working_directory": self.session_context.working_directory,
                "recent_commands_count": len(self.session_context.recent_commands)
            },
            "current_state": {
                "intent": self.context_state.current_intent,
                "task": self.context_state.ongoing_task,
                "task_progress": self.context_state.task_progress,
                "confidence": self.context_state.confidence_level
            },
            "conversation_stats": {
                "total_turns": len(self.conversation_history),
                "recent_success_rate": self._calculate_recent_success_rate(),
                "avg_response_time": self._calculate_avg_response_time()
            },
            "system_info": {
                "hostname": self.system_context.hostname,
                "os": f"{self.system_context.os_info['system']} {self.system_context.os_info['release']}",
                "last_system_update": self.system_context.last_updated
            }
        }
    
    def _calculate_recent_success_rate(self) -> float:
        """计算最近的成功率"""
        if not self.conversation_history:
            return 1.0
        
        recent_turns = list(self.conversation_history)[-10:]  # 最近10轮
        success_count = sum(1 for turn in recent_turns if turn.success)
        
        return success_count / len(recent_turns)
    
    def _calculate_avg_response_time(self) -> float:
        """计算平均响应时间"""
        execution_times = [
            turn.execution_time for turn in self.conversation_history
            if turn.execution_time is not None
        ]
        
        if execution_times:
            return sum(execution_times) / len(execution_times)
        
        return 0.0
    
    def add_context_listener(self, listener: callable) -> None:
        """
        添加上下文监听器
        
        Args:
            listener: 监听器函数，接收 (event_type, data) 参数
        """
        self.context_listeners.append(listener)
        self.logger.debug("添加上下文监听器")
    
    def remove_context_listener(self, listener: callable) -> None:
        """
        移除上下文监听器
        
        Args:
            listener: 要移除的监听器函数
        """
        if listener in self.context_listeners:
            self.context_listeners.remove(listener)
            self.logger.debug("移除上下文监听器")
    
    def _notify_context_change(self, event_type: str, data: Any) -> None:
        """通知上下文变化"""
        for listener in self.context_listeners:
            try:
                listener(event_type, data)
            except Exception as e:
                self.logger.error(f"上下文监听器错误: {e}")
    
    def save_context(self) -> None:
        """保存上下文数据"""
        try:
            context_data = {
                "session_context": self.session_context.to_dict(),
                "system_context": self.system_context.to_dict(),
                "context_state": self.context_state.to_dict(),
                "conversation_history": [turn.to_dict() for turn in self.conversation_history],
                "config": self.config,
                "last_saved": time.time()
            }
            
            context_file = os.path.join(self.data_dir, f"context_{self.session_id}.json")
            with open(context_file, 'w', encoding='utf-8') as f:
                json.dump(context_data, f, indent=2, ensure_ascii=False)
            
            self.last_save_time = time.time()
            self.logger.debug("上下文数据已保存")
            
        except Exception as e:
            self.logger.error(f"保存上下文数据失败: {e}")
    
    def _load_context_data(self) -> None:
        """加载上下文数据"""
        context_file = os.path.join(self.data_dir, f"context_{self.session_id}.json")
        
        if os.path.exists(context_file):
            try:
                with open(context_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # 加载会话上下文
                if "session_context" in data:
                    self.session_context = SessionContext.from_dict(data["session_context"])
                
                # 加载系统上下文
                if "system_context" in data:
                    self.system_context = SystemContext(**data["system_context"])
                
                # 加载上下文状态
                if "context_state" in data:
                    self.context_state = ContextState(**data["context_state"])
                
                # 加载对话历史
                if "conversation_history" in data:
                    self.conversation_history = deque(
                        [ConversationTurn(**turn) for turn in data["conversation_history"]],
                        maxlen=100
                    )
                
                # 加载配置
                if "config" in data:
                    self.config.update(data["config"])
                
                self.logger.info(f"加载上下文数据: {len(self.conversation_history)}轮对话")
                
            except Exception as e:
                self.logger.error(f"加载上下文数据失败: {e}")
    
    def auto_save_if_needed(self) -> None:
        """如果需要则自动保存"""
        if time.time() - self.last_save_time >= self.config["auto_save_interval"]:
            self.save_context()
    
    def clear_context(self, keep_session: bool = True) -> None:
        """
        清理上下文
        
        Args:
            keep_session: 是否保留会话信息
        """
        if not keep_session:
            self.session_context = self._initialize_session_context()
        
        self.conversation_history.clear()
        self.context_state = ContextState(
            current_intent=None,
            ongoing_task=None,
            task_progress=0.0,
            accumulated_context={},
            temporary_data={},
            confidence_level=1.0
        )
        
        # 通知监听器
        self._notify_context_change("context_cleared", {"keep_session": keep_session})
        
        self.logger.info("上下文已清理")
    
    def export_context(self, file_path: str) -> bool:
        """
        导出上下文数据
        
        Args:
            file_path: 导出文件路径
            
        Returns:
            是否成功
        """
        try:
            export_data = {
                "session_context": self.session_context.to_dict(),
                "system_context": self.system_context.to_dict(),
                "context_state": self.context_state.to_dict(),
                "conversation_history": [turn.to_dict() for turn in self.conversation_history],
                "context_summary": self.get_context_summary(),
                "export_time": time.time()
            }
            
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, indent=2, ensure_ascii=False)
            
            self.logger.info(f"上下文数据导出到: {file_path}")
            return True
            
        except Exception as e:
            self.logger.error(f"导出上下文数据失败: {e}")
            return False
    
    def get_context_stats(self) -> Dict[str, Any]:
        """获取上下文统计信息"""
        return {
            "session_duration": time.time() - self.session_context.start_time,
            "total_conversations": len(self.conversation_history),
            "total_commands": len(self.session_context.recent_commands),
            "current_intent": self.context_state.current_intent,
            "ongoing_task": self.context_state.ongoing_task,
            "task_progress": self.context_state.task_progress,
            "confidence_level": self.context_state.confidence_level,
            "accumulated_context_size": len(self.context_state.accumulated_context),
            "temporary_data_size": len(self.context_state.temporary_data),
            "context_listeners": len(self.context_listeners)
        } 