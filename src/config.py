#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
配置模块
处理配置文件的加载和解析
"""

import os
import yaml
from typing import Dict, Any


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


class IntelligenceConfig(ConfigSection):
    """智能化功能配置"""

    def __init__(self, config_dict: Dict[str, Any]):
        """初始化智能化配置"""
        # 设置默认值
        self.enabled = True
        
        # 命令学习器配置
        learning_config = config_dict.get("learning", {})
        self.learning_data_file = learning_config.get("data_file", "~/.linuxagent_learning.json")
        self.max_learning_history = learning_config.get("max_history", 10000)
        self.min_pattern_frequency = learning_config.get("min_pattern_frequency", 3)
        self.learning_auto_save_interval = learning_config.get("auto_save_interval", 300)
        
        # 知识库配置
        knowledge_config = config_dict.get("knowledge", {})
        self.knowledge_data_dir = knowledge_config.get("data_dir", "~/.linuxagent_knowledge")
        self.knowledge_auto_update = knowledge_config.get("auto_update", True)
        self.knowledge_include_builtin = knowledge_config.get("include_builtin", True)
        
        # 推荐引擎配置
        recommendation_config = config_dict.get("recommendation", {})
        self.recommendation_enabled = recommendation_config.get("enabled", True)
        self.recommendation_max = recommendation_config.get("max_recommendations", 10)
        context_weights = recommendation_config.get("context_weights", {})
        self.context_weights = {
            "directory_match": context_weights.get("directory_match", 0.3),
            "recent_commands": context_weights.get("recent_commands", 0.25),
            "system_status": context_weights.get("system_status", 0.2),
            "user_pattern": context_weights.get("user_pattern", 0.15),
            "intent_match": context_weights.get("intent_match", 0.1)
        }
        
        # 自然语言处理配置
        nlp_config = config_dict.get("nlp", {})
        self.nlp_enabled = nlp_config.get("enabled", True)
        self.nlp_auto_translate = nlp_config.get("auto_translate", True)
        self.nlp_min_confidence = nlp_config.get("min_confidence", 0.6)
        self.nlp_show_alternatives = nlp_config.get("show_alternatives", True)
        
        # 模式分析配置
        pattern_config = config_dict.get("pattern_analysis", {})
        self.pattern_enabled = pattern_config.get("enabled", True)
        self.pattern_data_file = pattern_config.get("data_file", "~/.linuxagent_patterns.json")
        self.pattern_analysis_window_days = pattern_config.get("analysis_window_days", 7)
        self.pattern_min_strength = pattern_config.get("min_pattern_strength", 0.3)
        
        # 上下文管理配置
        context_config = config_dict.get("context", {})
        self.context_enabled = context_config.get("enabled", True)
        self.context_data_dir = context_config.get("data_dir", "~/.linuxagent_context")
        self.context_max_age = context_config.get("max_context_age", 3600)
        self.context_auto_save_interval = context_config.get("auto_save_interval", 300)
        self.context_max_conversation_history = context_config.get("max_conversation_history", 100)

        super().__init__(config_dict)


class Config:
    """配置类"""

    def __init__(self, config_file: str):
        """从配置文件加载配置"""
        self.config_file = config_file
        config_dict = self._load_config_file()

        self.api = APIConfig(config_dict.get("api", {}))
        self.security = SecurityConfig(config_dict.get("security", {}))
        self.ui = UIConfig(config_dict.get("ui", {}))
        self.logging = LoggingConfig(config_dict.get("logging", {}))
        self.intelligence = IntelligenceConfig(config_dict.get("intelligence", {}))

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
            "logging": self.logging.to_dict(),
            "intelligence": self.intelligence.to_dict()
        }
