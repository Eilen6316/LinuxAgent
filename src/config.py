#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
配置模块
处理配置文件的加载和解析
"""

import os
import yaml
from typing import Dict, Any, List, Optional

class ConfigSection:
    """配置部分的基类"""
    
    def __init__(self, config_dict: Dict[str, Any]):
        """从字典中加载配置"""
        for key, value in config_dict.items():
            setattr(self, key, value)
    
    def to_dict(self) -> Dict[str, Any]:
        """将配置转换为字典"""
        return {k: v for k, v in self.__dict__.items() if not k.startswith('_')}


class APIConfig(ConfigSection):
    """API配置"""
    
    def __init__(self, config_dict: Dict[str, Any]):
        """初始化API配置"""
        self.provider = "deepseek"
        self.api_key = ""
        self.base_url = "https://api.deepseek.com/v1"
        self.model = "deepseek-chat"
        self.timeout = 30
        
        super().__init__(config_dict)


class SecurityConfig(ConfigSection):
    """安全配置"""
    
    def __init__(self, config_dict: Dict[str, Any]):
        """初始化安全配置"""
        self.confirm_dangerous_commands = True
        self.blocked_commands = []
        self.confirm_patterns = []
        
        super().__init__(config_dict)


class UIConfig(ConfigSection):
    """用户界面配置"""
    
    def __init__(self, config_dict: Dict[str, Any]):
        """初始化用户界面配置"""
        self.history_file = "~/.linuxagent_history"
        self.max_history = 1000
        self.always_stream = True  # 默认启用总是流式回答
        
        super().__init__(config_dict)


class LoggingConfig(ConfigSection):
    """日志配置"""
    
    def __init__(self, config_dict: Dict[str, Any]):
        """初始化日志配置"""
        self.level = "INFO"
        self.file = "~/.linuxagent.log"
        self.max_size_mb = 5
        self.backup_count = 3
        
        super().__init__(config_dict)


class Config:
    """配置类"""
    
    def __init__(self, config_file: str):
        """从配置文件加载配置"""
        self.config_file = config_file
        config_dict = self._load_config_file()
        
        # 加载各部分配置
        self.api = APIConfig(config_dict.get("api", {}))
        self.security = SecurityConfig(config_dict.get("security", {}))
        self.ui = UIConfig(config_dict.get("ui", {}))
        self.logging = LoggingConfig(config_dict.get("logging", {}))
        
    def _load_config_file(self) -> Dict[str, Any]:
        """加载配置文件"""
        if not os.path.exists(self.config_file):
            raise FileNotFoundError(f"配置文件不存在: {self.config_file}")
            
        with open(self.config_file, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
            
        if not config:
            raise ValueError(f"配置文件为空或格式错误: {self.config_file}")
            
        return config
    
    def to_dict(self) -> Dict[str, Any]:
        """将配置转换为字典"""
        return {
            "api": self.api.to_dict(),
            "security": self.security.to_dict(),
            "ui": self.ui.to_dict(),
            "logging": self.logging.to_dict()
        } 