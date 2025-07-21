#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Linux知识库
存储Linux命令文档、最佳实践和常见问题解决方案
"""

import json
import os
import re
import time
import logging
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict
from collections import defaultdict


@dataclass
class CommandInfo:
    """命令信息"""
    name: str
    category: str
    description: str
    syntax: str
    parameters: List[Dict[str, str]]
    examples: List[Dict[str, str]]
    use_cases: List[str]
    risks: List[str]
    alternatives: List[str]
    related_commands: List[str]
    man_page: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CommandInfo':
        """从字典创建"""
        return cls(**data)


@dataclass
class BestPractice:
    """最佳实践"""
    id: str
    title: str
    description: str
    category: str
    commands: List[str]
    steps: List[str]
    tips: List[str]
    warnings: List[str]
    tags: List[str]
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)


@dataclass
class TroubleshootingGuide:
    """故障排除指南"""
    id: str
    problem: str
    symptoms: List[str]
    causes: List[str]
    solutions: List[Dict[str, Any]]
    prevention: List[str]
    related_commands: List[str]
    tags: List[str]
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)


class KnowledgeBase:
    """Linux知识库"""
    
    def __init__(self, data_dir: str = None):
        """
        初始化知识库
        
        Args:
            data_dir: 数据目录路径
        """
        self.data_dir = data_dir or os.path.expanduser("~/.linuxagent_knowledge")
        self.logger = logging.getLogger(__name__)
        
        # 确保数据目录存在
        os.makedirs(self.data_dir, exist_ok=True)
        
        # 知识库数据
        self.commands: Dict[str, CommandInfo] = {}
        self.best_practices: Dict[str, BestPractice] = {}
        self.troubleshooting_guides: Dict[str, TroubleshootingGuide] = {}
        
        # 索引
        self.category_index: Dict[str, List[str]] = defaultdict(list)
        self.tag_index: Dict[str, List[str]] = defaultdict(list)
        self.keyword_index: Dict[str, List[str]] = defaultdict(list)
        
        # 加载数据
        self._load_builtin_knowledge()
        self._load_user_knowledge()
        self._build_indexes()
        
        self.logger.info(f"知识库初始化完成，包含{len(self.commands)}个命令")
    
    def _load_builtin_knowledge(self) -> None:
        """加载内置知识"""
        # 基础命令知识
        builtin_commands = self._get_builtin_commands()
        for cmd_data in builtin_commands:
            cmd_info = CommandInfo.from_dict(cmd_data)
            self.commands[cmd_info.name] = cmd_info
        
        # 最佳实践
        builtin_practices = self._get_builtin_best_practices()
        for practice_data in builtin_practices:
            practice = BestPractice(**practice_data)
            self.best_practices[practice.id] = practice
        
        # 故障排除指南
        builtin_guides = self._get_builtin_troubleshooting()
        for guide_data in builtin_guides:
            guide = TroubleshootingGuide(**guide_data)
            self.troubleshooting_guides[guide.id] = guide
    
    def _get_builtin_commands(self) -> List[Dict[str, Any]]:
        """获取内置命令知识"""
        return [
            {
                "name": "ls",
                "category": "file_operations",
                "description": "列出目录内容",
                "syntax": "ls [选项] [目录...]",
                "parameters": [
                    {"flag": "-l", "description": "使用长格式显示详细信息"},
                    {"flag": "-a", "description": "显示所有文件，包括隐藏文件"},
                    {"flag": "-h", "description": "以人类可读的格式显示大小"},
                    {"flag": "-t", "description": "按修改时间排序"},
                    {"flag": "-r", "description": "逆序排列"}
                ],
                "examples": [
                    {"command": "ls -la", "description": "详细列出所有文件"},
                    {"command": "ls -lh", "description": "以可读格式显示文件大小"},
                    {"command": "ls -lt", "description": "按时间排序显示文件"}
                ],
                "use_cases": ["查看目录内容", "检查文件权限", "查找文件"],
                "risks": [],
                "alternatives": ["dir", "tree"],
                "related_commands": ["cd", "pwd", "find", "tree"]
            },
            {
                "name": "grep",
                "category": "text_processing",
                "description": "在文件中搜索文本模式",
                "syntax": "grep [选项] 模式 [文件...]",
                "parameters": [
                    {"flag": "-r", "description": "递归搜索目录"},
                    {"flag": "-i", "description": "忽略大小写"},
                    {"flag": "-n", "description": "显示行号"},
                    {"flag": "-v", "description": "显示不匹配的行"},
                    {"flag": "-c", "description": "只显示匹配行的数量"}
                ],
                "examples": [
                    {"command": "grep -r 'error' /var/log/", "description": "在日志目录中搜索错误"},
                    {"command": "grep -i 'warning' file.txt", "description": "忽略大小写搜索警告"},
                    {"command": "ps aux | grep nginx", "description": "搜索nginx进程"}
                ],
                "use_cases": ["日志分析", "查找文本", "过滤输出"],
                "risks": [],
                "alternatives": ["awk", "sed", "rg"],
                "related_commands": ["find", "sed", "awk", "cut"]
            },
            {
                "name": "find",
                "category": "file_operations",
                "description": "查找文件和目录",
                "syntax": "find [路径] [表达式]",
                "parameters": [
                    {"flag": "-name", "description": "按文件名搜索"},
                    {"flag": "-type", "description": "按文件类型搜索 (f=文件, d=目录)"},
                    {"flag": "-size", "description": "按文件大小搜索"},
                    {"flag": "-mtime", "description": "按修改时间搜索"},
                    {"flag": "-exec", "description": "对找到的文件执行命令"}
                ],
                "examples": [
                    {"command": "find . -name '*.txt'", "description": "查找所有txt文件"},
                    {"command": "find /home -type d -name 'test'", "description": "查找名为test的目录"},
                    {"command": "find . -size +100M", "description": "查找大于100MB的文件"}
                ],
                "use_cases": ["查找文件", "批量操作", "系统清理"],
                "risks": ["可能影响系统性能"],
                "alternatives": ["locate", "whereis", "which"],
                "related_commands": ["ls", "grep", "xargs", "exec"]
            },
            {
                "name": "ps",
                "category": "system_monitoring",
                "description": "显示运行中的进程",
                "syntax": "ps [选项]",
                "parameters": [
                    {"flag": "aux", "description": "显示所有用户的所有进程"},
                    {"flag": "-ef", "description": "显示完整格式的所有进程"},
                    {"flag": "-u", "description": "显示指定用户的进程"},
                    {"flag": "--sort", "description": "按指定字段排序"}
                ],
                "examples": [
                    {"command": "ps aux", "description": "显示所有进程"},
                    {"command": "ps -ef | grep nginx", "description": "查找nginx进程"},
                    {"command": "ps aux --sort=-%cpu", "description": "按CPU使用率排序"}
                ],
                "use_cases": ["监控进程", "查找进程", "性能分析"],
                "risks": [],
                "alternatives": ["top", "htop", "pgrep"],
                "related_commands": ["top", "kill", "jobs", "nohup"]
            },
            {
                "name": "chmod",
                "category": "permission_management",
                "description": "修改文件和目录权限",
                "syntax": "chmod [选项] 模式 文件...",
                "parameters": [
                    {"flag": "-R", "description": "递归修改目录及其内容的权限"},
                    {"flag": "+x", "description": "添加执行权限"},
                    {"flag": "755", "description": "所有者读写执行，组和其他用户读执行"},
                    {"flag": "644", "description": "所有者读写，组和其他用户只读"}
                ],
                "examples": [
                    {"command": "chmod +x script.sh", "description": "给脚本添加执行权限"},
                    {"command": "chmod 755 directory/", "description": "设置目录权限"},
                    {"command": "chmod -R 644 *.txt", "description": "递归设置txt文件权限"}
                ],
                "use_cases": ["设置文件权限", "修复权限问题", "安全管理"],
                "risks": ["可能导致安全问题", "可能使文件无法访问"],
                "alternatives": ["chown", "chgrp"],
                "related_commands": ["chown", "chgrp", "umask", "ls"]
            },
            {
                "name": "tar",
                "category": "archive",
                "description": "创建和解压归档文件",
                "syntax": "tar [选项] [归档文件] [文件...]",
                "parameters": [
                    {"flag": "-c", "description": "创建归档"},
                    {"flag": "-x", "description": "解压归档"},
                    {"flag": "-v", "description": "显示详细信息"},
                    {"flag": "-f", "description": "指定归档文件名"},
                    {"flag": "-z", "description": "使用gzip压缩"}
                ],
                "examples": [
                    {"command": "tar -czf backup.tar.gz /home/user/", "description": "创建压缩备份"},
                    {"command": "tar -xzf archive.tar.gz", "description": "解压缩文件"},
                    {"command": "tar -tf archive.tar", "description": "查看归档内容"}
                ],
                "use_cases": ["文件备份", "文件传输", "压缩存储"],
                "risks": ["可能覆盖现有文件"],
                "alternatives": ["zip", "7z", "gzip"],
                "related_commands": ["gzip", "zip", "unzip", "compress"]
            },
            {
                "name": "git",
                "category": "development",
                "description": "版本控制系统",
                "syntax": "git [命令] [选项]",
                "parameters": [
                    {"flag": "status", "description": "查看仓库状态"},
                    {"flag": "add", "description": "添加文件到暂存区"},
                    {"flag": "commit", "description": "提交更改"},
                    {"flag": "push", "description": "推送到远程仓库"},
                    {"flag": "pull", "description": "从远程仓库拉取"}
                ],
                "examples": [
                    {"command": "git status", "description": "查看仓库状态"},
                    {"command": "git add .", "description": "添加所有更改"},
                    {"command": "git commit -m 'message'", "description": "提交更改"},
                    {"command": "git push origin main", "description": "推送到主分支"}
                ],
                "use_cases": ["版本控制", "代码管理", "协作开发"],
                "risks": ["可能丢失未提交的更改"],
                "alternatives": ["svn", "hg"],
                "related_commands": ["diff", "patch", "make"]
            }
        ]
    
    def _get_builtin_best_practices(self) -> List[Dict[str, Any]]:
        """获取内置最佳实践"""
        return [
            {
                "id": "file_backup",
                "title": "文件备份最佳实践",
                "description": "如何安全有效地备份重要文件",
                "category": "file_management",
                "commands": ["tar", "rsync", "cp"],
                "steps": [
                    "确定需要备份的文件和目录",
                    "选择合适的备份位置",
                    "使用tar创建压缩归档",
                    "验证备份完整性",
                    "定期测试恢复过程"
                ],
                "tips": [
                    "使用增量备份节省空间",
                    "保持多个备份版本",
                    "将备份存储在不同位置"
                ],
                "warnings": [
                    "备份前确保有足够的存储空间",
                    "定期验证备份的完整性"
                ],
                "tags": ["backup", "safety", "files"]
            },
            {
                "id": "log_analysis",
                "title": "日志分析最佳实践",
                "description": "如何有效分析系统日志",
                "category": "system_monitoring",
                "commands": ["grep", "tail", "awk", "sed"],
                "steps": [
                    "确定日志文件位置",
                    "使用tail监控实时日志",
                    "使用grep过滤相关条目",
                    "统计错误和警告数量",
                    "分析趋势和模式"
                ],
                "tips": [
                    "使用grep的-A和-B选项查看上下文",
                    "结合多个工具进行复杂分析",
                    "定期清理旧日志文件"
                ],
                "warnings": [
                    "大日志文件可能影响性能",
                    "注意日志文件的权限设置"
                ],
                "tags": ["logs", "monitoring", "troubleshooting"]
            },
            {
                "id": "permission_security",
                "title": "文件权限安全实践",
                "description": "如何正确设置和管理文件权限",
                "category": "security",
                "commands": ["chmod", "chown", "umask"],
                "steps": [
                    "了解权限数字和符号表示法",
                    "设置适当的默认权限",
                    "定期审查敏感文件权限",
                    "使用最小权限原则",
                    "监控权限变更"
                ],
                "tips": [
                    "对脚本文件使用755权限",
                    "对配置文件使用644权限",
                    "敏感文件使用600权限"
                ],
                "warnings": [
                    "避免使用777权限",
                    "小心递归权限修改",
                    "注意SUID和SGID权限"
                ],
                "tags": ["security", "permissions", "files"]
            }
        ]
    
    def _get_builtin_troubleshooting(self) -> List[Dict[str, Any]]:
        """获取内置故障排除指南"""
        return [
            {
                "id": "high_cpu_usage",
                "problem": "CPU使用率过高",
                "symptoms": [
                    "系统响应缓慢",
                    "风扇噪音增大",
                    "应用程序卡顿"
                ],
                "causes": [
                    "后台进程占用资源",
                    "无限循环或死锁",
                    "系统负载过重",
                    "恶意软件"
                ],
                "solutions": [
                    {
                        "step": "识别高CPU进程",
                        "commands": ["top", "htop", "ps aux --sort=-%cpu"],
                        "description": "使用系统监控工具找出占用CPU的进程"
                    },
                    {
                        "step": "分析进程行为",
                        "commands": ["strace", "lsof"],
                        "description": "深入分析问题进程的行为"
                    },
                    {
                        "step": "终止问题进程",
                        "commands": ["kill", "killall"],
                        "description": "安全地终止占用过多资源的进程"
                    }
                ],
                "prevention": [
                    "定期监控系统性能",
                    "设置资源限制",
                    "及时更新系统和软件"
                ],
                "related_commands": ["top", "ps", "kill", "nice"],
                "tags": ["performance", "cpu", "monitoring"]
            },
            {
                "id": "disk_space_full",
                "problem": "磁盘空间不足",
                "symptoms": [
                    "系统提示磁盘空间不足",
                    "无法创建新文件",
                    "应用程序无法启动"
                ],
                "causes": [
                    "日志文件过大",
                    "临时文件积累",
                    "大文件未清理",
                    "数据库文件增长"
                ],
                "solutions": [
                    {
                        "step": "检查磁盘使用情况",
                        "commands": ["df -h", "du -sh /*"],
                        "description": "查看各分区和目录的空间使用情况"
                    },
                    {
                        "step": "找出大文件",
                        "commands": ["find / -size +100M", "du -ah / | sort -rh"],
                        "description": "定位占用空间较大的文件"
                    },
                    {
                        "step": "清理不需要的文件",
                        "commands": ["rm", "find . -name '*.tmp' -delete"],
                        "description": "删除临时文件和不需要的数据"
                    }
                ],
                "prevention": [
                    "定期清理临时文件",
                    "设置日志轮转",
                    "监控磁盘使用率"
                ],
                "related_commands": ["df", "du", "find", "rm"],
                "tags": ["storage", "cleanup", "maintenance"]
            }
        ]
    
    def _load_user_knowledge(self) -> None:
        """加载用户自定义知识"""
        # 尝试加载用户自定义的命令、最佳实践和故障排除指南
        for filename, data_dict, loader_func in [
            ("commands.json", self.commands, lambda x: CommandInfo.from_dict(x)),
            ("practices.json", self.best_practices, lambda x: BestPractice(**x)),
            ("troubleshooting.json", self.troubleshooting_guides, lambda x: TroubleshootingGuide(**x))
        ]:
            file_path = os.path.join(self.data_dir, filename)
            if os.path.exists(file_path):
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        user_data = json.load(f)
                    
                    for key, item_data in user_data.items():
                        data_dict[key] = loader_func(item_data)
                    
                    self.logger.info(f"加载用户知识: {filename}")
                except Exception as e:
                    self.logger.error(f"加载{filename}失败: {e}")
    
    def _build_indexes(self) -> None:
        """构建搜索索引"""
        # 构建分类索引
        for cmd_name, cmd_info in self.commands.items():
            self.category_index[cmd_info.category].append(cmd_name)
        
        for practice_id, practice in self.best_practices.items():
            self.category_index[practice.category].append(practice_id)
        
        # 构建标签索引
        for practice_id, practice in self.best_practices.items():
            for tag in practice.tags:
                self.tag_index[tag].append(practice_id)
        
        for guide_id, guide in self.troubleshooting_guides.items():
            for tag in guide.tags:
                self.tag_index[tag].append(guide_id)
        
        # 构建关键词索引
        for cmd_name, cmd_info in self.commands.items():
            # 索引命令名、描述和用例
            keywords = [cmd_name, cmd_info.description] + cmd_info.use_cases
            for keyword in keywords:
                words = re.findall(r'\w+', keyword.lower())
                for word in words:
                    if len(word) > 2:  # 忽略太短的词
                        self.keyword_index[word].append(cmd_name)
    
    def search_commands(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        搜索命令
        
        Args:
            query: 搜索查询
            limit: 结果数量限制
            
        Returns:
            搜索结果列表
        """
        results = []
        query_lower = query.lower()
        query_words = re.findall(r'\w+', query_lower)
        
        # 精确匹配命令名
        if query_lower in self.commands:
            cmd_info = self.commands[query_lower]
            results.append({
                "command": cmd_info.name,
                "description": cmd_info.description,
                "category": cmd_info.category,
                "relevance": 1.0,
                "parameters": [p["flag"] for p in cmd_info.parameters],
                "examples": [e["command"] for e in cmd_info.examples],
                "risks": cmd_info.risks,
                "alternatives": cmd_info.alternatives
            })
        
        # 关键词匹配
        for word in query_words:
            if word in self.keyword_index:
                for cmd_name in self.keyword_index[word]:
                    if cmd_name not in [r["command"] for r in results]:
                        cmd_info = self.commands[cmd_name]
                        relevance = self._calculate_relevance(query_words, cmd_info)
                        results.append({
                            "command": cmd_info.name,
                            "description": cmd_info.description,
                            "category": cmd_info.category,
                            "relevance": relevance,
                            "parameters": [p["flag"] for p in cmd_info.parameters],
                            "examples": [e["command"] for e in cmd_info.examples],
                            "risks": cmd_info.risks,
                            "alternatives": cmd_info.alternatives
                        })
        
        # 描述和用例模糊匹配
        for cmd_name, cmd_info in self.commands.items():
            if cmd_name not in [r["command"] for r in results]:
                text_to_search = f"{cmd_info.description} {' '.join(cmd_info.use_cases)}".lower()
                if any(word in text_to_search for word in query_words):
                    relevance = self._calculate_relevance(query_words, cmd_info) * 0.7
                    results.append({
                        "command": cmd_info.name,
                        "description": cmd_info.description,
                        "category": cmd_info.category,
                        "relevance": relevance,
                        "parameters": [p["flag"] for p in cmd_info.parameters],
                        "examples": [e["command"] for e in cmd_info.examples],
                        "risks": cmd_info.risks,
                        "alternatives": cmd_info.alternatives
                    })
        
        # 按相关性排序
        results.sort(key=lambda x: x["relevance"], reverse=True)
        
        return results[:limit]
    
    def _calculate_relevance(self, query_words: List[str], cmd_info: CommandInfo) -> float:
        """计算相关性分数"""
        score = 0.0
        total_text = f"{cmd_info.name} {cmd_info.description} {' '.join(cmd_info.use_cases)}".lower()
        
        for word in query_words:
            if word in cmd_info.name.lower():
                score += 1.0  # 命令名匹配权重最高
            elif word in cmd_info.description.lower():
                score += 0.7  # 描述匹配
            elif any(word in use_case.lower() for use_case in cmd_info.use_cases):
                score += 0.5  # 用例匹配
        
        # 归一化分数
        return min(score / len(query_words), 1.0)
    
    def get_command_info(self, command: str) -> Optional[CommandInfo]:
        """获取命令详细信息"""
        return self.commands.get(command)
    
    def get_best_practices(self, category: str = None, tags: List[str] = None) -> List[BestPractice]:
        """
        获取最佳实践
        
        Args:
            category: 分类筛选
            tags: 标签筛选
            
        Returns:
            最佳实践列表
        """
        practices = list(self.best_practices.values())
        
        if category:
            practices = [p for p in practices if p.category == category]
        
        if tags:
            practices = [p for p in practices if any(tag in p.tags for tag in tags)]
        
        return practices
    
    def get_troubleshooting_guides(self, problem_keywords: str = None) -> List[TroubleshootingGuide]:
        """
        获取故障排除指南
        
        Args:
            problem_keywords: 问题关键词
            
        Returns:
            故障排除指南列表
        """
        guides = list(self.troubleshooting_guides.values())
        
        if problem_keywords:
            keywords = problem_keywords.lower()
            guides = [
                g for g in guides 
                if keywords in g.problem.lower() or 
                any(keywords in symptom.lower() for symptom in g.symptoms)
            ]
        
        return guides
    
    def add_command(self, command_info: CommandInfo) -> bool:
        """
        添加自定义命令
        
        Args:
            command_info: 命令信息
            
        Returns:
            是否成功
        """
        try:
            self.commands[command_info.name] = command_info
            self._save_user_commands()
            self._build_indexes()  # 重建索引
            self.logger.info(f"添加命令: {command_info.name}")
            return True
        except Exception as e:
            self.logger.error(f"添加命令失败: {e}")
            return False
    
    def add_best_practice(self, practice: BestPractice) -> bool:
        """
        添加最佳实践
        
        Args:
            practice: 最佳实践
            
        Returns:
            是否成功
        """
        try:
            self.best_practices[practice.id] = practice
            self._save_user_practices()
            self._build_indexes()
            self.logger.info(f"添加最佳实践: {practice.id}")
            return True
        except Exception as e:
            self.logger.error(f"添加最佳实践失败: {e}")
            return False
    
    def _save_user_commands(self) -> None:
        """保存用户自定义命令"""
        user_commands = {
            name: cmd.to_dict() 
            for name, cmd in self.commands.items() 
            if name not in [c["name"] for c in self._get_builtin_commands()]
        }
        
        if user_commands:
            file_path = os.path.join(self.data_dir, "commands.json")
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(user_commands, f, indent=2, ensure_ascii=False)
    
    def _save_user_practices(self) -> None:
        """保存用户自定义最佳实践"""
        builtin_ids = [p["id"] for p in self._get_builtin_best_practices()]
        user_practices = {
            pid: practice.to_dict() 
            for pid, practice in self.best_practices.items() 
            if pid not in builtin_ids
        }
        
        if user_practices:
            file_path = os.path.join(self.data_dir, "practices.json")
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(user_practices, f, indent=2, ensure_ascii=False)
    
    def get_knowledge_stats(self) -> Dict[str, Any]:
        """获取知识库统计信息"""
        return {
            "total_commands": len(self.commands),
            "total_practices": len(self.best_practices),
            "total_guides": len(self.troubleshooting_guides),
            "categories": list(self.category_index.keys()),
            "tags": list(self.tag_index.keys()),
            "indexed_keywords": len(self.keyword_index)
        }
    
    def export_knowledge(self, file_path: str) -> bool:
        """
        导出知识库
        
        Args:
            file_path: 导出文件路径
            
        Returns:
            是否成功
        """
        try:
            export_data = {
                "commands": {name: cmd.to_dict() for name, cmd in self.commands.items()},
                "best_practices": {pid: practice.to_dict() for pid, practice in self.best_practices.items()},
                "troubleshooting_guides": {gid: guide.to_dict() for gid, guide in self.troubleshooting_guides.items()},
                "export_time": time.time(),
                "stats": self.get_knowledge_stats()
            }
            
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, indent=2, ensure_ascii=False)
            
            self.logger.info(f"知识库导出到: {file_path}")
            return True
            
        except Exception as e:
            self.logger.error(f"导出知识库失败: {e}")
            return False 