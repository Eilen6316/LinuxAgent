#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
用户界面接口
定义与用户交互的抽象接口
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Union, Callable, Generator


class UserInterface(ABC):
    """用户界面抽象接口"""
    
    @abstractmethod
    def welcome(self) -> None:
        """显示欢迎信息"""
        pass
    
    @abstractmethod
    def get_input(self, prompt: str = "") -> str:
        """
        获取用户输入
        
        Args:
            prompt: 提示文本
            
        Returns:
            用户输入
        """
        pass
    
    @abstractmethod
    def show_thinking(self) -> None:
        """显示正在思考的提示"""
        pass
    
    @abstractmethod
    def show_result(self, result: Union[str, Dict[str, Any]], command: Optional[str] = None) -> None:
        """
        显示结果
        
        Args:
            result: 结果文本或字典
            command: 执行的命令(如果有)
        """
        pass
    
    @abstractmethod
    def show_error(self, message: str) -> None:
        """
        显示错误信息
        
        Args:
            message: 错误信息
        """
        pass
    
    @abstractmethod
    def confirm(self, message: str) -> bool:
        """
        获取用户确认
        
        Args:
            message: 确认消息
            
        Returns:
            是否确认
        """
        pass
    
    @abstractmethod
    def clear_screen(self) -> None:
        """清屏"""
        pass
    
    @abstractmethod
    def show_help(self) -> None:
        """显示帮助信息"""
        pass
    
    @abstractmethod
    def show_history(self, entries: List[str]) -> None:
        """
        显示历史记录
        
        Args:
            entries: 历史记录条目
        """
        pass
    
    @abstractmethod
    def show_config(self, config: Dict[str, Any]) -> None:
        """
        显示配置信息
        
        Args:
            config: 配置字典
        """
        pass
    
    @abstractmethod
    def stream_output(self, generator: Generator[str, None, None]) -> None:
        """
        流式显示输出
        
        Args:
            generator: 输出生成器
        """
        pass 