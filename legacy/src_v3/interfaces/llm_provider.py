#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
LLM提供者接口
定义与大语言模型交互的抽象接口
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Union, Generator


class LLMProvider(ABC):
    """大语言模型提供者抽象接口"""
    
    @abstractmethod
    def is_available(self) -> bool:
        """检查API是否可用"""
        pass
    
    @abstractmethod
    def generate_command(self, task: str, system_info: Dict[str, Any]) -> Dict[str, Any]:
        """
        获取执行任务的命令
        
        Args:
            task: 用户描述的任务
            system_info: 系统信息
            
        Returns:
            包含命令和相关信息的字典
        """
        pass
    
    @abstractmethod
    def analyze_output(self, command: str, stdout: str, stderr: str) -> Dict[str, Any]:
        """
        分析命令输出
        
        Args:
            command: 执行的命令
            stdout: 标准输出
            stderr: 标准错误
            
        Returns:
            分析结果字典
        """
        pass
    
    @abstractmethod
    def get_template_suggestion(self, prompt: str, system_info: Dict[str, Any]) -> Dict[str, Any]:
        """
        获取模板建议
        
        Args:
            prompt: 提示
            system_info: 系统信息
            
        Returns:
            建议字典
        """
        pass
    
    @abstractmethod
    def stream_response(self, messages: List[Dict[str, str]]) -> Generator[str, None, None]:
        """
        流式获取响应
        
        Args:
            messages: 消息列表
            
        Returns:
            响应生成器
        """
        pass 