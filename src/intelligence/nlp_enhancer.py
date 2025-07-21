#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
自然语言增强器
改进用户输入理解，将自然语言描述转换为具体的Linux命令
"""

import re
import logging
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from collections import defaultdict


@dataclass
class LanguagePattern:
    """语言模式"""
    pattern: str
    command_template: str
    confidence: float
    parameters: List[str]
    examples: List[str]
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "pattern": self.pattern,
            "command_template": self.command_template,
            "confidence": self.confidence,
            "parameters": self.parameters,
            "examples": self.examples
        }


@dataclass
class TranslationResult:
    """翻译结果"""
    original_input: str
    translated_command: str
    confidence: float
    explanation: str
    alternative_commands: List[str]
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "original_input": self.original_input,
            "translated_command": self.translated_command,
            "confidence": self.confidence,
            "explanation": self.explanation,
            "alternative_commands": self.alternative_commands
        }


class NLPEnhancer:
    """自然语言增强器"""
    
    def __init__(self):
        """初始化NLP增强器"""
        self.logger = logging.getLogger(__name__)
        
        # 语言模式
        self.language_patterns = self._build_language_patterns()
        
        # 参数提取模式
        self.parameter_patterns = self._build_parameter_patterns()
        
        # 同义词映射
        self.synonyms = self._build_synonyms()
        
        # 常见错误映射
        self.common_mistakes = self._build_common_mistakes()
        
        self.logger.info("自然语言增强器初始化完成")
    
    def _build_language_patterns(self) -> List[LanguagePattern]:
        """构建语言模式"""
        return [
            # 文件操作模式
            LanguagePattern(
                pattern=r"(?:显示|查看|列出)(?:.*?)(?:文件|目录|内容)",
                command_template="ls {path}",
                confidence=0.9,
                parameters=["{path}"],
                examples=["显示当前目录文件", "查看/home目录内容"]
            ),
            LanguagePattern(
                pattern=r"(?:复制|拷贝)(?:.*?)文件",
                command_template="cp {source} {destination}",
                confidence=0.85,
                parameters=["{source}", "{destination}"],
                examples=["复制文件到备份目录", "拷贝配置文件"]
            ),
            LanguagePattern(
                pattern=r"(?:删除|移除)(?:.*?)(?:文件|目录)",
                command_template="rm {options} {path}",
                confidence=0.8,
                parameters=["{options}", "{path}"],
                examples=["删除临时文件", "移除空目录"]
            ),
            LanguagePattern(
                pattern=r"(?:创建|新建)(?:.*?)(?:文件|目录)",
                command_template="mkdir -p {path}",
                confidence=0.85,
                parameters=["{path}"],
                examples=["创建新目录", "新建项目文件夹"]
            ),
            LanguagePattern(
                pattern=r"(?:查找|搜索)(?:.*?)文件",
                command_template="find {path} -name '{filename}'",
                confidence=0.8,
                parameters=["{path}", "{filename}"],
                examples=["查找所有txt文件", "搜索配置文件"]
            ),
            
            # 文本处理模式
            LanguagePattern(
                pattern=r"(?:搜索|查找)(?:.*?)(?:文本|内容|字符串)",
                command_template="grep {options} '{pattern}' {file}",
                confidence=0.85,
                parameters=["{options}", "{pattern}", "{file}"],
                examples=["搜索日志中的错误", "查找配置文件中的设置"]
            ),
            LanguagePattern(
                pattern=r"(?:查看|显示)(?:.*?)(?:日志|文件内容)",
                command_template="cat {file}",
                confidence=0.8,
                parameters=["{file}"],
                examples=["查看系统日志", "显示配置文件内容"]
            ),
            LanguagePattern(
                pattern=r"(?:监控|实时查看)(?:.*?)(?:日志|文件)",
                command_template="tail -f {file}",
                confidence=0.9,
                parameters=["{file}"],
                examples=["监控Apache日志", "实时查看系统日志"]
            ),
            
            # 系统监控模式
            LanguagePattern(
                pattern=r"(?:查看|检查|显示)(?:.*?)(?:进程|运行的程序)",
                command_template="ps aux",
                confidence=0.9,
                parameters=[],
                examples=["查看所有进程", "检查运行的程序"]
            ),
            LanguagePattern(
                pattern=r"(?:查看|检查)(?:.*?)(?:CPU|处理器|系统性能)",
                command_template="top",
                confidence=0.85,
                parameters=[],
                examples=["查看CPU使用率", "检查系统性能"]
            ),
            LanguagePattern(
                pattern=r"(?:查看|检查)(?:.*?)(?:内存|RAM)",
                command_template="free -h",
                confidence=0.85,
                parameters=[],
                examples=["查看内存使用情况", "检查RAM状态"]
            ),
            LanguagePattern(
                pattern=r"(?:查看|检查)(?:.*?)(?:磁盘|硬盘|存储)(?:.*?)(?:空间|使用)",
                command_template="df -h",
                confidence=0.85,
                parameters=[],
                examples=["查看磁盘空间", "检查硬盘使用情况"]
            ),
            
            # 网络操作模式
            LanguagePattern(
                pattern=r"(?:测试|检查)(?:.*?)(?:网络连接|连通性)",
                command_template="ping {host}",
                confidence=0.85,
                parameters=["{host}"],
                examples=["测试网络连接", "检查服务器连通性"]
            ),
            LanguagePattern(
                pattern=r"(?:下载|获取)(?:.*?)文件",
                command_template="wget {url}",
                confidence=0.8,
                parameters=["{url}"],
                examples=["下载软件包", "获取配置文件"]
            ),
            
            # 权限管理模式
            LanguagePattern(
                pattern=r"(?:修改|设置|更改)(?:.*?)(?:权限|访问权限)",
                command_template="chmod {permissions} {file}",
                confidence=0.8,
                parameters=["{permissions}", "{file}"],
                examples=["修改文件权限", "设置脚本执行权限"]
            ),
            LanguagePattern(
                pattern=r"(?:更改|修改)(?:.*?)(?:所有者|拥有者)",
                command_template="chown {owner} {file}",
                confidence=0.8,
                parameters=["{owner}", "{file}"],
                examples=["更改文件所有者", "修改目录拥有者"]
            ),
            
            # 压缩解压模式
            LanguagePattern(
                pattern=r"(?:压缩|打包)(?:.*?)(?:文件|目录)",
                command_template="tar -czf {archive}.tar.gz {source}",
                confidence=0.8,
                parameters=["{archive}", "{source}"],
                examples=["压缩备份文件", "打包项目目录"]
            ),
            LanguagePattern(
                pattern=r"(?:解压|提取)(?:.*?)(?:压缩包|归档)",
                command_template="tar -xzf {archive}",
                confidence=0.8,
                parameters=["{archive}"],
                examples=["解压软件包", "提取备份文件"]
            ),
            
            # 服务管理模式
            LanguagePattern(
                pattern=r"(?:启动|开启)(?:.*?)服务",
                command_template="sudo systemctl start {service}",
                confidence=0.8,
                parameters=["{service}"],
                examples=["启动Apache服务", "开启数据库服务"]
            ),
            LanguagePattern(
                pattern=r"(?:停止|关闭)(?:.*?)服务",
                command_template="sudo systemctl stop {service}",
                confidence=0.8,
                parameters=["{service}"],
                examples=["停止Apache服务", "关闭数据库服务"]
            ),
            LanguagePattern(
                pattern=r"(?:重启|重新启动)(?:.*?)服务",
                command_template="sudo systemctl restart {service}",
                confidence=0.8,
                parameters=["{service}"],
                examples=["重启Web服务", "重新启动数据库"]
            ),
            
            # Git操作模式
            LanguagePattern(
                pattern=r"(?:查看|检查)(?:.*?)(?:git|版本控制)(?:.*?)状态",
                command_template="git status",
                confidence=0.9,
                parameters=[],
                examples=["查看Git状态", "检查版本控制状态"]
            ),
            LanguagePattern(
                pattern=r"(?:提交|保存)(?:.*?)(?:更改|修改)",
                command_template="git add . && git commit -m '{message}'",
                confidence=0.8,
                parameters=["{message}"],
                examples=["提交代码更改", "保存项目修改"]
            ),
            LanguagePattern(
                pattern=r"(?:推送|上传)(?:.*?)(?:代码|更改)",
                command_template="git push origin main",
                confidence=0.8,
                parameters=[],
                examples=["推送代码到仓库", "上传更改到远程"]
            )
        ]
    
    def _build_parameter_patterns(self) -> Dict[str, List[str]]:
        """构建参数提取模式"""
        return {
            "file_path": [
                r"(?:路径|目录|文件夹)[:：]?\s*([^\s]+)",
                r"在\s*([^\s]+)\s*(?:中|里|目录)",
                r"(?:/[^\s]*)",
                r"(?:~/[^\s]*)",
                r"(?:\./[^\s]*)",
                r"(?:\.\.[^\s]*)"
            ],
            "filename": [
                r"(?:文件名|名称)[:：]?\s*([^\s]+)",
                r"(?:叫|名为|称为)\s*([^\s]+)",
                r"([^\s]+\.(?:txt|log|conf|cfg|ini|json|xml|py|sh|js|css|html))"
            ],
            "pattern": [
                r"(?:模式|匹配|包含)[:：]?\s*['\"]([^'\"]+)['\"]",
                r"(?:搜索|查找)\s*['\"]([^'\"]+)['\"]",
                r"['\"]([^'\"]+)['\"]"
            ],
            "host": [
                r"(?:主机|服务器|地址)[:：]?\s*([^\s]+)",
                r"(?:ping|连接)\s+([^\s]+)",
                r"(\d+\.\d+\.\d+\.\d+)",
                r"([a-zA-Z0-9\-\.]+\.[a-zA-Z]{2,})"
            ],
            "service": [
                r"(?:服务|进程)[:：]?\s*([^\s]+)",
                r"(?:apache|nginx|mysql|postgresql|redis|mongodb|docker|ssh)",
                r"([a-zA-Z0-9\-_]+)(?:\.service)?"
            ],
            "permissions": [
                r"(?:权限|模式)[:：]?\s*(\d{3,4})",
                r"((?:[rwx-]{9})|(?:\d{3,4}))",
                r"(?:755|644|600|777|chmod\s+(\d{3,4}))"
            ]
        }
    
    def _build_synonyms(self) -> Dict[str, List[str]]:
        """构建同义词映射"""
        return {
            "显示": ["查看", "列出", "展示", "打印"],
            "删除": ["移除", "清除", "去掉", "删掉"],
            "复制": ["拷贝", "备份", "复制到"],
            "创建": ["新建", "建立", "生成", "创造"],
            "查找": ["搜索", "寻找", "定位", "找到"],
            "修改": ["更改", "改变", "变更", "调整"],
            "启动": ["开启", "开始", "运行", "激活"],
            "停止": ["关闭", "结束", "终止", "停下"],
            "文件": ["文档", "数据", "资料"],
            "目录": ["文件夹", "路径", "位置"],
            "进程": ["程序", "任务", "应用"],
            "服务": ["守护进程", "后台程序"],
            "权限": ["访问权限", "文件权限", "权限设置"],
            "网络": ["网络连接", "连接", "网络状况"],
            "系统": ["操作系统", "电脑", "机器"],
            "日志": ["记录", "日志文件", "系统日志"]
        }
    
    def _build_common_mistakes(self) -> Dict[str, str]:
        """构建常见错误映射"""
        return {
            "ll": "ls -la",
            "dir": "ls",
            "copy": "cp",
            "move": "mv",
            "remove": "rm",
            "delete": "rm",
            "type": "cat",
            "cls": "clear",
            "md": "mkdir",
            "rd": "rmdir",
            "cd..": "cd ..",
            "cd/": "cd /",
            "grep -r": "grep -r",
            "find -name": "find . -name",
            "ps -ef | grep": "ps aux | grep"
        }
    
    def translate_to_command(self, user_input: str) -> TranslationResult:
        """
        将自然语言输入翻译为Linux命令
        
        Args:
            user_input: 用户自然语言输入
            
        Returns:
            翻译结果
        """
        # 清理和预处理输入
        cleaned_input = self._preprocess_input(user_input)
        
        # 检查常见错误
        corrected_input = self._correct_common_mistakes(cleaned_input)
        if corrected_input != cleaned_input:
            return TranslationResult(
                original_input=user_input,
                translated_command=corrected_input,
                confidence=0.95,
                explanation=f"纠正了常见命令错误: {cleaned_input} -> {corrected_input}",
                alternative_commands=[]
            )
        
        # 尝试模式匹配
        best_match = None
        best_confidence = 0.0
        
        for pattern in self.language_patterns:
            match = re.search(pattern.pattern, cleaned_input, re.IGNORECASE)
            if match:
                confidence = pattern.confidence
                
                # 提取参数
                parameters = self._extract_parameters(cleaned_input, pattern.parameters)
                
                # 生成命令
                command = self._generate_command(pattern.command_template, parameters)
                
                if confidence > best_confidence:
                    best_confidence = confidence
                    best_match = {
                        "pattern": pattern,
                        "parameters": parameters,
                        "command": command
                    }
        
        if best_match:
            # 生成替代命令
            alternatives = self._generate_alternatives(best_match["command"], best_match["pattern"])
            
            return TranslationResult(
                original_input=user_input,
                translated_command=best_match["command"],
                confidence=best_confidence,
                explanation=f"基于模式匹配: {best_match['pattern'].pattern}",
                alternative_commands=alternatives
            )
        
        # 如果没有匹配，尝试关键词分析
        keyword_result = self._analyze_keywords(cleaned_input)
        if keyword_result:
            return keyword_result
        
        # 返回默认结果
        return TranslationResult(
            original_input=user_input,
            translated_command="# 未能理解的命令",
            confidence=0.0,
            explanation="无法解析的自然语言输入",
            alternative_commands=["help", "man"]
        )
    
    def _preprocess_input(self, text: str) -> str:
        """预处理输入文本"""
        # 转换为小写
        text = text.lower().strip()
        
        # 移除多余的空格
        text = re.sub(r'\s+', ' ', text)
        
        # 处理中文标点
        text = text.replace('，', ',').replace('。', '.').replace('？', '?').replace('！', '!')
        
        # 同义词替换
        for word, synonyms in self.synonyms.items():
            for synonym in synonyms:
                text = text.replace(synonym, word)
        
        return text
    
    def _correct_common_mistakes(self, text: str) -> str:
        """纠正常见错误"""
        for mistake, correction in self.common_mistakes.items():
            if text.strip() == mistake:
                return correction
        return text
    
    def _extract_parameters(self, text: str, parameter_names: List[str]) -> Dict[str, str]:
        """从文本中提取参数"""
        parameters = {}
        
        for param_name in parameter_names:
            param_key = param_name.strip('{}')
            
            if param_key in self.parameter_patterns:
                for pattern in self.parameter_patterns[param_key]:
                    match = re.search(pattern, text)
                    if match:
                        parameters[param_key] = match.group(1) if match.groups() else match.group(0)
                        break
            
            # 如果没有找到特定参数，尝试通用提取
            if param_key not in parameters:
                parameters[param_key] = self._extract_generic_parameter(text, param_key)
        
        return parameters
    
    def _extract_generic_parameter(self, text: str, param_type: str) -> str:
        """通用参数提取"""
        if param_type == "path":
            # 查找路径相关信息
            path_matches = re.findall(r'[/~\.][^\s]*', text)
            return path_matches[0] if path_matches else "."
        
        elif param_type == "file":
            # 查找文件名
            file_matches = re.findall(r'\S+\.\w+', text)
            return file_matches[0] if file_matches else "*"
        
        elif param_type == "options":
            # 查找选项
            if "递归" in text or "目录" in text:
                return "-r"
            elif "详细" in text or "冗长" in text:
                return "-v"
            elif "强制" in text:
                return "-f"
            else:
                return ""
        
        return ""
    
    def _generate_command(self, template: str, parameters: Dict[str, str]) -> str:
        """生成命令"""
        command = template
        
        for param_key, param_value in parameters.items():
            placeholder = "{" + param_key + "}"
            command = command.replace(placeholder, param_value)
        
        # 清理多余的空格和占位符
        command = re.sub(r'\s+', ' ', command).strip()
        command = re.sub(r'\{[^}]*\}', '', command)  # 移除未替换的占位符
        
        return command
    
    def _generate_alternatives(self, command: str, pattern: LanguagePattern) -> List[str]:
        """生成替代命令"""
        alternatives = []
        base_command = command.split()[0]
        
        # 基于命令类型生成替代方案
        alternative_map = {
            "ls": ["tree", "find", "dir"],
            "cat": ["less", "more", "head", "tail"],
            "grep": ["awk", "sed", "rg"],
            "find": ["locate", "whereis", "which"],
            "ps": ["top", "htop", "pgrep"],
            "cp": ["rsync", "mv"],
            "rm": ["mv ... /tmp", "trash"],
            "tar": ["zip", "7z", "gzip"],
            "wget": ["curl", "lynx"],
            "top": ["htop", "atop", "iotop"]
        }
        
        if base_command in alternative_map:
            alternatives.extend(alternative_map[base_command])
        
        return alternatives[:3]  # 返回前3个替代方案
    
    def _analyze_keywords(self, text: str) -> Optional[TranslationResult]:
        """基于关键词分析生成命令"""
        keywords = text.split()
        
        # 定义关键词到命令的映射
        keyword_commands = {
            "help": "man",
            "manual": "man",
            "清屏": "clear",
            "清除": "clear",
            "历史": "history",
            "时间": "date",
            "日期": "date",
            "日历": "cal",
            "用户": "whoami",
            "当前目录": "pwd",
            "工作目录": "pwd",
            "磁盘": "df -h",
            "内存": "free -h",
            "CPU": "top",
            "进程": "ps aux",
            "网络": "netstat -tuln",
            "环境变量": "env",
            "路径": "echo $PATH"
        }
        
        for keyword, command in keyword_commands.items():
            if keyword in text:
                return TranslationResult(
                    original_input=text,
                    translated_command=command,
                    confidence=0.6,
                    explanation=f"基于关键词匹配: {keyword}",
                    alternative_commands=[]
                )
        
        return None
    
    def enhance_command_input(self, command_input: str) -> Dict[str, Any]:
        """
        增强命令输入
        
        Args:
            command_input: 命令输入
            
        Returns:
            增强结果
        """
        result = {
            "original": command_input,
            "suggestions": [],
            "corrections": [],
            "explanations": []
        }
        
        # 检查常见拼写错误
        corrections = self._check_spelling(command_input)
        if corrections:
            result["corrections"] = corrections
        
        # 提供命令建议
        suggestions = self._suggest_improvements(command_input)
        if suggestions:
            result["suggestions"] = suggestions
        
        # 提供解释
        explanation = self._explain_command(command_input)
        if explanation:
            result["explanations"] = [explanation]
        
        return result
    
    def _check_spelling(self, command: str) -> List[str]:
        """检查拼写错误"""
        corrections = []
        
        for mistake, correction in self.common_mistakes.items():
            if mistake in command:
                corrected = command.replace(mistake, correction)
                corrections.append(corrected)
        
        return corrections
    
    def _suggest_improvements(self, command: str) -> List[str]:
        """建议改进"""
        suggestions = []
        
        # 建议添加有用的选项
        if command.startswith("ls") and "-l" not in command:
            suggestions.append(command + " -la")
        
        if command.startswith("grep") and "-r" not in command:
            suggestions.append(command + " -r")
        
        if command.startswith("rm") and "-i" not in command:
            suggestions.append(command.replace("rm", "rm -i"))
        
        return suggestions
    
    def _explain_command(self, command: str) -> str:
        """解释命令"""
        explanations = {
            "ls": "列出目录内容",
            "cat": "显示文件内容",
            "grep": "搜索文本模式",
            "find": "查找文件和目录",
            "ps": "显示运行进程",
            "top": "显示系统进程",
            "df": "显示磁盘空间使用情况",
            "free": "显示内存使用情况",
            "chmod": "修改文件权限",
            "chown": "修改文件所有者",
            "tar": "压缩和解压文件",
            "wget": "下载文件",
            "curl": "传输数据"
        }
        
        base_command = command.split()[0]
        return explanations.get(base_command, "")
    
    def get_usage_examples(self, command: str) -> List[Dict[str, str]]:
        """获取使用示例"""
        examples = {
            "ls": [
                {"command": "ls -la", "description": "详细列出所有文件"},
                {"command": "ls -lh", "description": "以人类可读格式显示文件大小"},
                {"command": "ls -lt", "description": "按修改时间排序"}
            ],
            "grep": [
                {"command": "grep -r 'pattern' .", "description": "递归搜索当前目录"},
                {"command": "grep -i 'text' file.txt", "description": "忽略大小写搜索"},
                {"command": "ps aux | grep nginx", "description": "搜索nginx进程"}
            ],
            "find": [
                {"command": "find . -name '*.txt'", "description": "查找所有txt文件"},
                {"command": "find /home -type d", "description": "查找所有目录"},
                {"command": "find . -size +100M", "description": "查找大于100MB的文件"}
            ]
        }
        
        return examples.get(command, [])
    
    def get_enhancement_stats(self) -> Dict[str, Any]:
        """获取增强器统计信息"""
        return {
            "language_patterns": len(self.language_patterns),
            "parameter_patterns": len(self.parameter_patterns),
            "synonyms": len(self.synonyms),
            "common_mistakes": len(self.common_mistakes),
            "supported_languages": ["中文", "英文"]
        } 