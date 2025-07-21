#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
智能推荐引擎
基于用户上下文、历史数据和系统状态提供智能命令推荐
"""

import re
import logging
import time
from typing import Dict, List, Optional, Tuple, Any, Set
from dataclasses import dataclass
from collections import defaultdict, Counter

from .command_learner import CommandLearner
from .knowledge_base import KnowledgeBase


@dataclass
class RecommendationContext:
    """推荐上下文"""
    current_directory: str
    recent_commands: List[str]
    system_status: Dict[str, Any]
    user_input: str
    intent: Optional[str] = None
    urgency: str = "normal"  # low, normal, high
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "current_directory": self.current_directory,
            "recent_commands": self.recent_commands,
            "system_status": self.system_status,
            "user_input": self.user_input,
            "intent": self.intent,
            "urgency": self.urgency
        }


@dataclass
class Recommendation:
    """推荐结果"""
    command: str
    description: str
    confidence: float
    reason: str
    category: str
    parameters: List[str]
    examples: List[str]
    risks: List[str]
    alternatives: List[str]
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "command": self.command,
            "description": self.description,
            "confidence": self.confidence,
            "reason": self.reason,
            "category": self.category,
            "parameters": self.parameters,
            "examples": self.examples,
            "risks": self.risks,
            "alternatives": self.alternatives
        }


class RecommendationEngine:
    """智能推荐引擎"""
    
    def __init__(self, command_learner: CommandLearner = None, knowledge_base: KnowledgeBase = None):
        """
        初始化推荐引擎
        
        Args:
            command_learner: 命令学习器
            knowledge_base: 知识库
        """
        self.command_learner = command_learner
        self.knowledge_base = knowledge_base
        self.logger = logging.getLogger(__name__)
        
        # 意图识别模式
        self.intent_patterns = self._build_intent_patterns()
        
        # 上下文权重
        self.context_weights = {
            "directory_match": 0.3,
            "recent_command_sequence": 0.25,
            "system_status": 0.2,
            "user_pattern": 0.15,
            "intent_match": 0.1
        }
        
        # 命令分类
        self.command_categories = self._build_command_categories()
        
        self.logger.info("智能推荐引擎初始化完成")
    
    def _build_intent_patterns(self) -> Dict[str, List[str]]:
        """构建意图识别模式"""
        return {
            "file_operations": [
                r"(?:复制|拷贝|copy)",
                r"(?:移动|move|mv)",
                r"(?:删除|remove|rm)",
                r"(?:创建|新建|create|touch|mkdir)",
                r"(?:查找|搜索|find|search)",
                r"(?:查看|显示|show|cat|less)"
            ],
            "system_monitoring": [
                r"(?:查看|检查|monitor).*(?:系统|性能|状态)",
                r"(?:CPU|内存|磁盘|网络).*(?:使用|占用)",
                r"(?:进程|process|ps)",
                r"(?:服务|service|systemctl)"
            ],
            "network_operations": [
                r"(?:网络|network|net)",
                r"(?:连接|connect|ping)",
                r"(?:下载|download|wget|curl)",
                r"(?:传输|transfer|scp|rsync)"
            ],
            "package_management": [
                r"(?:安装|install|apt|yum|pacman)",
                r"(?:更新|update|upgrade)",
                r"(?:卸载|remove|uninstall)",
                r"(?:包|package|软件)"
            ],
            "text_processing": [
                r"(?:编辑|edit|vim|nano)",
                r"(?:搜索|grep|find).*(?:文本|内容)",
                r"(?:替换|replace|sed)",
                r"(?:排序|sort)"
            ],
            "permission_management": [
                r"(?:权限|permission|chmod)",
                r"(?:所有者|owner|chown)",
                r"(?:用户|user|group)"
            ]
        }
    
    def _build_command_categories(self) -> Dict[str, List[str]]:
        """构建命令分类"""
        return {
            "file_operations": ["ls", "cp", "mv", "rm", "mkdir", "rmdir", "touch", "find", "locate"],
            "text_processing": ["cat", "less", "more", "head", "tail", "grep", "sed", "awk", "sort", "uniq"],
            "system_monitoring": ["top", "htop", "ps", "df", "du", "free", "iostat", "netstat"],
            "network": ["ping", "wget", "curl", "ssh", "scp", "rsync", "nc"],
            "package_management": ["apt", "yum", "pacman", "pip", "npm", "docker"],
            "permission": ["chmod", "chown", "chgrp", "umask", "sudo"],
            "archive": ["tar", "zip", "unzip", "gzip", "gunzip"],
            "development": ["git", "make", "gcc", "python", "node", "npm"]
        }
    
    def recommend_commands(self, context: RecommendationContext) -> List[Recommendation]:
        """
        推荐命令
        
        Args:
            context: 推荐上下文
            
        Returns:
            推荐列表
        """
        recommendations = []
        
        # 1. 意图识别
        intent = self._identify_intent(context.user_input)
        context.intent = intent
        
        # 2. 基于意图的推荐
        intent_recommendations = self._recommend_by_intent(context)
        recommendations.extend(intent_recommendations)
        
        # 3. 基于学习历史的推荐
        if self.command_learner:
            learning_recommendations = self._recommend_by_learning(context)
            recommendations.extend(learning_recommendations)
        
        # 4. 基于知识库的推荐
        if self.knowledge_base:
            knowledge_recommendations = self._recommend_by_knowledge(context)
            recommendations.extend(knowledge_recommendations)
        
        # 5. 基于上下文的推荐
        context_recommendations = self._recommend_by_context(context)
        recommendations.extend(context_recommendations)
        
        # 6. 去重和排序
        recommendations = self._deduplicate_and_rank(recommendations)
        
        return recommendations[:10]  # 返回前10个推荐
    
    def _identify_intent(self, user_input: str) -> Optional[str]:
        """识别用户意图"""
        user_input_lower = user_input.lower()
        
        for intent, patterns in self.intent_patterns.items():
            for pattern in patterns:
                if re.search(pattern, user_input_lower):
                    return intent
        
        return None
    
    def _recommend_by_intent(self, context: RecommendationContext) -> List[Recommendation]:
        """基于意图推荐"""
        recommendations = []
        
        if not context.intent:
            return recommendations
        
        intent_commands = self.command_categories.get(context.intent, [])
        
        for command in intent_commands[:5]:  # 每个意图最多5个推荐
            # 计算置信度
            confidence = 0.7  # 基础置信度
            
            # 根据用户输入相似度调整
            if command in context.user_input.lower():
                confidence += 0.2
            
            # 根据最近使用情况调整
            if context.recent_commands and command in [cmd.split()[0] for cmd in context.recent_commands]:
                confidence += 0.1
            
            recommendation = Recommendation(
                command=command,
                description=f"用于{context.intent}的{command}命令",
                confidence=min(confidence, 1.0),
                reason=f"基于意图识别: {context.intent}",
                category=context.intent,
                parameters=self._get_common_parameters(command),
                examples=self._get_command_examples(command),
                risks=self._get_command_risks(command),
                alternatives=self._get_command_alternatives(command)
            )
            
            recommendations.append(recommendation)
        
        return recommendations
    
    def _recommend_by_learning(self, context: RecommendationContext) -> List[Recommendation]:
        """基于学习历史推荐"""
        recommendations = []
        
        if not self.command_learner:
            return recommendations
        
        # 获取学习建议
        suggestions = self.command_learner.get_command_suggestions(
            current_context=context.current_directory,
            recent_commands=context.recent_commands
        )
        
        for suggestion in suggestions[:5]:
            confidence = min(suggestion["priority"] / 10.0, 0.9)  # 转换为0-0.9的置信度
            
            recommendation = Recommendation(
                command=suggestion["command"],
                description=f"基于历史使用模式推荐的{suggestion['command']}命令",
                confidence=confidence,
                reason=f"学习推荐: {suggestion['reason']}",
                category="learning_based",
                parameters=self._get_common_parameters(suggestion["command"]),
                examples=self._get_command_examples(suggestion["command"]),
                risks=self._get_command_risks(suggestion["command"]),
                alternatives=self._get_command_alternatives(suggestion["command"])
            )
            
            recommendations.append(recommendation)
        
        return recommendations
    
    def _recommend_by_knowledge(self, context: RecommendationContext) -> List[Recommendation]:
        """基于知识库推荐"""
        recommendations = []
        
        if not self.knowledge_base:
            return recommendations
        
        # 从知识库搜索相关命令
        search_results = self.knowledge_base.search_commands(context.user_input)
        
        for result in search_results[:3]:
            confidence = result.get("relevance", 0.5)
            
            recommendation = Recommendation(
                command=result["command"],
                description=result.get("description", f"{result['command']}命令"),
                confidence=confidence,
                reason="基于知识库匹配",
                category=result.get("category", "general"),
                parameters=result.get("parameters", []),
                examples=result.get("examples", []),
                risks=result.get("risks", []),
                alternatives=result.get("alternatives", [])
            )
            
            recommendations.append(recommendation)
        
        return recommendations
    
    def _recommend_by_context(self, context: RecommendationContext) -> List[Recommendation]:
        """基于上下文推荐"""
        recommendations = []
        
        # 分析当前目录
        directory_recommendations = self._analyze_directory_context(context)
        recommendations.extend(directory_recommendations)
        
        # 分析系统状态
        system_recommendations = self._analyze_system_context(context)
        recommendations.extend(system_recommendations)
        
        # 分析命令序列
        sequence_recommendations = self._analyze_command_sequence(context)
        recommendations.extend(sequence_recommendations)
        
        return recommendations
    
    def _analyze_directory_context(self, context: RecommendationContext) -> List[Recommendation]:
        """分析目录上下文"""
        recommendations = []
        current_dir = context.current_directory.lower()
        
        # 基于目录特征推荐命令
        if "git" in current_dir or ".git" in current_dir:
            git_commands = ["git status", "git add", "git commit", "git push", "git pull"]
            for cmd in git_commands:
                recommendations.append(Recommendation(
                    command=cmd.split()[0],
                    description=f"Git仓库中常用的{cmd}命令",
                    confidence=0.6,
                    reason="检测到Git仓库目录",
                    category="development",
                    parameters=[cmd.split()[1]] if len(cmd.split()) > 1 else [],
                    examples=[cmd],
                    risks=[],
                    alternatives=[]
                ))
        
        if "log" in current_dir:
            log_commands = ["tail", "grep", "less", "cat"]
            for cmd in log_commands:
                recommendations.append(Recommendation(
                    command=cmd,
                    description=f"日志目录中常用的{cmd}命令",
                    confidence=0.5,
                    reason="检测到日志目录",
                    category="text_processing",
                    parameters=self._get_common_parameters(cmd),
                    examples=self._get_command_examples(cmd),
                    risks=self._get_command_risks(cmd),
                    alternatives=self._get_command_alternatives(cmd)
                ))
        
        return recommendations
    
    def _analyze_system_context(self, context: RecommendationContext) -> List[Recommendation]:
        """分析系统状态上下文"""
        recommendations = []
        system_status = context.system_status
        
        # 基于系统状态推荐
        if system_status.get("cpu_percent", 0) > 80:
            high_cpu_commands = ["top", "htop", "ps", "kill"]
            for cmd in high_cpu_commands:
                recommendations.append(Recommendation(
                    command=cmd,
                    description=f"高CPU使用率时的{cmd}命令",
                    confidence=0.8,
                    reason="检测到高CPU使用率",
                    category="system_monitoring",
                    parameters=self._get_common_parameters(cmd),
                    examples=self._get_command_examples(cmd),
                    risks=self._get_command_risks(cmd),
                    alternatives=self._get_command_alternatives(cmd)
                ))
        
        if system_status.get("memory_percent", 0) > 85:
            memory_commands = ["free", "top", "ps"]
            for cmd in memory_commands:
                recommendations.append(Recommendation(
                    command=cmd,
                    description=f"高内存使用率时的{cmd}命令",
                    confidence=0.8,
                    reason="检测到高内存使用率",
                    category="system_monitoring",
                    parameters=self._get_common_parameters(cmd),
                    examples=self._get_command_examples(cmd),
                    risks=self._get_command_risks(cmd),
                    alternatives=self._get_command_alternatives(cmd)
                ))
        
        return recommendations
    
    def _analyze_command_sequence(self, context: RecommendationContext) -> List[Recommendation]:
        """分析命令序列"""
        recommendations = []
        
        if not context.recent_commands:
            return recommendations
        
        last_command = context.recent_commands[-1].split()[0] if context.recent_commands else ""
        
        # 定义常见的命令序列
        command_sequences = {
            "ls": ["cd", "cat", "vim", "rm", "cp"],
            "cd": ["ls", "pwd", "find"],
            "git": ["git add", "git commit", "git push"],
            "find": ["grep", "xargs", "exec"],
            "ps": ["kill", "top", "grep"],
            "tar": ["gzip", "mv", "cp"],
            "wget": ["chmod", "tar", "unzip"],
            "make": ["make install", "make clean"],
            "docker": ["docker run", "docker exec", "docker logs"]
        }
        
        if last_command in command_sequences:
            for next_cmd in command_sequences[last_command][:3]:
                recommendations.append(Recommendation(
                    command=next_cmd.split()[0],
                    description=f"通常在{last_command}之后使用的{next_cmd}命令",
                    confidence=0.6,
                    reason=f"基于命令序列: {last_command} -> {next_cmd}",
                    category="sequence_based",
                    parameters=next_cmd.split()[1:] if len(next_cmd.split()) > 1 else [],
                    examples=[next_cmd],
                    risks=self._get_command_risks(next_cmd.split()[0]),
                    alternatives=self._get_command_alternatives(next_cmd.split()[0])
                ))
        
        return recommendations
    
    def _get_common_parameters(self, command: str) -> List[str]:
        """获取命令的常用参数"""
        parameter_map = {
            "ls": ["-l", "-a", "-la", "-h"],
            "grep": ["-r", "-i", "-n", "-v"],
            "find": ["-name", "-type", "-exec"],
            "tar": ["-xvf", "-cvf", "-zvf"],
            "ps": ["-ef", "-aux", "-f"],
            "chmod": ["+x", "755", "644"],
            "git": ["add", "commit", "push", "pull", "status"],
            "docker": ["run", "exec", "logs", "ps"]
        }
        
        return parameter_map.get(command, [])
    
    def _get_command_examples(self, command: str) -> List[str]:
        """获取命令示例"""
        example_map = {
            "ls": ["ls -la", "ls -lh /home"],
            "grep": ["grep -r 'pattern' .", "grep -i 'text' file.txt"],
            "find": ["find . -name '*.txt'", "find /path -type f"],
            "tar": ["tar -xvf file.tar", "tar -cvf archive.tar files/"],
            "ps": ["ps -ef | grep process", "ps aux"],
            "git": ["git status", "git add .", "git commit -m 'message'"]
        }
        
        return example_map.get(command, [f"{command} [参数]"])
    
    def _get_command_risks(self, command: str) -> List[str]:
        """获取命令风险"""
        risk_map = {
            "rm": ["永久删除文件", "无法恢复"],
            "chmod": ["可能影响文件权限", "可能导致安全问题"],
            "sudo": ["需要管理员权限", "可能影响系统"],
            "dd": ["可能覆盖重要数据", "操作不可逆"],
            "mkfs": ["将格式化磁盘", "所有数据将丢失"]
        }
        
        return risk_map.get(command, [])
    
    def _get_command_alternatives(self, command: str) -> List[str]:
        """获取命令替代方案"""
        alternative_map = {
            "vim": ["nano", "emacs"],
            "cat": ["less", "more"],
            "ps": ["top", "htop"],
            "grep": ["awk", "sed"],
            "wget": ["curl"],
            "tar": ["zip", "7z"]
        }
        
        return alternative_map.get(command, [])
    
    def _deduplicate_and_rank(self, recommendations: List[Recommendation]) -> List[Recommendation]:
        """去重和排序推荐结果"""
        # 按命令去重，保留置信度最高的
        unique_recommendations = {}
        
        for rec in recommendations:
            if rec.command not in unique_recommendations or rec.confidence > unique_recommendations[rec.command].confidence:
                unique_recommendations[rec.command] = rec
        
        # 按置信度排序
        sorted_recommendations = sorted(
            unique_recommendations.values(),
            key=lambda x: x.confidence,
            reverse=True
        )
        
        return sorted_recommendations
    
    def explain_recommendation(self, recommendation: Recommendation, context: RecommendationContext) -> Dict[str, Any]:
        """解释推荐原因"""
        explanation = {
            "command": recommendation.command,
            "why_recommended": recommendation.reason,
            "confidence_score": recommendation.confidence,
            "context_analysis": {
                "user_input": context.user_input,
                "detected_intent": context.intent,
                "current_directory": context.current_directory,
                "recent_commands": context.recent_commands[-3:] if context.recent_commands else []
            },
            "command_info": {
                "description": recommendation.description,
                "category": recommendation.category,
                "common_parameters": recommendation.parameters,
                "usage_examples": recommendation.examples,
                "potential_risks": recommendation.risks,
                "alternatives": recommendation.alternatives
            }
        }
        
        return explanation
    
    def get_recommendation_stats(self) -> Dict[str, Any]:
        """获取推荐统计信息"""
        stats = {
            "engine_version": "1.0.0",
            "supported_categories": list(self.command_categories.keys()),
            "intent_patterns": len(self.intent_patterns),
            "context_weights": self.context_weights,
            "has_learning_data": self.command_learner is not None,
            "has_knowledge_base": self.knowledge_base is not None
        }
        
        return stats 