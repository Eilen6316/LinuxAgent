#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
命令执行器接口
定义执行系统命令的抽象接口
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Tuple, Optional


class CommandExecutorInterface(ABC):
    """命令执行器抽象接口"""
    
    @abstractmethod
    def execute_command(self, command: str, timeout: Optional[int] = None) -> Tuple[str, str, int]:
        """
        执行命令
        
        Args:
            command: 要执行的命令
            timeout: 超时时间(秒)
            
        Returns:
            元组 (stdout, stderr, return_code)
        """
        pass
    
    @abstractmethod
    def is_command_safe(self, command: str) -> Tuple[bool, str]:
        """
        检查命令是否安全
        
        Args:
            command: 要检查的命令
            
        Returns:
            元组 (is_safe, reason_if_unsafe)
        """
        pass
    
    @abstractmethod
    def get_system_info(self) -> Dict[str, Any]:
        """
        获取系统信息
        
        Returns:
            系统信息字典
        """
        pass
        
    @abstractmethod
    def execute_file_editor(self, file_path: str, editor: str = "vim") -> Tuple[str, str, int]:
        """
        使用编辑器打开文件
        
        Args:
            file_path: 文件路径
            editor: 编辑器
            
        Returns:
            元组 (stdout, stderr, return_code)
        """
        pass 