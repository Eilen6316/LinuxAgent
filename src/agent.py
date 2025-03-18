#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
核心代理模块
负责协调用户界面、LLM API和命令执行组件
"""

import os
import sys
import time
import logging
import re
import json
from typing import List, Dict, Any, Optional, Tuple, Union

from .config import Config
from .interfaces.user_interface import UserInterface
from .interfaces.llm_provider import LLMProvider
from .interfaces.command_executor import CommandExecutorInterface

from .providers.deepseek import DeepSeekProvider
from .providers.openai import OpenAIProvider
from .executors.linux_command import LinuxCommandExecutor
from .ui.console import ConsoleUI
from rich.panel import Panel


class Agent:
    """LinuxAgent代理类"""
    
    def __init__(self, config: Config, logger=None):
        """初始化代理"""
        self.config = config
        self.logger = logger or logging.getLogger("agent")
        
        # 初始化UI
        self.ui = self._create_ui(config.ui)
        
        if hasattr(self.ui, 'initial_panel_height'):
            current_height = self.ui.initial_panel_height
            if 28 <= current_height <= 32:
                self.logger.info(f"检测到面板高度({current_height})接近可能导致卡顿的临界值，自动调整为25")
                self.ui.initial_panel_height = 25
        
        # 初始化LLM提供者
        self.api = self._create_llm_provider(config.api)
        
        # 初始化命令执行器
        self.executor = self._create_command_executor(config.security)
        
        # 操作历史
        self.history = []
        
        # 对话历史，用于多轮对话
        self.chat_history = []
        self.max_chat_history = 20  # 保留最近20轮对话
        self.chat_history_file = os.path.expanduser("~/.linuxagent_chat_history.json")
        self._load_chat_history()
        
        # 工作模式：auto(自动判断), chat(问答模式), agent(命令执行模式)
        self.working_mode = "auto"
        
        # 统计信息
        self.stats_file = os.path.expanduser("~/.linuxagent_stats.json")
        self.stats = self._load_stats()
        
        # 命令推荐系统
        self.command_history_file = os.path.expanduser("~/.linuxagent_command_history.json")
        self.command_history = self._load_command_history()
        self.enable_recommendations = getattr(config, 'enable_recommendations', True)
        
        # 使用分析
        self.analytics_file = os.path.expanduser("~/.linuxagent_analytics.json")
        self.analytics_data = self._load_analytics_data()
        self.collect_analytics = getattr(config, 'collect_analytics', True)
        self.detailed_stats = getattr(config, 'detailed_stats', False)
        
        # 性能基准测试
        self.enable_benchmarking = getattr(config, 'enable_benchmarking', False)
        self.benchmark_file = os.path.expanduser("~/.linuxagent_benchmarks.json")
        self.benchmarks = self._load_benchmarks()
        
        self._check_api_availability()
    
    def _create_ui(self, ui_config) -> UserInterface:
        """创建用户界面"""
        self.logger.info("初始化用户界面")
        return ConsoleUI(ui_config)
    
    def _create_llm_provider(self, api_config) -> LLMProvider:
        """创建LLM提供者"""
        self.logger.info(f"初始化LLM提供者: {api_config.provider}")
        
        if api_config.provider.lower() == 'deepseek':
            return DeepSeekProvider(api_config, logger=self.logger)
        elif api_config.provider.lower() == 'openai':
            return OpenAIProvider(api_config, logger=self.logger)
        else:
            self.logger.warning(f"未知的LLM提供者: {api_config.provider}，使用默认的DeepSeek")
            return DeepSeekProvider(api_config, logger=self.logger)
    
    def _create_command_executor(self, security_config) -> CommandExecutorInterface:
        """创建命令执行器"""
        self.logger.info("初始化命令执行器")
        return LinuxCommandExecutor(security_config, logger=self.logger)
    
    def _check_api_availability(self) -> bool:
        """检查API是否可用"""
        self.logger.info(f"检查LLM API可用性")
        
        is_available = self.api.is_available()
        if not is_available:
            self.logger.error("LLM API不可用")
            self.ui.show_error("LLM API连接失败，请检查网络和API密钥")
            return False
            
        self.logger.info("LLM API可用")
        return True
    
    def _load_chat_history(self) -> None:
        """加载对话历史"""
        if os.path.exists(self.chat_history_file):
            try:
                with open(self.chat_history_file, 'r', encoding='utf-8') as f:
                    self.chat_history = json.load(f)
                self.logger.info(f"成功加载对话历史，共{len(self.chat_history)}条记录")
                
                if len(self.chat_history) > self.max_chat_history * 2:
                    self.chat_history = self.chat_history[-(self.max_chat_history * 2):]
                    self.logger.info(f"对话历史过长，截取最近{len(self.chat_history)}条记录")
            except Exception as e:
                self.logger.error(f"加载对话历史失败: {e}")
                self.chat_history = []
        else:
            self.logger.info("对话历史文件不存在，使用空历史")
            self.chat_history = []
            
    def _save_chat_history(self) -> None:
        """保存对话历史"""
        try:
            with open(self.chat_history_file, 'w', encoding='utf-8') as f:
                json.dump(self.chat_history, f, ensure_ascii=False, indent=2)
            self.logger.info(f"成功保存对话历史，共{len(self.chat_history)}条记录")
        except Exception as e:
            self.logger.error(f"保存对话历史失败: {e}")
    
    def _handle_special_commands(self, user_input: str) -> bool:
        """处理特殊命令"""
        if user_input.lower() in ["exit", "quit", "bye"]:
            self.logger.info("用户请求退出")
            return True
            
        elif user_input.lower() == "help":
            self.logger.info("显示帮助信息")
            self.ui.show_help()
            return True
            
        elif user_input.lower() == "clear":
            self.logger.info("清屏")
            self.ui.clear_screen()
            return True
            
        elif user_input.lower() == "history":
            self.logger.info("显示历史记录")
            history_entries = [entry["user_input"] for entry in self.history]
            self.ui.show_history(history_entries)
            return True
            
        elif user_input.lower() == "config":
            self.logger.info("显示配置信息")
            self.ui.show_config(self.config.to_dict())
            return True
            
        elif user_input.lower() == "stats":
            self.logger.info("显示统计信息")
            self._show_stats()
            return True
            
        elif user_input.lower() == "analytics" or user_input.lower() == "dashboard":
            self.logger.info("显示使用分析仪表板")
            self.show_analytics_dashboard()
            return True
        
        elif user_input.lower() == "chat history":
            self.logger.info("显示对话历史")
            self._show_chat_history()
            return True
            
        elif user_input.lower() == "clear chat":
            self.logger.info("清除对话历史")
            self.chat_history = []
            self._save_chat_history()
            self.ui.console.print("[bold green]对话历史已清除[/bold green]")
            return True
            
        elif user_input.lower() == "save chat":
            self.logger.info("保存对话历史")
            self._save_chat_history()
            self.ui.console.print("[bold green]对话历史已保存[/bold green]")
            return True
            
        elif user_input.lower() == "settings" or user_input.lower() == "set":
            self.logger.info("调整设置")
            self._adjust_settings()
            return True
            
        elif user_input.lower().startswith("set api_key "):
            self.logger.info("设置API密钥")
            parts = user_input.split(" ", 2)
            if len(parts) == 3:
                api_key = parts[2].strip()
                if api_key:
                    # 设置内存中的API密钥
                    self.config.api.api_key = api_key
                    
                    # 保存到配置文件
                    self._save_config_to_file(quiet=True)
                    
                    # 屏蔽显示部分密钥
                    masked_key = api_key[:4] + '*' * (len(api_key) - 8) + api_key[-4:] if len(api_key) > 8 else "****"
                    self.ui.console.print(f"[bold green]API密钥已设置为 {masked_key} 并保存到配置文件[/bold green]")
                else:
                    self.ui.console.print("[bold red]API密钥不能为空[/bold red]")
            else:
                self.ui.console.print("[bold yellow]用法: set api_key YOUR_API_KEY[/bold yellow]")
            return True
            
        elif user_input.lower() == "theme":
            self.logger.info("自定义主题")
            self.ui.show_theme_settings()
            return True
            
        elif user_input.lower().startswith("language"):
            # 新增命令：设置语言
            parts = user_input.split(" ", 1)
            lang_code = parts[1] if len(parts) > 1 else ""
            self._set_language(lang_code)
            return True
            
        elif user_input.lower() == "chat mode":
            # 新增命令：切换到ChatAI模式（问答模式）
            self.logger.info("切换到ChatAI模式")
            self.working_mode = "chat"
            self.ui.console.print("[bold green]已切换到[/bold green] [bold cyan]ChatAI模式[/bold cyan] - 所有输入都会以问答方式处理")
            return True
            
        elif user_input.lower() == "agent mode":
            # 新增命令：切换到AgentAI模式（命令执行模式）
            self.logger.info("切换到AgentAI模式")
            self.working_mode = "agent"
            self.ui.console.print("[bold green]已切换到[/bold green] [bold cyan]AgentAI模式[/bold cyan] - 所有输入都会尝试解析为命令执行")
            return True
            
        elif user_input.lower() == "auto mode":
            # 新增命令：切换到自动模式
            self.logger.info("切换到自动模式")
            self.working_mode = "auto"
            self.ui.console.print("[bold green]已切换到[/bold green] [bold cyan]自动模式[/bold cyan] - 系统将自动判断输入类型")
            return True
            
        elif user_input.lower() == "mode":
            # 新增命令：显示当前模式
            mode_desc = {
                "auto": "自动模式 - 系统自动判断输入类型",
                "chat": "ChatAI模式 - 所有输入都以问答方式处理",
                "agent": "AgentAI模式 - 所有输入都尝试解析为命令执行"
            }
            self.ui.console.print(f"[bold green]当前工作模式:[/bold green] [bold cyan]{mode_desc.get(self.working_mode, '未知模式')}[/bold cyan]")
            return True
            
        elif user_input.lower() == "tutorial":
            # 新增命令：启动交互式教程
            self.logger.info("启动交互式教程")
            self.ui.start_tutorial()
            return True
            
        elif user_input.lower().startswith("export chat"):
            # 新增命令：导出对话历史
            parts = user_input.split(" ", 3)
            
            # 如果只输入了export chat，提供一个交互式菜单
            if len(parts) <= 2:
                self.logger.info("显示导出对话菜单")
                
                from rich.table import Table
                
                table = Table(title="导出对话历史")
                table.add_column("选项", style="cyan", justify="center")
                table.add_column("格式", style="green")
                table.add_column("说明", style="white")
                
                table.add_row("1", "Markdown (md)", "导出为Markdown格式，适合阅读")
                table.add_row("2", "文本 (txt)", "导出为纯文本格式")
                table.add_row("3", "脚本 (sh)", "导出为可执行Shell脚本，提取命令")
                
                self.ui.console.print(table)
                self.ui.console.print("\n[bold]请选择导出格式编号:[/bold]")
                
                choice = self.ui.get_input("导出格式 > ")
                
                format_map = {
                    "1": "markdown",
                    "2": "text",
                    "3": "script"
                }
                
                if choice in format_map:
                    format_type = format_map[choice]
                    output_file = f"linuxagent_chat_{int(time.time())}"
                    self.logger.info(f"导出对话历史为{format_type}格式")
                    self._export_chat_history(format_type, output_file)
                else:
                    self.ui.console.print("[bold yellow]无效的选择，已取消导出[/bold yellow]")
            else:
                # 原有的解析逻辑
                format_type = parts[2] if len(parts) > 2 else "markdown"
                output_file = parts[3] if len(parts) > 3 else f"linuxagent_chat_{int(time.time())}"
                
                if format_type not in ["markdown", "md", "text", "txt", "script", "sh"]:
                    self.ui.console.print("[bold yellow]支持的导出格式: markdown/md, text/txt, script/sh[/bold yellow]")
                    format_type = "markdown"
                
                self._export_chat_history(format_type, output_file)
            
            return True
            
        elif user_input.lower().startswith("chat"):
            # 处理chat命令，进入聊天模式
            parts = user_input.split(" ", 1)
            question = parts[1] if len(parts) > 1 else ""
            
            if not question:
                self.ui.console.print("[bold yellow]请在chat后面输入您想询问的内容[/bold yellow]")
                return True
            
            self._handle_question_mode(question)
            return True
            
        elif user_input.lower().startswith("edit "):
            parts = user_input.split(" ", 2)
            file_path = parts[1] if len(parts) > 1 else ""
            editor = parts[2] if len(parts) > 2 else "vim"
            
            if not file_path:
                self.ui.show_error("请指定要编辑的文件路径")
                return True
                
            self.logger.info(f"使用 {editor} 编辑文件: {file_path}")
            self.ui.console.print(f"[bold]正在使用 {editor} 编辑文件: [/bold][yellow]{file_path}[/yellow]")
            
            stdout, stderr, return_code = self.executor.execute_file_editor(file_path, editor)
            
            if return_code == 0:
                self.ui.console.print("[bold green]文件编辑完成[/bold green]")
            else:
                self.ui.show_error(f"编辑文件时出错: {stderr}")
                
            return True
            
        return False
    
    def _is_question_mode(self, user_input: str) -> bool:
        """判断是否是问答模式"""
        always_stream = getattr(self.config.ui, 'always_stream', True)
        
        command_prefixes = ["ls", "cd", "rm", "cp", "mv", "mkdir", "touch", "cat", "grep", 
                           "find", "ps", "top", "df", "du", "chmod", "chown", "kill", 
                           "tar", "zip", "unzip", "ping", "sudo", "apt", "yum", "dnf", "pacman"]
        
        if user_input.lower().startswith("chat "):
            return True
            
        first_word = user_input.split()[0].lower() if user_input.split() else ""
        if first_word in command_prefixes:
            return False 
            
        agent_action_indicators = [
            "执行", "运行", "帮我执行", "帮我运行", "帮我查", "请执行", "请运行", 
            "执行命令", "运行命令", "查看", "检查", "显示", "列出", "统计", "获取",
            "run", "execute", "check", "list", "show", "get"
        ]
        
        if any(indicator in user_input.lower() for indicator in agent_action_indicators):
            return False  
        
        question_indicators = ["是什么", "什么是", "如何", "怎么", "解释", "说明",
                             "为什么", "区别", "比较", "展示", "tell me", 
                             "what is", "how to", "explain", "difference between",
                             "请问", "help", "帮助", "能否", "可以", "吗", "?", "？"]
        
        if user_input.endswith("?") or user_input.endswith("？"):
            return True

        is_question = any(indicator in user_input.lower() for indicator in question_indicators)
        
        if always_stream and not is_question:
            self.logger.info(f"全局流式回答模式：将输入 '{user_input}' 作为问题处理")
            return True
            
        return is_question

    def _handle_question_mode(self, user_input: str) -> None:
        """处理问答模式，使用流式输出"""
        self.logger.info("进入问答模式，使用流式输出")
        
        # 更新统计信息
        self.stats["questions_answered"] += 1
        
        system_info = self.executor.get_system_info()
        
        # 将用户输入添加到对话历史
        self.chat_history.append({"role": "user", "content": user_input})
        
        # 限制历史记录长度，防止过长
        if len(self.chat_history) > self.max_chat_history * 2:  
            # 保留system消息和最近的历史
            messages_to_keep = self.max_chat_history * 2
            self.chat_history = self.chat_history[-messages_to_keep:]
            
        # 构建消息，包含历史记录
        messages = [
            {"role": "system", "content": "你是一个Linux专家助手，提供关于Linux系统、命令和运维的专业解答。回答要简洁、准确，并尽可能给出实用的命令示例。同时记住用户之前的提问和你的回答，保持连贯性。\n\n系统信息：" + json.dumps(system_info, ensure_ascii=False)}
        ]
        
        # 添加对话历史
        messages.extend(self.chat_history)
        
        self.ui.console.print("[bold cyan]正在生成流式回答...[/bold cyan]")
        
        if self.enable_benchmarking:
            start_time = time.time()
        
        try:
            if not hasattr(self.api, 'stream_response') or not callable(getattr(self.api, 'stream_response')):
                self.logger.warning("当前API提供者不支持流式输出，将使用普通响应")
                self.ui.show_error("流式输出不可用，将使用普通响应")
                response = self.api.generate_command(user_input, system_info)
                
                if self.collect_analytics:
                    self.analytics_data["api_calls"]["total"] += 1
                    if response:
                        self.analytics_data["api_calls"]["successful"] += 1
                    else:
                        self.analytics_data["api_calls"]["failed"] += 1
                    self._save_analytics_data()
                
                if self.enable_benchmarking:
                    api_response_time = time.time() - start_time
                    self._record_api_benchmark("question_answering", api_response_time)
                
                if response and "explanation" in response:
                    response_text = response["explanation"]
                    
                    self._display_segmented_text(response_text)
                    self.chat_history.append({"role": "assistant", "content": response_text})
                return
                
            # 获取流式响应
            response_generator = self.api.stream_response(messages)
            full_response = ""
            
            def response_collector():
                nonlocal full_response
                chunk_counter = 0
                empty_chunk_count = 0
                start_time = time.time()
                buffer = ""
                buffer_size_threshold = getattr(self.config.ui, 'buffer_size', 100)
                buffer_time_threshold = 0.2  
                last_yield_time = time.time()
                line_count = 0  
                critical_line_range = range(28, 33)  
                
                try:
                    for chunk in response_generator:
                        chunk_counter += 1

                        if not chunk:
                            empty_chunk_count += 1
                            if empty_chunk_count >= 5:
                                empty_chunk_count = 0
                                if buffer:
                                    yield buffer
                                    buffer = ""
                                    last_yield_time = time.time()
                                yield "."
                            continue
                            
                        empty_chunk_count = 0
                        full_response += chunk
                        buffer += chunk
                        buffer_lines = buffer.count('\n') + 1
                        line_count += buffer_lines
                        approaching_critical = line_count in critical_line_range
                        
                        current_time = time.time()
                        # 当缓冲区达到阈值或时间超过阈值时才输出
                        # 或者接近临界行数时提前输出，避免卡顿
                        if (len(buffer) >= buffer_size_threshold or 
                            current_time - last_yield_time >= buffer_time_threshold or
                            approaching_critical):
                            
                            if approaching_critical:
                                buffer += "\n "
                                self.logger.debug(f"检测到接近临界行数({line_count})，添加额外行避开卡顿")
                            
                            yield buffer
                            line_count = 0
                            buffer = ""
                            last_yield_time = current_time
                        
                        if chunk_counter % 50 == 0:
                            elapsed = time.time() - start_time
                            self.logger.debug(f"已接收 {chunk_counter} 个数据块，耗时: {elapsed:.2f}秒")
                            
                    if buffer:
                        yield buffer
                        
                except Exception as e:
                    self.logger.error(f"流式响应收集器异常: {str(e)}", exc_info=True)
                    error_msg = f"\n\n[响应收集出错: {str(e)}]"
                    full_response += error_msg
                    yield error_msg
            
            self.ui.stream_output(response_collector())
            
            if self.enable_benchmarking:
                api_response_time = time.time() - start_time
                self._record_api_benchmark("question_answering", api_response_time)
            
            if self.collect_analytics:
                self.analytics_data["api_calls"]["total"] += 1
                self.analytics_data["api_calls"]["successful"] += 1
                self._save_analytics_data()
            
            if full_response:
                if len(full_response) > 5000:
                    self.ui.console.print("\n[bold yellow]完整回答较长，您是否需要以分段方式再次查看完整内容?[/bold yellow]")
                    if self.ui.confirm("[bold]再次查看完整内容?[/bold]"):
                        self.ui.console.print("\n[bold green]完整回答内容:[/bold green]")
                        self._display_segmented_text(full_response)
                        
                self.chat_history.append({"role": "assistant", "content": full_response})
                self.logger.info(f"添加对话历史，当前历史长度: {len(self.chat_history)}")
            
        except Exception as e:
            self.logger.error(f"流式输出失败: {e}", exc_info=True)
            self.ui.show_error(f"生成回答时出错: {e}")
            
            if self.collect_analytics:
                self.analytics_data["api_calls"]["total"] += 1
                self.analytics_data["api_calls"]["failed"] += 1
                self._save_analytics_data()
            
            try:
                self.logger.info("尝试使用普通响应作为备选")
                
                if self.enable_benchmarking:
                    backup_start_time = time.time()
                    
                response = self.api.generate_command(user_input, system_info)
                
                if self.enable_benchmarking:
                    api_response_time = time.time() - backup_start_time
                    self._record_api_benchmark("question_answering", api_response_time)
                
                if response and "explanation" in response:
                    response_text = response["explanation"]
                    self.ui.console.print("\n[bold yellow]流式输出失败，使用备选响应:[/bold yellow]")
                    self.ui.console.print(response_text)
                    # 添加助手回复到对话历史
                    self.chat_history.append({"role": "assistant", "content": response_text})
                    
                    # 更新API调用统计
                    if self.collect_analytics:
                        self.analytics_data["api_calls"]["successful"] += 1  # 备选成功
                        self._save_analytics_data()
                
            except Exception as backup_error:
                self.logger.error(f"备选响应也失败: {backup_error}")
                self.ui.show_error("无法生成回答，请检查网络连接和API配置")
    
    def process_user_input(self, user_input: str) -> None:
        """处理用户输入"""
        self.logger.info(f"处理用户输入: {user_input}")
        
        self.history.append({
            "user_input": user_input,
            "timestamp": time.time()
        })
        
        if self._handle_special_commands(user_input):
            return
        
        self.chat_history.append({"role": "user", "content": user_input})
        
        if len(self.chat_history) > self.max_chat_history * 2: 
            self.chat_history = self.chat_history[-self.max_chat_history * 2:]

        if self.enable_recommendations:
            recommendations = self.get_command_recommendations(user_input)
            if recommendations:
                self.show_command_recommendations(recommendations)
        
        # 根据设定的工作模式判断处理方式
        if self.working_mode == "chat":
            # 强制ChatAI模式
            self._handle_question_mode(user_input)
            return
        elif self.working_mode == "agent":
            # 强制AgentAI模式
            # 跳过问答模式检查，直接进入命令生成逻辑
            pass
        else:  # auto模式，自动判断
            # 检查是否是问答模式
            if self._is_question_mode(user_input):
                self._handle_question_mode(user_input)
                return
        
        self.ui.show_thinking()
        
        try:
            system_info = self.executor.get_system_info()           
            simple_commands = ["ls", "pwd", "cd", "cat", "echo", "mkdir", "touch", "cp", "mv", "rm", "ps", "df", "du", "grep", "find", "top"]
            command_parts = user_input.split()
            if command_parts and command_parts[0] in simple_commands:
                self.logger.info(f"识别为简单系统命令: {user_input}")
                command = user_input
                explanation = f"执行{command_parts[0]}命令"
                self.ui.console.print(f"[bold]理解:[/bold] {explanation}")
                self.ui.console.print(f"[bold]要执行的命令:[/bold] [yellow]{command}[/yellow]")
                
                is_interactive = self._is_interactive_command(command)
                is_safe, unsafe_reason = self.executor.is_command_safe(command)
                
                if not is_safe and self.config.security.confirm_dangerous_commands:
                    confirmation_message = f"此命令可能有风险: {unsafe_reason}。确认执行?"
                    if not self.ui.confirm(confirmation_message):
                        self.logger.info("用户取消执行危险命令")
                        self.ui.console.print("[bold red]已取消执行[/bold red]")
                        assistant_response = f"命令 '{command}' 被用户拒绝执行，原因: {unsafe_reason}"
                        self.chat_history.append({"role": "assistant", "content": assistant_response})
                        self._save_chat_history()
                        return
                
                self.ui.console.print("[bold cyan]正在执行命令，这可能需要一些时间...[/bold cyan]")
                with self.ui.console.status("[bold green]命令执行中...[/bold green]", spinner="dots"):
                    stdout, stderr, return_code = self.executor.execute_command(command)
                
                self.stats["commands_executed"] += 1
                
                if return_code == 0:
                    self.ui.console.print("[bold green]命令执行成功！正在分析结果...[/bold green]")
                    analysis = self.api.analyze_output(command, stdout, stderr)
                    self.ui.show_result(analysis, command)
                    self.stats["successful_commands"] += 1
                    
                    success_response = f"命令执行成功:\n命令: {command}\n分析: {analysis.get('explanation', '')}"
                    if 'recommendations' in analysis and analysis['recommendations']:
                        success_response += "\n\n建议: " + "\n- ".join([""] + analysis['recommendations'])
                    self.chat_history.append({"role": "assistant", "content": success_response})
                    self._save_chat_history()
                else:
                    self.logger.warning(f"命令执行失败: {stderr}")
                    self.ui.console.print("[bold yellow]命令执行返回非零状态，正在分析问题...[/bold yellow]")
                    
                    # 询问用户是否需要分析错误
                    if self.ui.confirm("\n[bold]命令执行失败。需要分析错误原因吗?[/bold]"):
                        self.logger.info("用户请求分析命令执行错误")
                        analysis = self.api.analyze_output(command, stdout, stderr)
                        self.ui.show_result(analysis, command)
                        
                        # 将分析添加到对话历史
                        failure_response = f"命令执行失败:\n命令: {command}\n错误分析: {analysis.get('explanation', '')}"
                        self.chat_history.append({"role": "assistant", "content": failure_response})
                        
                        # 询问是否需要更详细的ChatAI模式分析
                        if self.ui.confirm("\n[bold]需要更详细的错误分析和解决方案吗?[/bold]"):
                            error_analysis_prompt = f"以下Linux命令执行失败，请详细分析错误原因并提供具体解决方案:\n命令: {command}\n错误输出: {stderr}"
                            self._handle_question_mode(error_analysis_prompt)
                            
                            # 询问是否根据分析结果修改命令重试
                            if self.ui.confirm("\n[bold]是否根据分析尝试修改命令并重新执行?[/bold]"):
                                self.ui.console.print("[bold cyan]请输入修改后的命令:[/bold cyan]")
                                modified_command = self.ui.get_input("[修改命令] > ")
                                if modified_command and modified_command.strip():
                                    # 递归调用处理修改后的命令
                                    self.process_user_input(modified_command)
                    else:
                        # 简单显示错误信息
                        self.ui.show_result(stderr, command)
                        # 将失败信息添加到对话历史
                        failure_response = f"命令执行失败:\n命令: {command}\n错误: {stderr[:1000]}" + ("..." if len(stderr) > 1000 else "")
                        self.chat_history.append({"role": "assistant", "content": failure_response})
                    
                    self.stats["failed_commands"] += 1
                    self._save_chat_history()
                return
            
            parsed_command = self._parse_create_edit_request(user_input)
            if parsed_command:
                self.logger.info(f"执行直接编辑/创建操作: {parsed_command}")
                self._execute_edit_operation(parsed_command)
                # 将文件编辑操作添加到对话历史
                assistant_response = f"已执行文件编辑操作: {parsed_command}"
                self.chat_history.append({"role": "assistant", "content": assistant_response})
                self._save_chat_history()
                return
            
            interactive_command = self._parse_interactive_command(user_input)
            if interactive_command:
                self.logger.info(f"直接执行交互式命令: {interactive_command}")
                self._execute_interactive_operation(interactive_command)
                # 将交互式命令添加到对话历史
                assistant_response = f"已执行交互式命令: {interactive_command}"
                self.chat_history.append({"role": "assistant", "content": assistant_response})
                self._save_chat_history()
                return
            
            # 使用流式输出生成命令
            # 为命令生成建立上下文，包含对话历史
            command_context_messages = [
                {"role": "system", "content": 
                    "你是一个Linux命令生成助手，帮助用户将自然语言转换为准确的Linux命令。" +
                    "可以返回单个命令或命令序列。以JSON格式返回，格式如下：\n" +
                    "单个命令格式：{\"command\": \"具体命令\", \"explanation\": \"命令说明\", \"dangerous\": true/false, \"reason_if_dangerous\": \"危险原因\"}\n" +
                    "命令序列格式：{\"commands\": [{\"command\": \"命令1\", \"explanation\": \"说明1\"}, {\"command\": \"命令2\", \"explanation\": \"说明2\"}]}\n" +
                    "只返回JSON，不要有其他内容。\n\n系统信息：" + 
                    json.dumps(system_info, ensure_ascii=False)
                }
            ]
            
            # 添加最近的对话历史作为上下文(最多使用最近的5轮对话)
            recent_history = []
            for msg in self.chat_history[-10:]:  # 最多使用10条消息
                # 跳过系统消息
                if msg["role"] != "system":
                    recent_history.append(msg)
            
            # 将历史消息添加到上下文中
            command_context_messages.extend(recent_history)
            
            # 确保最后一条消息是当前的用户输入
            if command_context_messages[-1]["role"] != "user" or command_context_messages[-1]["content"] != user_input:
                # 清除最后一条消息(如果存在且是用户消息)，然后添加当前用户输入
                if command_context_messages[-1]["role"] == "user":
                    command_context_messages.pop()
                command_context_messages.append({"role": "user", "content": user_input})
            
            self.ui.console.print("[bold cyan]正在分析请求并生成命令...[/bold cyan]")
            
            # 使用可配置的流式输出
            always_stream = getattr(self.config.ui, 'always_stream', True)
            command_result = ""
            if always_stream and hasattr(self.api, 'stream_response') and callable(getattr(self.api, 'stream_response')):
                # 收集流式响应内容
                full_response = ""
                
                def collect_command_response():
                    nonlocal full_response
                    for chunk in self.api.stream_response(command_context_messages):
                        full_response += chunk
                        yield chunk
                
                # 使用流式输出显示响应生成
                self.ui.console.print("[bold]生成命令中...[/bold]")
                self.ui.stream_output(collect_command_response())
                command_result = full_response
            else:
                # 使用非流式响应
                try:
                    result = self.api.generate_command(user_input, system_info)
                    command_result = json.dumps(result, ensure_ascii=False)
                except Exception as e:
                    self.logger.error(f"API调用失败: {e}")
                    self.ui.show_error(f"API调用失败: {e}")
                    # 失败时尝试问答模式
                    self._handle_question_mode(user_input)
                    return
            
            # 处理命令结果
            try:
                # 尝试将结果解析为JSON
                if '{' in command_result and '}' in command_result:
                    # 提取JSON部分
                    try:
                        json_str = command_result[command_result.find('{'):command_result.rfind('}')+1]
                        result = json.loads(json_str)
                    except:
                        # 如果精确提取失败，用正则表达式尝试
                        import re
                        json_match = re.search(r'\{.*\}', command_result, re.DOTALL)
                        if json_match:
                            json_str = json_match.group(0)
                            result = json.loads(json_str)
                        else:
                            raise ValueError("无法从响应中提取JSON")
                else:
                    result = {"explanation": command_result, "command": ""}
                    
                if "commands" in result and isinstance(result["commands"], list) and len(result["commands"]) > 0:
                    for cmd_obj in result["commands"]:
                        if "command" in cmd_obj and cmd_obj["command"]:
                            command = cmd_obj["command"]
                            explanation = cmd_obj.get("explanation", "执行命令")
                            dangerous = False
                            reason_if_dangerous = ""
                            
                            if len(result["commands"]) > 1:
                                command_list = "\n".join([f"{i+1}. {c.get('command', '')} - {c.get('explanation', '')}" 
                                                     for i, c in enumerate(result["commands"])])
                                self.ui.console.print(f"[bold yellow]API返回了多个命令建议:[/bold yellow]\n{command_list}")
                                
                                confirmation_message = "是否要按顺序执行所有命令？(选择'否'则只执行第一个命令)"
                                if self.ui.confirm(confirmation_message):
                                    self.logger.info("用户选择执行所有命令")
                                    self._execute_command_sequence_from_api(result["commands"])
                                    return
                                else:
                                    self.ui.console.print(f"[bold]将执行第一个命令: [/bold][yellow]{command}[/yellow]")
                                    explanation = f"执行命令序列的第一步: {explanation}"
                            break
                    else:
                        raise ValueError("命令数组中没有有效命令")
                else:
                    command = result.get("command", "")
                    explanation = result.get("explanation", "")
                    dangerous = result.get("dangerous", False)
                    reason_if_dangerous = result.get("reason_if_dangerous", "")
            except Exception as e:
                self.logger.error(f"解析命令响应失败: {e}")
                self.ui.show_error(f"无法解析命令响应: {e}")
                assistant_response = f"无法生成有效命令: {str(e)}"
                self.chat_history.append({"role": "assistant", "content": assistant_response})
                self._save_chat_history()
                
                if self.ui.confirm("\n[bold]无法解析为有效命令。是否尝试使用ChatAI模式处理您的请求?[/bold]"):
                    self.logger.info("用户选择使用ChatAI模式")
                    # 失败时尝试问答模式
                    self._handle_question_mode(user_input)
                return
            
            command = result.get("command", "")
            explanation = result.get("explanation", "")
            dangerous = result.get("dangerous", False)
            reason_if_dangerous = result.get("reason_if_dangerous", "")
            
            if not command:
                self.logger.warning("API未返回有效命令")
                self.ui.show_error("无法理解您的请求或无法生成对应的命令")
                assistant_response = "无法生成有效命令。请尝试重新描述您的需求。"
                self.chat_history.append({"role": "assistant", "content": assistant_response})
                self._save_chat_history()
                
                # 询问用户是否使用问答模式
                if self.ui.confirm("\n[bold]无法生成有效命令。是否尝试使用ChatAI模式处理您的请求?[/bold]"):
                    self.logger.info("用户选择使用ChatAI模式处理无效命令")  
                    self._handle_question_mode(user_input)
                return
            
            if len(command) > 1000:
                self.logger.warning(f"生成的命令过长，可能不是有效命令: {command[:100]}...")
                self.ui.show_error("生成的命令异常，无法执行。请尝试用更简洁的方式描述您的需求。")
                
                if self.ui.confirm("\n[bold]命令异常。是否尝试使用ChatAI模式处理您的请求?[/bold]"):
                    self.logger.info("用户选择使用ChatAI模式处理命令异常")
                    self._handle_question_mode(user_input)
                return
                
            suspicious_starts = ["###", "##", "#", "解释:", "命令目的:", "安全性:", "是否是危险命令:"]
            if any(command.startswith(prefix) for prefix in suspicious_starts):
                self.logger.warning(f"生成的命令可能是解释文本，而非实际命令: {command}")
                self.ui.show_error("生成的命令格式异常，无法执行。请重新描述您的需求。")
                
                if self.ui.confirm("\n[bold]命令格式异常。是否尝试使用ChatAI模式处理您的请求?[/bold]"):
                    self.logger.info("用户选择使用ChatAI模式处理格式异常")
                    self._handle_question_mode(user_input)
                return
            
            self.logger.info(f"生成命令: {command}")
            
            if self._is_file_creation_command(command):
                file_path = self._extract_file_path(command)
                if file_path:
                    self.ui.console.print(f"[bold]理解:[/bold] {explanation}")
                    self.ui.console.print(f"[bold]检测到文件创建/编辑命令，将使用交互式编辑器打开文件[/bold]")
                    
                    self._ensure_directory_exists(file_path)
                    
                    editor = self._get_preferred_editor()
                    self._execute_edit_operation(f"{editor} {file_path}")
                    
                    # 添加到对话历史
                    assistant_response = f"检测到文件创建/编辑命令，已使用{editor}打开文件: {file_path}"
                    self.chat_history.append({"role": "assistant", "content": assistant_response})
                    self._save_chat_history()
                    return
            
            is_complex_command = self._is_complex_command(command)
            
            is_safe, unsafe_reason = self.executor.is_command_safe(command)
            needs_confirmation = False
            
            if not is_safe:
                needs_confirmation = True
                self.logger.warning(f"命令不安全: {unsafe_reason}")
            elif dangerous:
                needs_confirmation = True
                unsafe_reason = reason_if_dangerous
                self.logger.warning(f"命令可能有风险: {reason_if_dangerous}")
            
            self.ui.console.print(f"[bold]理解:[/bold] {explanation}")
            self.ui.console.print(f"[bold]要执行的命令:[/bold] [yellow]{command}[/yellow]")
            
            is_interactive = self._is_interactive_command(command)
            
            if is_interactive:
                if "vim" in command or "vi" in command or "nano" in command or "emacs" in command:
                    self.ui.console.print("[bold cyan]这是一个文本编辑命令，将打开编辑器供您交互操作。[/bold cyan]")
                    self.ui.console.print("[bold cyan]完成编辑后，请保存并退出编辑器继续操作。[/bold cyan]")
                else:
                    self.ui.console.print("[bold cyan]这是一个交互式命令，将直接在终端中执行...[/bold cyan]")
            
            if is_complex_command and '&&' in command and not is_interactive:
                confirmation_message = "这是一个复杂命令，可能需要较长时间执行。是否拆分为多个命令分步执行？"
                if self.ui.confirm(confirmation_message):
                    self.logger.info("用户选择拆分复杂命令")
                    commands = self._split_complex_command(command)
                    self._execute_commands_sequence(commands, explanation)
                    
                    # 添加到对话历史
                    commands_text = "\n".join([f"{i+1}. {cmd}" for i, cmd in enumerate(commands)])
                    assistant_response = f"已执行复杂命令序列:\n{commands_text}"
                    self.chat_history.append({"role": "assistant", "content": assistant_response})
                    self._save_chat_history()
                    return
            
            if needs_confirmation and self.config.security.confirm_dangerous_commands:
                confirmation_message = f"此命令可能有风险: {unsafe_reason}。确认执行?"
                if not self.ui.confirm(confirmation_message):
                    self.logger.info("用户取消执行危险命令")
                    self.ui.console.print("[bold red]已取消执行[/bold red]")
                    
                    # 添加拒绝执行记录到对话历史
                    assistant_response = f"命令 '{command}' 被用户拒绝执行，原因: {unsafe_reason}"
                    self.chat_history.append({"role": "assistant", "content": assistant_response})
                    self._save_chat_history()
                    return
            
            self.ui.console.print("[bold cyan]正在执行命令，这可能需要一些时间...[/bold cyan]")
            
            if is_interactive:
                stdout, stderr, return_code = self.executor.execute_command(command)
            else:
                with self.ui.console.status("[bold green]命令执行中...[/bold green]", spinner="dots"):
                    stdout, stderr, return_code = self.executor.execute_command(command)
            
            # 更新统计信息
            self.stats["commands_executed"] += 1
            
            if is_interactive:
                if return_code == 0:
                    self.ui.console.print("[bold green]交互式命令执行完成[/bold green]")
                    self.stats["successful_commands"] += 1
                    
                    # 添加到对话历史
                    assistant_response = f"交互式命令执行成功:\n命令: {command}"
                    self.chat_history.append({"role": "assistant", "content": assistant_response})
                    self._save_chat_history()
                else:
                    self.ui.show_error(f"交互式命令执行失败: {stderr}")
                    self.stats["failed_commands"] += 1
                    
                    # 添加到对话历史
                    assistant_response = f"交互式命令执行失败:\n命令: {command}\n错误: {stderr[:500]}" + ("..." if len(stderr) > 500 else "")
                    self.chat_history.append({"role": "assistant", "content": assistant_response})
                    self._save_chat_history()
                return
                
            if return_code == 0:
                self.ui.console.print("[bold green]命令执行成功！正在分析结果...[/bold green]")
                analysis = self.api.analyze_output(command, stdout, stderr)
                self.ui.show_result(analysis, command)
                self.stats["successful_commands"] += 1
                
                # 添加到对话历史
                success_response = f"命令执行成功:\n命令: {command}\n分析: {analysis.get('explanation', '')}"
                if 'recommendations' in analysis and analysis['recommendations']:
                    success_response += "\n\n建议: " + "\n- ".join([""] + analysis['recommendations'])
                self.chat_history.append({"role": "assistant", "content": success_response})
                self._save_chat_history()
            else:
                self.logger.warning(f"命令执行失败: {stderr}")
                self.ui.console.print("[bold yellow]命令执行返回非零状态，正在分析问题...[/bold yellow]")
                
                # 询问用户是否需要分析错误
                if self.ui.confirm("\n[bold]命令执行失败。需要分析错误原因吗?[/bold]"):
                    self.logger.info("用户请求分析命令执行错误")
                    analysis = self.api.analyze_output(command, stdout, stderr)
                    self.ui.show_result(analysis, command)
                    
                    # 将分析添加到对话历史
                    failure_response = f"命令执行失败:\n命令: {command}\n错误分析: {analysis.get('explanation', '')}"
                    self.chat_history.append({"role": "assistant", "content": failure_response})
                    
                    # 询问是否需要更详细的ChatAI模式分析
                    if self.ui.confirm("\n[bold]需要更详细的错误分析和解决方案吗?[/bold]"):
                        error_analysis_prompt = f"以下Linux命令执行失败，请详细分析错误原因并提供具体解决方案:\n命令: {command}\n错误输出: {stderr}"
                        self._handle_question_mode(error_analysis_prompt)
                        
                        # 询问是否根据分析结果修改命令重试
                        if self.ui.confirm("\n[bold]是否根据分析尝试修改命令并重新执行?[/bold]"):
                            self.ui.console.print("[bold cyan]请输入修改后的命令:[/bold cyan]")
                            modified_command = self.ui.get_input("[修改命令] > ")
                            if modified_command and modified_command.strip():
                                # 递归调用处理修改后的命令
                                self.process_user_input(modified_command)
                else:
                    # 简单显示错误信息
                    self.ui.show_result(stderr, command)
                    # 将失败信息添加到对话历史
                    failure_response = f"命令执行失败:\n命令: {command}\n错误: {stderr[:1000]}" + ("..." if len(stderr) > 1000 else "")
                    self.chat_history.append({"role": "assistant", "content": failure_response})
                
                self.stats["failed_commands"] += 1
                self._save_chat_history()
                
        except Exception as e:
            self.logger.error(f"处理用户输入时出错: {e}", exc_info=True)
            self.ui.show_error(f"处理请求时出错: {e}")
            # 将错误信息添加到对话历史
            error_response = f"处理请求时出错: {str(e)}"
            self.chat_history.append({"role": "assistant", "content": error_response})
            self._save_chat_history()
            
            # 询问用户是否使用问答模式
            if self.ui.confirm("\n[bold]处理请求发生异常。是否尝试使用ChatAI模式处理您的请求?[/bold]"):
                self.logger.info("用户选择使用ChatAI模式处理异常")
                # 发生异常时，尝试问答模式
                self._handle_question_mode(user_input)
    
    def _execute_edit_operation(self, command: str) -> None:
        """执行编辑操作"""
        parts = command.split()
        file_path = parts[-1]
        editor = parts[-2] if len(parts) > 1 else "vim"
        
        self.ui.console.print(f"[bold]正在使用 {editor} 编辑文件: [/bold][yellow]{file_path}[/yellow]")
        
        stdout, stderr, return_code = self.executor.execute_file_editor(file_path, editor.split('/')[-1])
        
        if return_code == 0:
            self.ui.console.print("[bold green]文件编辑完成[/bold green]")
        else:
            self.ui.show_error(f"编辑文件时出错: {stderr}")

    def _load_stats(self) -> Dict[str, int]:
        """加载统计数据"""
        default_stats = {
            "commands_executed": 0,
            "questions_answered": 0,
            "successful_commands": 0,
            "failed_commands": 0,
            "total_sessions": 0,
            "total_usage_time": 0  # 总使用时间（秒）
        }
        
        if os.path.exists(self.stats_file):
            try:
                with open(self.stats_file, 'r', encoding='utf-8') as f:
                    stats = json.load(f)
                self.logger.info(f"成功加载统计数据")
                # 确保所有键都存在
                for key in default_stats:
                    if key not in stats:
                        stats[key] = default_stats[key]
                return stats
            except Exception as e:
                self.logger.error(f"加载统计数据失败: {e}")
                return default_stats
        else:
            self.logger.info(f"统计数据文件不存在，使用默认值")
            return default_stats
            
    def _save_stats(self) -> None:
        """保存统计数据"""
        try:
            # 如果有历史记录，计算本次会话时长
            if self.history:
                start_time = self.history[0]["timestamp"]
                current_time = time.time()
                session_duration = current_time - start_time
                self.stats["total_usage_time"] += int(session_duration)
            
            with open(self.stats_file, 'w', encoding='utf-8') as f:
                json.dump(self.stats, f, indent=2)
            self.logger.info(f"成功保存统计数据")
        except Exception as e:
            self.logger.error(f"保存统计数据失败: {e}")
    
    def _show_stats(self) -> None:
        """显示使用统计信息"""
        from rich.table import Table
        
        table = Table(title="LinuxAgent 使用统计")
        
        table.add_column("统计项", style="cyan")
        table.add_column("数值", style="green", justify="right")
        
        # 当前会话统计
        table.add_row("== 当前会话 ==", "")
        
        current_session_commands = self.stats["commands_executed"] - (self.stats.get("previous_commands_executed", 0) or 0)
        current_session_questions = self.stats["questions_answered"] - (self.stats.get("previous_questions_answered", 0) or 0)
        table.add_row("命令执行数", str(current_session_commands))
        table.add_row("问答请求数", str(current_session_questions))
        
        # 如果有历史记录，显示当前会话时长
        if self.history:
            start_time = self.history[0]["timestamp"]
            current_time = time.time()
            session_duration = current_time - start_time
            hours = int(session_duration // 3600)
            minutes = int((session_duration % 3600) // 60)
            seconds = int(session_duration % 60)
            duration_str = f"{hours}小时 {minutes}分钟 {seconds}秒"
            table.add_row("会话时长", duration_str)
        
        # 总体统计
        table.add_row("== 总体统计 ==", "")
        table.add_row("总命令执行数", str(self.stats["commands_executed"]))
        table.add_row("成功命令数", str(self.stats["successful_commands"]))
        table.add_row("失败命令数", str(self.stats["failed_commands"]))
        table.add_row("总问答请求数", str(self.stats["questions_answered"]))
        
        if self.stats["commands_executed"] > 0:
            success_rate = self.stats["successful_commands"] / self.stats["commands_executed"] * 100
            table.add_row("命令成功率", f"{success_rate:.1f}%")
        
        # 添加累计使用情况
        total_sessions = self.stats.get("total_sessions", 0) + 1
        total_time = self.stats.get("total_usage_time", 0)
        if self.history:
            total_time += int(time.time() - self.history[0]["timestamp"])
        
        hours = total_time // 3600
        minutes = (total_time % 3600) // 60
        table.add_row("累计会话数", str(total_sessions))
        table.add_row("累计使用时间", f"{hours}小时 {minutes}分钟")
            
        # 添加使用的LLM提供者
        table.add_row("LLM提供者", self.config.api.provider)
        
        self.ui.console.print(table)

    def _show_chat_history(self):
        """显示对话历史"""
        if not self.chat_history:
            self.ui.console.print("[bold yellow]对话历史为空[/bold yellow]")
            return
            
        from rich.table import Table
        from rich.panel import Panel
        
        # 询问用户是否需要简略模式或详细模式
        self.ui.console.print("[bold]选择查看模式:[/bold]")
        self.ui.console.print("1. 简略模式 - 仅显示摘要")
        self.ui.console.print("2. 详细模式 - 查看完整对话内容")
        
        mode = self.ui.get_input("选择查看模式 (1/2) > ")
        
        if mode == "1":
            # 简略模式 - 显示摘要表格
            table = Table(title="对话历史摘要")
            table.add_column("序号", style="cyan", justify="right")
            table.add_column("角色", style="cyan")
            table.add_column("内容预览", style="white")
            table.add_column("时间", style="dim")
            
            for i, msg in enumerate(self.chat_history):
                role = msg.get("role", "")
                content = msg.get("content", "")
                time_stamp = msg.get("timestamp", "")
                
                # 美化显示角色
                if role == "user":
                    role_display = "[bold green]用户[/bold green]"
                elif role == "assistant":
                    role_display = "[bold blue]助手[/bold blue]"
                elif role == "system":
                    role_display = "[bold magenta]系统[/bold magenta]"
                else:
                    role_display = role
                
                # 内容预览
                content_preview = content[:50] + "..." if len(content) > 50 else content
                
                # 时间戳
                time_display = ""
                if time_stamp:
                    from datetime import datetime
                    try:
                        time_display = datetime.fromtimestamp(time_stamp).strftime("%H:%M:%S")
                    except:
                        pass
                
                table.add_row(str(i+1), role_display, content_preview, time_display)
                
            self.ui.console.print(table)

            if self.ui.confirm("\n[bold]是否查看某条对话的详细内容?[/bold]"):
                while True:
                    index = self.ui.get_input("请输入要查看的对话序号 (q退出) > ")
                    if index.lower() in ['q', 'quit', 'exit']:
                        break
                        
                    try:
                        idx = int(index) - 1
                        if 0 <= idx < len(self.chat_history):
                            self._show_chat_item(idx)
                        else:
                            self.ui.console.print("[bold red]无效的序号[/bold red]")
                    except ValueError:
                        self.ui.console.print("[bold red]请输入有效的数字[/bold red]")
                        
                    if not self.ui.confirm("\n[bold]继续查看其他对话?[/bold]"):
                        break
        else:
            # 详细模式 - 逐个显示
            self.ui.console.print("\n[bold]完整对话历史:[/bold]")
            
            page_size = 5  # 每页显示的对话数量
            total_pages = (len(self.chat_history) + page_size - 1) // page_size
            current_page = 1
            
            while current_page <= total_pages:
                start_idx = (current_page - 1) * page_size
                end_idx = min(start_idx + page_size, len(self.chat_history))
                
                self.ui.console.print(f"\n[bold cyan]--- 第 {current_page}/{total_pages} 页 ---[/bold cyan]")
                
                for i in range(start_idx, end_idx):
                    self._show_chat_item(i, compact=True)
                
                if current_page < total_pages:
                    options = ["n: 下一页", "p: 上一页", "q: 退出", "g <页码>: 跳转到指定页", "v <序号>: 查看详细内容"]
                    self.ui.console.print("\n[bold]导航选项:[/bold] " + " | ".join(options))
                    
                    choice = self.ui.get_input("导航 > ")
                    
                    if choice.lower() == 'n':
                        current_page += 1
                    elif choice.lower() == 'p' and current_page > 1:
                        current_page -= 1
                    elif choice.lower() == 'q':
                        break
                    elif choice.lower().startswith('g '):
                        try:
                            page = int(choice[2:])
                            if 1 <= page <= total_pages:
                                current_page = page
                            else:
                                self.ui.console.print(f"[bold red]页码范围: 1-{total_pages}[/bold red]")
                        except ValueError:
                            self.ui.console.print("[bold red]无效的页码[/bold red]")
                    elif choice.lower().startswith('v '):
                        try:
                            idx = int(choice[2:]) - 1
                            if 0 <= idx < len(self.chat_history):
                                self._show_chat_item(idx, compact=False)

                                self.ui.console.print("\n[bold]导航选项:[/bold] " + " | ".join(options))
                            else:
                                self.ui.console.print("[bold red]无效的序号[/bold red]")
                        except ValueError:
                            self.ui.console.print("[bold red]无效的序号[/bold red]")
                    else:
                        self.ui.console.print("[bold red]无效的选择[/bold red]")
                else:
                    self.ui.console.print("\n[bold green]已显示全部对话历史[/bold green]")
                    if not self.ui.confirm("[bold]退出查看?[/bold]"):
                        current_page = 1  # 重新开始浏览

    def _show_chat_item(self, index, compact=False):
        """显示单条对话详情
        
        Args:
            index: 对话索引
            compact: 是否使用紧凑模式显示
        """
        msg = self.chat_history[index]
        role = msg.get("role", "")
        content = msg.get("content", "")
        time_stamp = msg.get("timestamp", "")
        
        # 美化显示角色
        if role == "user":
            role_display = "[bold green]用户[/bold green]"
            panel_style = "green"
        elif role == "assistant":
            role_display = "[bold blue]助手[/bold blue]"
            panel_style = "blue"
        elif role == "system":
            role_display = "[bold magenta]系统[/bold magenta]"
            panel_style = "magenta"
        else:
            role_display = role
            panel_style = "white"
        
        # 时间戳
        time_display = ""
        if time_stamp:
            from datetime import datetime
            try:
                time_display = datetime.fromtimestamp(time_stamp).strftime("%Y-%m-%d %H:%M:%S")
            except:
                pass
        
        title = f"{index+1}. {role_display}" + (f" ({time_display})" if time_display else "")
        
        if compact and len(content) > 200:
            display_content = content[:197] + "..."
            self.ui.console.print(Panel(display_content, title=title, border_style=panel_style))
            self.ui.console.print(f"[dim]内容过长，使用 'v {index+1}' 查看完整内容[/dim]")
        else:
            if len(content) > 1000 and not compact:
                self._display_segmented_text(content, title=title, panel_style=panel_style)
            else:
                self.ui.console.print(Panel(content, title=title, border_style=panel_style))

    def _adjust_settings(self):
        """调整设置的交互界面"""
        from rich.table import Table
        
        while True:
            table = Table(title="LinuxAgent 设置")
            table.add_column("编号", style="cyan", justify="center")
            table.add_column("类别", style="green")
            table.add_column("说明", style="white")
            
            table.add_row("1", "UI设置", "调整用户界面、流式输出等显示相关设置")
            table.add_row("2", "API设置", "配置大语言模型API相关参数")
            table.add_row("3", "安全设置", "配置命令执行的安全策略")
            table.add_row("4", "对话设置", "调整对话历史和多轮对话相关设置")
            table.add_row("5", "语言和主题", "调整界面语言和主题")
            table.add_row("6", "数据分析", "用户使用数据分析和命令推荐设置")
            table.add_row("q", "退出", "返回主界面")
            
            self.ui.console.print(table)
            self.ui.console.print("\n[bold]请选择要调整的设置类别:[/bold]")
            
            choice = self.ui.get_input("设置 > ")
            
            if choice.lower() in ['q', 'quit', 'exit', 'back']:
                break
                
            try:
                if choice == "1":
                    self._adjust_ui_settings()
                elif choice == "2":
                    self._adjust_api_settings()
                elif choice == "3":
                    self._adjust_security_settings()
                elif choice == "4":
                    self._adjust_chat_settings()
                elif choice == "5":
                    self._adjust_language_theme_settings()
                elif choice == "6":
                    self._adjust_data_analysis_settings()
                else:
                    self.ui.console.print("[bold red]无效的选择，请重新输入[/bold red]")
            except Exception as e:
                self.logger.error(f"调整设置时出错: {e}", exc_info=True)
                self.ui.show_error(f"调整设置时出错: {e}")
                
        self.ui.console.print("[bold green]设置已更新[/bold green]")
        
    def _adjust_ui_settings(self):
        """调整UI设置"""
        from rich.table import Table
        
        # 显示当前UI设置
        table = Table(title="UI设置")
        table.add_column("设置项", style="cyan")
        table.add_column("当前值", style="green")
        table.add_column("说明", style="white")
        
        # UI设置
        table.add_row(
            "1. 流式输出刷新率",
            f"{self.ui.refresh_rate}",
            "每秒刷新屏幕的次数，较高值更流畅但可能导致闪烁"
        )
        
        table.add_row(
            "2. 面板初始高度",
            f"{self.ui.initial_panel_height}",
            "流式输出面板的初始高度（行数），推荐设为25或35避开30行卡顿问题"
        )
        
        # 全局流式回答设置
        always_stream = getattr(self.config.ui, 'always_stream', True)
        table.add_row(
            "3. 全局流式回答",
            f"{'开启' if always_stream else '关闭'}",
            "是否对所有非命令输入使用流式回答"
        )
        
        # 添加缓冲区大小设置
        buffer_size = getattr(self.config.ui, 'buffer_size', 100)
        table.add_row(
            "4. 流式输出缓冲大小",
            f"{buffer_size}字符",
            "缓存多少字符后一次性输出，较大值减少卡顿但流畅度降低"
        )
        
        # 添加行宽设置
        line_width = getattr(self.config.ui, 'line_width', 80)
        table.add_row(
            "5. 流式输出行宽",
            f"{line_width}字符",
            "每行显示的最大字符数，超过此宽度将自动换行"
        )
        
        # 添加最大显示行数设置
        max_lines = getattr(self.config.ui, 'max_lines', 40)
        table.add_row(
            "6. 流式输出最大行数",
            f"{max_lines}行",
            "流式输出面板可显示的最大行数，值越大显示内容越多"
        )
        
        # 添加自动滚动设置
        auto_scroll = getattr(self.config.ui, 'auto_scroll', True)
        table.add_row(
            "7. 自动滚动",
            f"{'开启' if auto_scroll else '关闭'}",
            "是否在输出时自动滚动到最新内容"
        )
        
        self.ui.console.print(table)
        self.ui.console.print("\n[bold]输入要修改的设置编号，或输入q返回:[/bold]")
        
        while True:
            choice = self.ui.get_input("UI设置 > ")
            
            if choice.lower() in ['q', 'quit', 'exit', 'back']:
                break
                
            try:
                setting_num = int(choice)
                if setting_num == 1:
                    # 调整流式输出刷新率
                    self.ui.console.print("\n当前刷新率：" + str(self.ui.refresh_rate))
                    self.ui.console.print("推荐值：较流畅(15-20)，较稳定(5-10)")
                    new_rate = self.ui.get_input("请输入新的刷新率(1-30) > ")
                    try:
                        new_rate = int(new_rate)
                        if 1 <= new_rate <= 30:
                            # 更新UI对象中的刷新率
                            self.ui.refresh_rate = new_rate
                            self.ui.console.print(f"[bold green]流式输出刷新率已更新为 {new_rate}[/bold green]")
                        else:
                            self.ui.console.print("[bold red]输入的值不在有效范围内[/bold red]")
                    except ValueError:
                        self.ui.console.print("[bold red]请输入有效的数字[/bold red]")
                        
                elif setting_num == 2:
                    # 调整面板初始高度
                    self.ui.console.print("\n当前面板初始高度：" + str(self.ui.initial_panel_height))
                    self.ui.console.print("推荐值：25行或35行，避开可能导致卡顿的30行临界点")
                    new_height = self.ui.get_input("请输入新的面板初始高度(5-50) > ")
                    try:
                        new_height = int(new_height)
                        if 5 <= new_height <= 50:
                            # 更新UI对象中的初始面板高度
                            self.ui.initial_panel_height = new_height
                            self.ui.console.print(f"[bold green]面板初始高度已更新为 {new_height}[/bold green]")
                            # 提示解决卡顿问题
                            if 28 <= new_height <= 32:
                                self.ui.console.print("[bold yellow]注意: 设置为接近30行可能导致长文本显示卡顿，推荐设置为25或35[/bold yellow]")
                        else:
                            self.ui.console.print("[bold red]输入的值不在有效范围内[/bold red]")
                    except ValueError:
                        self.ui.console.print("[bold red]请输入有效的数字[/bold red]")
                        
                elif setting_num == 3:
                    # 调整全局流式回答设置
                    current = "开启" if getattr(self.config.ui, 'always_stream', True) else "关闭"
                    self.ui.console.print(f"\n当前全局流式回答设置：{current}")
                    self.ui.console.print("开启后，所有非明确命令的输入都会使用流式回答")
                    
                    new_setting = self.ui.get_input("请选择(1:开启, 0:关闭) > ")
                    if new_setting in ['1', '0']:
                        # 更新设置
                        setattr(self.config.ui, 'always_stream', new_setting == '1')
                        new_status = "开启" if new_setting == '1' else "关闭"
                        self.ui.console.print(f"[bold green]全局流式回答已{new_status}[/bold green]")
                    else:
                        self.ui.console.print("[bold red]无效的选择[/bold red]")
                
                elif setting_num == 4:
                    # 调整流式输出缓冲大小
                    current_buffer_size = getattr(self.config.ui, 'buffer_size', 100)
                    self.ui.console.print(f"\n当前流式输出缓冲大小：{current_buffer_size}字符")
                    self.ui.console.print("推荐值：流畅(50-100)，减少卡顿(200-500)，对长文本友好(500-1000)")
                    
                    new_buffer_size = self.ui.get_input("请输入新的缓冲大小(50-2000) > ")
                    try:
                        new_buffer_size = int(new_buffer_size)
                        if 50 <= new_buffer_size <= 2000:
                            # 更新配置
                            setattr(self.config.ui, 'buffer_size', new_buffer_size)
                            self.ui.console.print(f"[bold green]流式输出缓冲大小已更新为 {new_buffer_size}字符[/bold green]")
                        else:
                            self.ui.console.print("[bold red]输入的值不在有效范围内[/bold red]")
                    except ValueError:
                        self.ui.console.print("[bold red]请输入有效的数字[/bold red]")
                        
                elif setting_num == 5:
                    # 调整流式输出行宽
                    current_line_width = getattr(self.config.ui, 'line_width', 80)
                    self.ui.console.print(f"\n当前流式输出行宽：{current_line_width}字符")
                    self.ui.console.print("推荐值：窄屏(60-80)，宽屏(100-120)")
                    
                    new_line_width = self.ui.get_input("请输入新的行宽(40-150) > ")
                    try:
                        new_line_width = int(new_line_width)
                        if 40 <= new_line_width <= 150:
                            # 更新配置
                            setattr(self.config.ui, 'line_width', new_line_width)
                            self.ui.console.print(f"[bold green]流式输出行宽已更新为 {new_line_width}字符[/bold green]")
                        else:
                            self.ui.console.print("[bold red]输入的值不在有效范围内[/bold red]")
                    except ValueError:
                        self.ui.console.print("[bold red]请输入有效的数字[/bold red]")
                
                elif setting_num == 6:
                    # 调整流式输出最大行数
                    current_max_lines = getattr(self.config.ui, 'max_lines', 40)
                    self.ui.console.print(f"\n当前流式输出最大行数：{current_max_lines}行")
                    self.ui.console.print("推荐值：较小屏幕(25-35)，大屏幕(40-50)")
                    
                    new_max_lines = self.ui.get_input("请输入新的最大行数(15-100) > ")
                    try:
                        new_max_lines = int(new_max_lines)
                        if 15 <= new_max_lines <= 100:
                            # 更新配置
                            setattr(self.config.ui, 'max_lines', new_max_lines)
                            self.ui.console.print(f"[bold green]流式输出最大行数已更新为 {new_max_lines}行[/bold green]")
                        else:
                            self.ui.console.print("[bold red]输入的值不在有效范围内[/bold red]")
                    except ValueError:
                        self.ui.console.print("[bold red]请输入有效的数字[/bold red]")
                
                elif setting_num == 7:
                    # 调整自动滚动设置
                    current = "开启" if getattr(self.config.ui, 'auto_scroll', True) else "关闭"
                    self.ui.console.print(f"\n当前自动滚动设置：{current}")
                    self.ui.console.print("开启后，流式输出会自动滚动到最新内容")
                    
                    new_setting = self.ui.get_input("请选择(1:开启, 0:关闭) > ")
                    if new_setting in ['1', '0']:
                        # 更新设置
                        setattr(self.config.ui, 'auto_scroll', new_setting == '1')
                        new_status = "开启" if new_setting == '1' else "关闭"
                        self.ui.console.print(f"[bold green]自动滚动已{new_status}[/bold green]")
                    else:
                        self.ui.console.print("[bold red]无效的选择[/bold red]")
                    
                else:
                    self.ui.console.print("[bold red]无效的设置编号[/bold red]")
            except ValueError:
                self.ui.console.print("[bold red]请输入数字或q退出[/bold red]")
                
    def _adjust_api_settings(self):
        """调整API设置"""
        from rich.table import Table
        import yaml
        import os
        
        # 显示当前API设置
        table = Table(title="API设置")
        table.add_column("设置项", style="cyan")
        table.add_column("当前值", style="green")
        table.add_column("说明", style="white")
        
        # 隐藏部分API密钥
        api_key = self.config.api.api_key
        masked_key = "无" if not api_key else api_key[:4] + '*' * (len(api_key) - 8) + api_key[-4:] if len(api_key) > 8 else "***"
        
        table.add_row(
            "1. API提供者",
            f"{self.config.api.provider}",
            "大语言模型提供者 (deepseek, openai)"
        )
        
        table.add_row(
            "2. API密钥",
            f"{masked_key}",
            "访问LLM API的密钥"
        )
        
        table.add_row(
            "3. 模型名称",
            f"{self.config.api.model}",
            "使用的大语言模型名称"
        )
        
        table.add_row(
            "4. 请求超时时间",
            f"{self.config.api.timeout}秒",
            "API请求超时时间"
        )
        
        self.ui.console.print(table)
        self.ui.console.print("\n[bold]输入要修改的设置编号，或输入q返回:[/bold]")
        
        config_changed = False
        
        while True:
            choice = self.ui.get_input("API设置 > ")
            
            if choice.lower() in ['q', 'quit', 'exit', 'back']:
                break
                
            try:
                setting_num = int(choice)
                if setting_num == 1:
                    # 修改API提供者
                    self.ui.console.print("\n当前API提供者：" + str(self.config.api.provider))
                    self.ui.console.print("支持的提供者: deepseek, openai")
                    new_provider = self.ui.get_input("请输入新的API提供者 > ")
                    if new_provider.lower() in ['deepseek', 'openai']:
                        self.config.api.provider = new_provider.lower()
                        config_changed = True
                        self.ui.console.print(f"[bold green]API提供者已更新为 {new_provider.lower()}[/bold green]")
                    else:
                        self.ui.console.print("[bold red]不支持的API提供者[/bold red]")
                        
                elif setting_num == 2:
                    # 修改API密钥
                    self.ui.console.print("\n修改API密钥")
                    current_key = self.config.api.api_key
                    masked_current = "无" if not current_key else current_key[:4] + '*' * (len(current_key) - 8) + current_key[-4:] if len(current_key) > 8 else "***"
                    self.ui.console.print(f"当前API密钥: {masked_current}")
                    
                    new_key = self.ui.get_input("请输入新的API密钥 > ")
                    if new_key:
                        self.config.api.api_key = new_key
                        config_changed = True
                        masked_new = new_key[:4] + '*' * (len(new_key) - 8) + new_key[-4:] if len(new_key) > 8 else "***"
                        self.ui.console.print(f"[bold green]API密钥已更新为 {masked_new}[/bold green]")
                    else:
                        self.ui.console.print("[bold yellow]API密钥未更改[/bold yellow]")
                        
                elif setting_num == 3:
                    # 修改模型名称
                    self.ui.console.print("\n当前模型名称：" + str(self.config.api.model))
                    
                    if self.config.api.provider.lower() == 'deepseek':
                        self.ui.console.print("DeepSeek推荐模型: deepseek-chat")
                        new_model = self.ui.get_input("请输入新的模型名称 > ")
                        if new_model:
                            self.config.api.model = new_model
                            config_changed = True
                            self.ui.console.print(f"[bold green]模型名称已更新为 {new_model}[/bold green]")
                        else:
                            self.ui.console.print("[bold yellow]模型名称未更改[/bold yellow]")
                    elif self.config.api.provider.lower() == 'openai':
                        self.ui.console.print("OpenAI推荐模型: gpt-3.5-turbo, gpt-4, gpt-4-turbo")
                        new_model = self.ui.get_input("请输入新的模型名称 > ")
                        if new_model:
                            self.config.api.model = new_model
                            config_changed = True
                            self.ui.console.print(f"[bold green]模型名称已更新为 {new_model}[/bold green]")
                        else:
                            self.ui.console.print("[bold yellow]模型名称未更改[/bold yellow]")
                            
                elif setting_num == 4:
                    # 修改请求超时时间
                    self.ui.console.print("\n当前请求超时时间：" + str(self.config.api.timeout) + "秒")
                    new_timeout = self.ui.get_input("请输入新的超时时间(秒) > ")
                    try:
                        new_timeout = int(new_timeout)
                        if new_timeout > 0:
                            self.config.api.timeout = new_timeout
                            config_changed = True
                            self.ui.console.print(f"[bold green]请求超时时间已更新为 {new_timeout}秒[/bold green]")
                        else:
                            self.ui.console.print("[bold red]超时时间必须大于0[/bold red]")
                    except ValueError:
                        self.ui.console.print("[bold red]请输入有效的数字[/bold red]")
                else:
                    self.ui.console.print("[bold red]无效的设置编号[/bold red]")
            except ValueError:
                self.ui.console.print("[bold red]请输入数字或q退出[/bold red]")
                
        # 如果配置有更改，询问是否保存到配置文件
        if config_changed:
            if self.ui.confirm("是否将API设置保存到配置文件?"):
                self._save_config_to_file()
                
    def _adjust_security_settings(self):
        """调整安全设置"""
        from rich.table import Table
        import yaml
        
        # 显示当前安全设置
        table = Table(title="安全设置")
        table.add_column("设置项", style="cyan")
        table.add_column("当前值", style="green")
        table.add_column("说明", style="white")
        
        table.add_row(
            "1. 危险命令确认",
            f"{'开启' if self.config.security.confirm_dangerous_commands else '关闭'}",
            "执行危险命令时是否需要确认"
        )
        
        table.add_row(
            "2. 完全禁止的命令",
            f"{len(self.config.security.blocked_commands)}条",
            "完全禁止执行的命令列表"
        )
        
        table.add_row(
            "3. 需要确认的命令模式",
            f"{len(self.config.security.confirm_patterns)}条",
            "执行时需要确认的命令模式列表"
        )
        
        self.ui.console.print(table)
        self.ui.console.print("\n[bold]输入要修改的设置编号，或输入q返回:[/bold]")
        
        config_changed = False
        
        while True:
            choice = self.ui.get_input("安全设置 > ")
            
            if choice.lower() in ['q', 'quit', 'exit', 'back']:
                break
                
            try:
                setting_num = int(choice)
                if setting_num == 1:
                    # 修改危险命令确认设置
                    current = "开启" if self.config.security.confirm_dangerous_commands else "关闭"
                    self.ui.console.print(f"\n当前危险命令确认设置：{current}")
                    self.ui.console.print("开启后，执行危险命令时会要求用户确认")
                    
                    new_setting = self.ui.get_input("请选择(1:开启, 0:关闭) > ")
                    if new_setting in ['1', '0']:
                        # 更新设置
                        self.config.security.confirm_dangerous_commands = new_setting == '1'
                        config_changed = True
                        new_status = "开启" if new_setting == '1' else "关闭"
                        self.ui.console.print(f"[bold green]危险命令确认已{new_status}[/bold green]")
                    else:
                        self.ui.console.print("[bold red]无效的选择[/bold red]")
                        
                elif setting_num == 2:
                    # 查看和修改完全禁止的命令
                    self._manage_blocked_commands()
                    config_changed = True
                    
                elif setting_num == 3:
                    # 查看和修改需要确认的命令模式
                    self._manage_confirm_patterns()
                    config_changed = True
                    
                else:
                    self.ui.console.print("[bold red]无效的设置编号[/bold red]")
            except ValueError:
                self.ui.console.print("[bold red]请输入数字或q退出[/bold red]")
                
        # 如果配置有更改，询问是否保存到配置文件
        if config_changed:
            if self.ui.confirm("是否将安全设置保存到配置文件?"):
                self._save_config_to_file()
                
    def _manage_blocked_commands(self):
        """管理完全禁止的命令列表"""
        from rich.table import Table
        from rich.style import Style
        
        while True:
            # 显示当前禁止的命令列表
            table = Table(title="完全禁止的命令列表")
            table.add_column("编号", style="cyan", justify="center")
            table.add_column("命令", style="red")
            
            if not self.config.security.blocked_commands:
                table.add_row("", "[italic]无禁止命令[/italic]")
            else:
                for i, cmd in enumerate(self.config.security.blocked_commands, 1):
                    table.add_row(str(i), cmd)
            
            self.ui.console.print(table)
            self.ui.console.print("\n[bold]操作选项:[/bold]")
            self.ui.console.print("  a: 添加新的禁止命令")
            self.ui.console.print("  d <编号>: 删除指定编号的禁止命令")
            self.ui.console.print("  q: 返回上级菜单")
            
            action = self.ui.get_input("禁止命令 > ")
            
            if action.lower() == 'q':
                break
                
            elif action.lower() == 'a':
                # 添加新的禁止命令
                new_cmd = self.ui.get_input("请输入要禁止的命令 > ")
                if new_cmd and new_cmd not in self.config.security.blocked_commands:
                    self.config.security.blocked_commands.append(new_cmd)
                    self.ui.console.print(f"[bold green]已添加禁止命令: {new_cmd}[/bold green]")
                elif new_cmd in self.config.security.blocked_commands:
                    self.ui.console.print("[bold yellow]该命令已在禁止列表中[/bold yellow]")
                else:
                    self.ui.console.print("[bold red]命令不能为空[/bold red]")
                    
            elif action.lower().startswith('d '):
                # 删除指定编号的禁止命令
                try:
                    idx = int(action[2:]) - 1
                    if 0 <= idx < len(self.config.security.blocked_commands):
                        removed_cmd = self.config.security.blocked_commands.pop(idx)
                        self.ui.console.print(f"[bold green]已删除禁止命令: {removed_cmd}[/bold green]")
                    else:
                        self.ui.console.print("[bold red]无效的编号[/bold red]")
                except ValueError:
                    self.ui.console.print("[bold red]请输入有效的编号[/bold red]")
            else:
                self.ui.console.print("[bold red]无效的操作[/bold red]")
                
    def _manage_confirm_patterns(self):
        """管理需要确认的命令模式列表"""
        from rich.table import Table
        
        while True:
            # 显示当前需要确认的命令模式列表
            table = Table(title="需要确认的命令模式列表")
            table.add_column("编号", style="cyan", justify="center")
            table.add_column("模式", style="yellow")
            
            if not self.config.security.confirm_patterns:
                table.add_row("", "[italic]无需确认的命令模式[/italic]")
            else:
                for i, pattern in enumerate(self.config.security.confirm_patterns, 1):
                    table.add_row(str(i), pattern)
            
            self.ui.console.print(table)
            self.ui.console.print("\n[bold]操作选项:[/bold]")
            self.ui.console.print("  a: 添加新的命令模式")
            self.ui.console.print("  d <编号>: 删除指定编号的命令模式")
            self.ui.console.print("  q: 返回上级菜单")
            
            action = self.ui.get_input("确认模式 > ")
            
            if action.lower() == 'q':
                break
                
            elif action.lower() == 'a':
                # 添加新的命令模式
                new_pattern = self.ui.get_input("请输入要需要确认的命令模式 > ")
                if new_pattern and new_pattern not in self.config.security.confirm_patterns:
                    self.config.security.confirm_patterns.append(new_pattern)
                    self.ui.console.print(f"[bold green]已添加需确认命令模式: {new_pattern}[/bold green]")
                elif new_pattern in self.config.security.confirm_patterns:
                    self.ui.console.print("[bold yellow]该模式已在列表中[/bold yellow]")
                else:
                    self.ui.console.print("[bold red]模式不能为空[/bold red]")
                    
            elif action.lower().startswith('d '):
                # 删除指定编号的命令模式
                try:
                    idx = int(action[2:]) - 1
                    if 0 <= idx < len(self.config.security.confirm_patterns):
                        removed_pattern = self.config.security.confirm_patterns.pop(idx)
                        self.ui.console.print(f"[bold green]已删除需确认命令模式: {removed_pattern}[/bold green]")
                    else:
                        self.ui.console.print("[bold red]无效的编号[/bold red]")
                except ValueError:
                    self.ui.console.print("[bold red]请输入有效的编号[/bold red]")
            else:
                self.ui.console.print("[bold red]无效的操作[/bold red]")
                
    def _adjust_chat_settings(self):
        """调整对话设置"""
        from rich.table import Table
        
        # 显示当前对话设置
        table = Table(title="对话设置")
        table.add_column("设置项", style="cyan")
        table.add_column("当前值", style="green")
        table.add_column("说明", style="white")
        
        # 对话历史设置
        table.add_row(
            "1. 最大对话历史条数",
            f"{self.max_chat_history}",
            "记住的最大对话轮数"
        )
        
        table.add_row(
            "2. 工作模式",
            f"{self.working_mode}",
            "当前工作模式 (auto, chat, agent)"
        )
        
        self.ui.console.print(table)
        self.ui.console.print("\n[bold]输入要修改的设置编号，或输入q返回:[/bold]")
        
        while True:
            choice = self.ui.get_input("对话设置 > ")
            
            if choice.lower() in ['q', 'quit', 'exit', 'back']:
                break
                
            try:
                setting_num = int(choice)
                if setting_num == 1:
                    # 调整最大对话历史条数
                    self.ui.console.print("\n当前最大对话历史条数：" + str(self.max_chat_history))
                    new_limit = self.ui.get_input("请输入新的最大对话历史条数(5-50) > ")
                    try:
                        new_limit = int(new_limit)
                        if 5 <= new_limit <= 50:
                            # 更新最大对话历史条数
                            self.max_chat_history = new_limit
                            
                            # 如果当前历史超出新限制，进行截断
                            if len(self.chat_history) > new_limit * 2:
                                self.chat_history = self.chat_history[-(new_limit * 2):]
                                
                            self.ui.console.print(f"[bold green]最大对话历史条数已更新为 {new_limit}[/bold green]")
                            # 保存更新后的历史
                            self._save_chat_history()
                        else:
                            self.ui.console.print("[bold red]输入的值不在有效范围内[/bold red]")
                    except ValueError:
                        self.ui.console.print("[bold red]请输入有效的数字[/bold red]")
                        
                elif setting_num == 2:
                    # 修改工作模式
                    self.ui.console.print("\n当前工作模式：" + str(self.working_mode))
                    self.ui.console.print("  auto: 自动判断输入类型")
                    self.ui.console.print("  chat: 总是以问答方式处理")
                    self.ui.console.print("  agent: 总是尝试解析为命令执行")
                    
                    new_mode = self.ui.get_input("请输入新的工作模式 (auto/chat/agent) > ")
                    if new_mode.lower() in ['auto', 'chat', 'agent']:
                        self.working_mode = new_mode.lower()
                        self.ui.console.print(f"[bold green]工作模式已更新为 {new_mode.lower()}[/bold green]")
                    else:
                        self.ui.console.print("[bold red]无效的工作模式[/bold red]")
                else:
                    self.ui.console.print("[bold red]无效的设置编号[/bold red]")
            except ValueError:
                self.ui.console.print("[bold red]请输入数字或q退出[/bold red]")
                
    def _save_config_to_file(self, quiet=False):
        """将配置保存到文件"""
        import yaml
        import os
        
        config_dict = {
            "api": {
                "provider": self.config.api.provider,
                "api_key": self.config.api.api_key,
                "base_url": self.config.api.base_url,
                "model": self.config.api.model,
                "timeout": self.config.api.timeout
            },
            "security": {
                "confirm_dangerous_commands": self.config.security.confirm_dangerous_commands,
                "blocked_commands": self.config.security.blocked_commands,
                "confirm_patterns": self.config.security.confirm_patterns
            },
            "ui": {
                "history_file": self.config.ui.history_file,
                "max_history": self.config.ui.max_history,
                "always_stream": getattr(self.config.ui, 'always_stream', True),
                "theme": getattr(self.config.ui, 'theme', 'default'),
                "language": getattr(self.config.ui, 'language', 'zh'),
                "buffer_size": getattr(self.config.ui, 'buffer_size', 100),
                "refresh_rate": getattr(self.ui, 'refresh_rate', 10),
                "initial_panel_height": getattr(self.ui, 'initial_panel_height', 25),
                "segment_threshold": getattr(self.config.ui, 'segment_threshold', 5000),
                "segment_size": getattr(self.config.ui, 'segment_size', 2000),
                "line_width": getattr(self.config.ui, 'line_width', 80),
                "max_lines": getattr(self.config.ui, 'max_lines', 40),
                "auto_scroll": getattr(self.config.ui, 'auto_scroll', True)
            },
            "logging": {
                "level": self.config.logging.level,
                "file": self.config.logging.file,
                "max_size_mb": self.config.logging.max_size_mb,
                "backup_count": self.config.logging.backup_count
            },
            "analytics": {
                "enable_recommendations": getattr(self.config, 'enable_recommendations', True),
                "collect_analytics": getattr(self.config, 'collect_analytics', True),
                "detailed_stats": getattr(self.config, 'detailed_stats', False),
                "enable_benchmarking": getattr(self.config, 'enable_benchmarking', False)
            }
        }
        
        # 获取默认配置文件路径
        default_config_file = os.path.abspath(self.config.config_file)
        
        # 在安静模式下直接使用默认路径，否则询问用户
        if quiet:
            config_file = default_config_file
        else:
            # 询问用户是否要自定义保存路径
            self.ui.console.print(f"[bold]默认配置文件路径:[/bold] [blue]{default_config_file}[/blue]")
            if self.ui.confirm("是否要自定义配置文件保存路径?"):
                custom_path = self.ui.get_input("请输入配置文件保存路径(含文件名): ")
                if custom_path:
                    config_file = os.path.abspath(custom_path)
                else:
                    config_file = default_config_file
            else:
                config_file = default_config_file
        
        # 确保目录存在
        config_dir = os.path.dirname(config_file)
        if config_dir and not os.path.exists(config_dir):
            try:
                os.makedirs(config_dir, exist_ok=True)
                if not quiet:
                    self.ui.console.print(f"[bold green]已创建目录:[/bold green] [blue]{config_dir}[/blue]")
            except Exception as e:
                self.logger.error(f"创建目录失败: {e}")
                if not quiet:
                    self.ui.show_error(f"创建目录失败: {e}")
                    self.ui.console.print("[bold red]将使用默认配置文件路径[/bold red]")
                config_file = default_config_file
        
        try:
            # 保存前先备份当前配置文件
            if os.path.exists(config_file):
                import shutil
                backup_file = f"{config_file}.bak"
                shutil.copy2(config_file, backup_file)
                if not quiet:
                    self.ui.console.print(f"[bold]已备份原配置文件到: [/bold][blue]{backup_file}[/blue]")
            
            # 写入新的配置文件
            with open(config_file, 'w', encoding='utf-8') as f:
                yaml.dump(config_dict, f, default_flow_style=False, allow_unicode=True)
                
            if not quiet:
                self.ui.console.print(f"[bold green]配置已保存到文件: [/bold green][blue]{config_file}[/blue]")
                # 提示修改生效相关
                self.ui.console.print("[bold yellow]部分设置更改可能需要重启LinuxAgent才能完全生效[/bold yellow]")
            
        except Exception as e:
            self.logger.error(f"保存配置文件失败: {e}", exc_info=True)
            if not quiet:
                self.ui.show_error(f"保存配置文件失败: {e}")
                self.ui.console.print("[bold red]配置保存失败，请检查文件权限或手动修改配置文件[/bold red]")
    
    def run(self):
        """运行代理主循环"""
        self.logger.info("启动LinuxAgent代理")
        
        # 设置UI的agent引用，用于在提示符中显示当前模式
        self.ui.set_agent(self)
        
        # 启动时清屏
        self.ui.clear_screen()
        self.ui.welcome()
        
        # 记录本次会话前的统计值
        self.stats["previous_commands_executed"] = self.stats["commands_executed"]
        self.stats["previous_questions_answered"] = self.stats["questions_answered"]
        self.stats["total_sessions"] = self.stats.get("total_sessions", 0) + 1
        
        try:
            while True:
                try:
                    user_input = self.ui.get_input()
                    
                    if not user_input:
                        continue
                    
                    if self._handle_special_commands(user_input):
                        if user_input.lower() in ["exit", "quit", "bye"]:
                            break
                        continue
                    
                    self.process_user_input(user_input)
                    
                except KeyboardInterrupt:
                    self.logger.info("用户中断")
                    self.ui.console.print("\n[bold yellow]操作已中断[/bold yellow]")
                    
                except Exception as e:
                    self.logger.error(f"主循环异常: {e}", exc_info=True)
                    self.ui.show_error(f"发生错误: {e}")
            
            # 保存统计数据
            self._save_stats()
            # 保存对话历史
            self._save_chat_history()
            
        except Exception as e:
            self.logger.error(f"运行时错误: {e}", exc_info=True)
            # 尝试保存统计数据
            self._save_stats()
            # 尝试保存对话历史
            self._save_chat_history()
        
        self.logger.info("LinuxAgent代理已退出")

    def _parse_create_edit_request(self, user_input: str) -> Optional[str]:
        """解析创建/编辑文件的请求"""
        web_page_patterns = [
            r'创建.*(?:网页|页面|HTML|html|登录页|注册页)',
            r'制作.*(?:网页|页面|HTML|html|登录页|注册页)',
            r'开发.*(?:网页|页面|HTML|html|登录页|注册页)',
            r'编写.*(?:网页|页面|HTML|html|登录页|注册页)'
        ]
        
        for pattern in web_page_patterns:
            if re.search(pattern, user_input):
                file_path_match = re.search(r'保存到\s+([^\s]+)', user_input)
                if file_path_match:
                    file_path = file_path_match.group(1)
                else:
                    file_path = "index.html"
                
                editor = "vim"
                if "nano" in user_input.lower():
                    editor = "nano"
                elif "emacs" in user_input.lower():
                    editor = "emacs"
                
                return f"{editor} {file_path}"
        
        return None
    
    def _is_file_creation_command(self, command: str) -> bool:
        """检查命令是否是创建文件的命令"""
        creation_patterns = [
            r'echo .* > .+\.html',
            r'cat > .+\.html',
            r'touch .+\.html',
            r'printf .* > .+\.html'
        ]
        
        return any(re.search(pattern, command) for pattern in creation_patterns)
    
    def _extract_file_path(self, command: str) -> Optional[str]:
        """从命令中提取文件路径"""
        redirect_match = re.search(r'> ([^\s;|&]+)', command)
        if redirect_match:
            return redirect_match.group(1)
            
        touch_match = re.search(r'touch ([^\s;|&]+)', command)
        if touch_match:
            return touch_match.group(1)
            
        return None
        
    def _ensure_directory_exists(self, file_path: str) -> None:
        """确保文件所在目录存在"""
        try:
            dir_path = os.path.dirname(file_path)
            if dir_path and not os.path.exists(dir_path):
                os.makedirs(dir_path, exist_ok=True)
        except Exception as e:
            self.logger.error(f"创建目录失败: {e}")
            
    def _get_preferred_editor(self) -> str:
        """获取首选编辑器"""
        editors = ["vim", "nano", "vi", "emacs"]
        
        if "EDITOR" in os.environ:
            editor = os.environ["EDITOR"]
            if any(ed in editor for ed in editors):
                return editor
                
        return "vim"
        
    def _get_template_suggestion(self, file_path: str, file_type: str) -> None:
        """从LLM获取模板建议"""
        try:
            system_info = self.executor.get_system_info()
            prompt = f"需要创建{file_type}类型的文件：{file_path}，提供简洁的编辑建议。"
            response = self.api.get_template_suggestion(prompt, system_info)
            
            if response and "suggestion" in response:
                self.ui.console.print(f"[bold]编辑建议:[/bold] {response['suggestion']}")
        except Exception as e:
            self.logger.error(f"获取模板建议失败: {e}")

    def _is_interactive_command(self, command: str) -> bool:
        """判断命令是否是交互式命令"""
        interactive_commands = [
            "vim", "vi", "nano", "emacs", "less", "more", "top", "htop",
            "watch", "tail -f", "mysql", "psql", "telnet", "ssh", "python",
            "ipython", "bash", "sh", "zsh", "ksh", "csh", "fish"
        ]
        
        first_word = command.split()[0] if command else ""
        if first_word in interactive_commands:
            return True
            
        return any(ic in command for ic in interactive_commands)
    
    def _is_complex_command(self, command: str) -> bool:
        """判断命令是否复杂"""
        if command.count('&&') > 2 or command.count(';') > 2:
            return True
            
        pkg_managers = ['dnf', 'yum', 'apt', 'apt-get', 'pacman', 'zypper']
        pkg_operations = ['update', 'upgrade', 'install']
        
        for pm in pkg_managers:
            for op in pkg_operations:
                if f"{pm} {op}" in command:
                    return True
                    
        return False
    
    def _split_complex_command(self, command: str) -> List[str]:
        """拆分复杂命令为多个简单命令"""
        if '&&' in command:
            return [cmd.strip() for cmd in command.split('&&')]
        elif ';' in command:
            return [cmd.strip() for cmd in command.split(';')]
        else:
            return [command]
    
    def _execute_commands_sequence(self, commands: List[str], explanation: str) -> None:
        """按顺序执行多个命令"""
        self.ui.console.print(f"[bold]将按以下顺序执行命令:[/bold]")
        for i, cmd in enumerate(commands, 1):
            self.ui.console.print(f"{i}. [yellow]{cmd}[/yellow]")
            
        total_commands = len(commands)
        results = []
        
        for i, cmd in enumerate(commands, 1):
            self.ui.console.print(f"\n[bold]执行步骤 {i}/{total_commands}:[/bold] [yellow]{cmd}[/yellow]")
            
            is_safe, unsafe_reason = self.executor.is_command_safe(cmd)
            if not is_safe and self.config.security.confirm_dangerous_commands:
                confirmation_message = f"此命令可能有风险: {unsafe_reason}。确认执行?"
                if not self.ui.confirm(confirmation_message):
                    self.ui.console.print("[bold red]跳过此步骤[/bold red]")
                    results.append((cmd, "", "用户取消执行", 1))
                    continue
            
            start_time = time.time()
            with self.ui.console.status(f"[bold green]执行步骤 {i}/{total_commands}...[/bold green]", spinner="dots"):
                stdout, stderr, return_code = self.executor.execute_command(cmd)
            end_time = time.time()
            execution_time = end_time - start_time
            
            # 记录命令执行基准数据
            if self.enable_benchmarking:
                self._record_command_benchmark(cmd, execution_time)
            
            # 记录命令历史，用于推荐系统
            success = return_code == 0
            self._add_to_command_history(cmd, success, user_input)
            
            status = "成功" if success else "失败"
            self.ui.print_command_execution_info(cmd, start_time, end_time, status)
            
            if success:
                self.ui.console.print(f"[bold green]步骤 {i} 执行成功[/bold green]")
                if stdout:
                    self.ui.console.print("[bold]输出:[/bold]")
                    max_output_lines = 20
                    output_lines = stdout.splitlines()
                    if len(output_lines) > max_output_lines:
                        shown_output = "\n".join(output_lines[:10] + ["...省略中间内容..."] + output_lines[-10:])
                        self.ui.console.print(shown_output)
                        self.ui.console.print(f"[dim](输出共 {len(output_lines)} 行，仅显示部分内容)[/dim]")
                    else:
                        self.ui.console.print(stdout)
            else:
                self.ui.console.print(f"[bold red]步骤 {i} 执行失败[/bold red]")
                if stderr:
                    self.ui.console.print("[bold red]错误信息:[/bold red]")
                    self.ui.console.print(stderr)
            
            results.append((cmd, stdout, stderr, return_code))
            
            if return_code != 0 and i < total_commands:
                if not self.ui.confirm("上一步执行失败，是否继续执行后续步骤?"):
                    self.ui.console.print("[bold yellow]用户中止后续步骤[/bold yellow]")
                    break
        
        self.ui.console.print("\n[bold]所有步骤执行完毕，正在分析结果...[/bold]")
        all_stdout = "\n".join([f"命令 {i+1}: {res[0]}\n输出:\n{res[1]}\n" for i, res in enumerate(results)])
        all_stderr = "\n".join([f"命令 {i+1} 错误:\n{res[2]}\n" if res[2] else "" for i, res in enumerate(results)])
        
        # 记录API基准测试数据
        if self.enable_benchmarking:
            start_time = time.time()
        
        analysis = self.api.analyze_output("; ".join([r[0] for r in results]), all_stdout, all_stderr)
        
        if self.enable_benchmarking:
            api_response_time = time.time() - start_time
            self._record_api_benchmark("output_analysis", api_response_time)
        
        self.ui.show_result(analysis, explanation)
    
    def _parse_interactive_command(self, user_input: str) -> Optional[str]:
        """解析常见交互式命令模式"""
        edit_patterns = [
            r'使用\s+(\w+)\s+编辑\s+([^\s]+)(\s+文件)?',
            r'用\s+(\w+)\s+打开\s+([^\s]+)(\s+文件)?',
            r'编辑\s+([^\s]+)(\s+文件)?(\s+用\s+(\w+))?'
        ]
        
        for pattern in edit_patterns:
            match = re.search(pattern, user_input)
            if match:
                groups = match.groups()
                if pattern == edit_patterns[0] or pattern == edit_patterns[1]:
                    editor = groups[0]
                    file_path = groups[1]
                elif pattern == edit_patterns[2]:
                    file_path = groups[0]
                    editor = groups[3] if groups[3] else "vim"
                else:
                    continue
                    
                if editor not in ["vim", "vi", "nano", "emacs"]:
                    continue
                    
                return f"{editor} {file_path}"
                
        return None
    
    def _execute_interactive_operation(self, command: str) -> None:
        """执行交互式操作"""
        self.ui.console.print(f"[bold]执行交互式命令:[/bold] [yellow]{command}[/yellow]")
        
        is_editor = any(editor in command.split()[0] for editor in ["vim", "vi", "nano", "emacs"])
        if is_editor:
            file_path = command.split()[-1]
            if file_path.endswith('.html'):
                file_type = "HTML页面"
                if 'login' in file_path.lower() or '登录' in file_path or '注册' in file_path:
                    file_type = "登录注册页面"
                self._get_template_suggestion(file_path, file_type)
        
        stdout, stderr, return_code = self.executor.execute_command(command)
        
        if return_code == 0:
            self.ui.console.print("[bold green]命令执行成功[/bold green]")
        else:
            self.ui.show_error(f"命令执行失败: {stderr}")
            
    def _execute_command_sequence_from_api(self, commands_array):
        """执行API返回的命令数组"""
        self.ui.console.print("[bold]将按顺序执行以下命令:[/bold]")
        command_list = []
        explanation_list = []
        
        for i, cmd_obj in enumerate(commands_array):
            cmd = cmd_obj.get("command", "")
            expl = cmd_obj.get("explanation", f"步骤 {i+1}")
            if cmd:
                command_list.append(cmd)
                explanation_list.append(expl)
                self.ui.console.print(f"{i+1}. [yellow]{cmd}[/yellow] - {expl}")
        
        if not command_list:
            self.ui.console.print("[bold red]没有可执行的命令[/bold red]")
            return
            
        # 执行命令序列
        command_outputs = []
        failed_commands = []  
        
        for i, (cmd, expl) in enumerate(zip(command_list, explanation_list)):
            self.ui.console.print(f"\n[bold]执行步骤 {i+1}/{len(command_list)}:[/bold] [yellow]{cmd}[/yellow]")
            self.ui.console.print(f"[dim]{expl}[/dim]")
            
            # 检查命令安全性
            is_safe, unsafe_reason = self.executor.is_command_safe(cmd)
            if not is_safe and self.config.security.confirm_dangerous_commands:
                confirmation_message = f"此命令可能有风险: {unsafe_reason}。确认执行?"
                if not self.ui.confirm(confirmation_message):
                    self.ui.console.print("[bold red]跳过此步骤[/bold red]")
                    command_outputs.append(("", f"用户拒绝执行：{cmd}", 1))
                    # 添加到对话历史
                    assistant_response = f"命令 '{cmd}' 被用户拒绝执行，原因: {unsafe_reason}"
                    self.chat_history.append({"role": "assistant", "content": assistant_response})
                    continue
            
            is_interactive = self._is_interactive_command(cmd)
            start_time = time.time()
            
            if is_interactive:
                self.ui.console.print("[bold cyan]这是一个交互式命令，将直接在终端中执行...[/bold cyan]")
                stdout, stderr, return_code = self.executor.execute_command(cmd)
            else:
                with self.ui.console.status(f"[bold green]执行中...[/bold green]", spinner="dots"):
                    stdout, stderr, return_code = self.executor.execute_command(cmd)
            
            end_time = time.time()
            status = "成功" if return_code == 0 else "失败"
            
            self.ui.print_command_execution_info(cmd, start_time, end_time, status)
            
            if return_code == 0:
                self.ui.console.print(f"[bold green]步骤 {i+1} 执行成功[/bold green]")
                if stdout and not is_interactive:
                    self.ui.console.print("[bold]输出:[/bold]")
                    max_output_lines = 20
                    output_lines = stdout.splitlines()
                    if len(output_lines) > max_output_lines:
                        shown_output = "\n".join(output_lines[:10] + ["...省略中间内容..."] + output_lines[-10:])
                        self.ui.console.print(shown_output)
                        self.ui.console.print(f"[dim](输出共 {len(output_lines)} 行，仅显示部分内容)[/dim]")
                    else:
                        self.ui.console.print(stdout)
            else:
                self.ui.console.print(f"[bold red]步骤 {i+1} 执行失败[/bold red]")
                if stderr:
                    self.ui.console.print("[bold red]错误信息:[/bold red]")
                    self.ui.console.print(stderr)

                failed_commands.append((i+1, cmd, stderr, expl))
            
            command_outputs.append((stdout, stderr, return_code))
            
            self.stats["commands_executed"] += 1
            if return_code == 0:
                self.stats["successful_commands"] += 1
            else:
                self.stats["failed_commands"] += 1
            
            if return_code != 0 and i < len(command_list) - 1:
                if not self.ui.confirm("上一步执行失败，是否继续执行后续步骤?"):
                    self.ui.console.print("[bold yellow]用户中止后续步骤[/bold yellow]")
                    break
        
        # 添加到对话历史
        command_summary = "\n".join([f"{i+1}. {cmd} - {'成功' if out[2] == 0 else '失败'}" 
                                 for i, (cmd, out) in enumerate(zip(command_list, command_outputs))])
        assistant_response = f"已执行命令序列:\n{command_summary}"
        self.chat_history.append({"role": "assistant", "content": assistant_response})
        self._save_chat_history()
        
        # 完成所有命令后显示摘要
        self.ui.console.print("\n[bold]命令序列执行完毕[/bold]")
        successful = sum(1 for _, _, code in command_outputs if code == 0)
        failed = len(command_outputs) - successful
        self.ui.console.print(f"总计: [green]{successful}个成功[/green], [red]{failed}个失败[/red]")
        
        if failed_commands:
            self.ui.console.print("\n[bold yellow]检测到以下命令执行失败:[/bold yellow]")
            for step, cmd, err, expl in failed_commands:
                self.ui.console.print(f"步骤 {step}: [yellow]{cmd}[/yellow] - {expl}")
                self.ui.console.print(f"[dim]错误: {err}[/dim]")
            
            if self.ui.confirm("是否需要分析失败原因并提供解决方案?"):
                self._analyze_failed_commands(failed_commands)
        
    def _analyze_failed_commands(self, failed_commands):
        """分析失败的命令，提供错误原因和解决方案"""
        self.ui.console.print("\n[bold]正在分析错误原因...[/bold]")
        
        # 特殊情况快速处理，无需调用API
        special_handled = []
        regular_commands = []

        for cmd_info in failed_commands:
            step, cmd, err, expl = cmd_info

            if "crontab -l" in cmd and "no crontab for" in err:
                special_handled.append({
                    "step": step,
                    "cmd": cmd,
                    "analysis": "当前用户没有配置定时任务，这不是真正的错误。",
                    "solution": [
                        "如需创建定时任务，可使用命令: crontab -e",
                        "这将打开编辑器，您可以添加定时任务，格式为: 分钟 小时 日 月 星期 要执行的命令",
                        "例如，每天凌晨2点执行备份: 0 2 * * * /path/to/backup.sh"
                    ]
                })
            elif "command not found" in err:
                special_handled.append({
                    "step": step,
                    "cmd": cmd,
                    "analysis": f"命令'{cmd.split()[0]}'未找到，可能需要安装相应的软件包。",
                    "solution": [
                        f"尝试使用包管理器安装: sudo apt install {cmd.split()[0]} 或 sudo yum install {cmd.split()[0]}",
                        "或者确认命令名称拼写是否正确"
                    ]
                })
            elif "permission denied" in err.lower():
                special_handled.append({
                    "step": step,
                    "cmd": cmd,
                    "analysis": "权限不足，无法执行该命令。",
                    "solution": [
                        f"尝试使用sudo执行: sudo {cmd}",
                        "或者检查文件权限并修改: chmod +x <文件名>"
                    ]
                })
            else:
                regular_commands.append(cmd_info)
        
        for info in special_handled:
            self.ui.console.print(f"\n[bold]分析步骤 {info['step']}:[/bold] [yellow]{info['cmd']}[/yellow]")
            self.ui.console.print("[bold]错误分析:[/bold]")
            self.ui.console.print(info['analysis'])
            self.ui.console.print("\n[bold]解决方案:[/bold]")
            for i, sol in enumerate(info['solution'], 1):
                self.ui.console.print(f"{i}. {sol}")
            
            # 将分析添加到对话历史
            analysis_response = f"错误分析: {info['analysis']}\n\n解决方案:\n" + "\n".join([f"{i}. {s}" for i, s in enumerate(info['solution'], 1)])
            self.chat_history.append({"role": "assistant", "content": analysis_response})
        
        if regular_commands:
            system_info = self.executor.get_system_info()

            combined_query = "以下多个命令执行失败，请分析每个命令失败的原因并提供解决方案：\n\n"
            
            for i, (step, cmd, err, expl) in enumerate(regular_commands, 1):
                combined_query += f"命令{i}: {cmd}\n"
                combined_query += f"错误信息{i}: {err}\n"
                combined_query += f"命令目的{i}: {expl}\n\n"
            
            combined_query += "请为每个命令单独分析，并提供简洁明了的解决方案。"
            
            messages = [
                {"role": "system", "content": 
                    "你是一个Linux错误分析专家。请分析多个命令执行失败的原因，并提供各自的解决方案。" +
                    "分析要精确、专业，并且提供实用的解决方法。\n\n系统信息：" + 
                    json.dumps(system_info, ensure_ascii=False)
                },
                {"role": "user", "content": combined_query}
            ]
            
            self.ui.console.print("[bold cyan]生成分析结果中...[/bold cyan]")
            
            try:
                full_response = ""
                
                def collect_analysis_response():
                    nonlocal full_response
                    for chunk in self.api.stream_response(messages):
                        full_response += chunk
                        yield chunk
                
                self.ui.stream_output(collect_analysis_response())
                
                if full_response:
                    for i, (step, cmd, _, _) in enumerate(regular_commands, 1):
                        self.ui.console.print(f"\n[bold cyan]步骤 {step}[/bold cyan] 的分析已包含在上述结果中")
                    
                    self.chat_history.append({"role": "assistant", "content": full_response})
                    self._save_chat_history()
            
            except Exception as e:
                self.logger.error(f"分析失败命令时出错: {e}", exc_info=True)
                self.ui.show_error(f"分析失败命令时出错: {e}")
        
        self.ui.console.print("\n[bold green]错误分析完成[/bold green]")


    def _export_chat_history(self, format_type: str, output_file: str) -> None:
        """
        导出对话历史
        
        Args:
            format_type: 导出格式，支持markdown/md, text/txt, script/sh
            output_file: 输出文件名（不含扩展名）
        """
        self.logger.info(f"导出对话历史为{format_type}格式")
        
        if not self.chat_history:
            self.ui.console.print("[bold yellow]对话历史为空，无法导出[/bold yellow]")
            return
        
        if format_type in ["markdown", "md"]:
            extension = ".md"
            format_name = "Markdown"
        elif format_type in ["text", "txt"]:
            extension = ".txt"
            format_name = "文本"
        elif format_type in ["script", "sh"]:
            extension = ".sh"
            format_name = "Shell脚本"
        else:
            extension = ".md"
            format_name = "Markdown"
        
        # 显示选择对话历史模式
        self.ui.console.print("[bold]导出模式:[/bold]")
        self.ui.console.print("1. 导出所有对话历史")
        self.ui.console.print("2. 选择性导出部分对话")
        
        export_mode = self.ui.get_input("请选择导出模式 (1/2) > ")
        
        chat_to_export = []
        if export_mode == "2":
            from rich.table import Table
            table = Table(title="对话历史列表")
            table.add_column("序号", style="cyan", justify="right")
            table.add_column("角色", style="cyan")
            table.add_column("内容预览", style="white")
            
            for i, msg in enumerate(self.chat_history):
                role = msg.get("role", "")
                content = msg.get("content", "")
                
                if role == "user":
                    role_display = "用户"
                elif role == "assistant":
                    role_display = "助手"
                elif role == "system":
                    role_display = "系统"
                else:
                    role_display = role
                
                content_preview = content[:50] + "..." if len(content) > 50 else content
                
                table.add_row(str(i+1), role_display, content_preview)
            
            self.ui.console.print(table)
            
            self.ui.console.print("\n[bold]请选择要导出的对话:[/bold]")
            self.ui.console.print("格式：输入序号范围(例如 1-5)或单个序号，多个选择用逗号分隔(例如 1,3,5-7)")
            self.ui.console.print("示例: '1-5,7,9-11' 表示导出序号为1至5、7、9至11的对话")
            
            selection = self.ui.get_input("导出选择 > ")
            
            try:
                selected_indices = set()
                for part in selection.split(','):
                    if '-' in part:
                        start, end = map(int, part.split('-'))
                        selected_indices.update(range(start - 1, end))
                    else:
                        selected_indices.add(int(part) - 1)
                
                selected_indices = sorted([idx for idx in selected_indices if 0 <= idx < len(self.chat_history)])
                
                for idx in selected_indices:
                    chat_to_export.append(self.chat_history[idx])
                    
                if not chat_to_export:
                    self.ui.console.print("[bold yellow]未选择任何有效对话，将取消导出[/bold yellow]")
                    return
                    
                self.ui.console.print(f"[bold green]已选择 {len(chat_to_export)} 条对话进行导出[/bold green]")
            except Exception as e:
                self.logger.error(f"解析选择时出错: {e}")
                self.ui.console.print("[bold red]选择格式错误，将导出所有对话[/bold red]")
                chat_to_export = self.chat_history.copy()
        else:
            chat_to_export = self.chat_history.copy()
        
        if output_file == f"linuxagent_chat_{int(time.time())}":
            default_path = os.path.join(os.getcwd(), output_file + extension)
            self.ui.console.print(f"[bold]默认导出路径:[/bold] [blue]{default_path}[/blue]")
            if self.ui.confirm("是否要自定义导出路径?"):
                custom_path = self.ui.get_input("请输入导出路径(含文件名): ")
                if custom_path:
                    output_file = custom_path
                    if not output_file.endswith(extension):
                        output_file += extension
        else:
            if not output_file.endswith(extension):
                output_file += extension
            
        if not os.path.isabs(output_file):
            output_file = os.path.join(os.getcwd(), output_file)
        
        output_dir = os.path.dirname(output_file)
        if output_dir and not os.path.exists(output_dir):
            try:
                os.makedirs(output_dir, exist_ok=True)
                self.ui.console.print(f"[bold green]已创建目录:[/bold green] [blue]{output_dir}[/blue]")
            except Exception as e:
                self.logger.error(f"创建目录失败: {e}")
                self.ui.show_error(f"创建目录失败: {e}")
                return
        
        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                if format_type in ["markdown", "md"]:
                    f.write(f"# LinuxAgent 会话记录\n\n")
                    f.write(f"导出时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                    
                    for msg in chat_to_export:
                        role = msg.get("role", "")
                        content = msg.get("content", "")
                        
                        if role == "user":
                            f.write(f"## 用户\n\n{content}\n\n")
                        elif role == "assistant":
                            f.write(f"## 助手\n\n{content}\n\n")
                
                elif format_type in ["text", "txt"]:
                    f.write(f"LinuxAgent 会话记录\n")
                    f.write(f"导出时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                    
                    for msg in chat_to_export:
                        role = msg.get("role", "")
                        content = msg.get("content", "")
                        
                        if role == "user":
                            f.write(f"用户: {content}\n\n")
                        elif role == "assistant":
                            f.write(f"助手: {content}\n\n")
                
                elif format_type in ["script", "sh"]:
                    f.write("#!/bin/bash\n")
                    f.write(f"# LinuxAgent 会话记录 - 可执行命令脚本\n")
                    f.write(f"# 导出时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                    
                    extracted_commands = []
                    command_count = 0
                    commands_extracted = set()  
                    
                    for msg in chat_to_export:
                        role = msg.get("role", "")
                        content = msg.get("content", "")
                        
                        if role == "assistant":
                            # 提取方式1: 查找"命令:"格式
                            command_lines = content.split("\n")
                            for line in command_lines:
                                line = line.strip()
                                if line.startswith("命令:"):
                                    cmd = line.replace("命令:", "").strip()
                                    if cmd and cmd not in commands_extracted:
                                        extracted_commands.append({"command": cmd, "source": "助手回复", "context": content[:50]})
                                        commands_extracted.add(cmd)
                        
                        # 提取方式2: 查找已执行命令序列
                        if "已执行命令序列:" in content:
                            lines = content.split("\n")
                            in_command_list = False
                            
                            for line in lines:
                                line = line.strip()
                                
                                if "已执行命令序列:" in line:
                                    in_command_list = True
                                    continue
                                
                                if in_command_list and line:
                                    match = re.search(r'\d+\.\s+([^-]+)(?:\s+-\s+.+)?', line)
                                    if match:
                                        cmd = match.group(1).strip()
                                        if cmd and cmd not in commands_extracted:
                                            extracted_commands.append({"command": cmd, "source": "命令序列", "context": content[:50]})
                                            commands_extracted.add(cmd)
                
                    for msg in chat_to_export:
                        role = msg.get("role", "")
                        content = msg.get("content", "")
                        
                        if role == "user":
                            words = content.split()
                            if words:
                                first_word = words[0].lower()
                                simple_commands = [
                                    "ls", "pwd", "cd", "cat", "echo", "mkdir", "touch", "cp", "mv", "rm", 
                                    "ps", "df", "du", "grep", "find", "top", "free", "uptime", "systemctl",
                                    "chmod", "chown", "whoami", "id", "ping", "ifconfig", "ip", "netstat",
                                    "ssh", "scp", "rsync", "wget", "curl", "head", "tail", "less", "sort",
                                    "uniq", "wc", "sed", "awk", "crontab", "date", "history"
                                ]
                                if first_word in simple_commands:
                                    if content not in commands_extracted:
                                        extracted_commands.append({"command": content, "source": "用户输入", "context": content})
                                        commands_extracted.add(content)
                    
                    if extracted_commands:
                        from rich.table import Table
                        cmd_table = Table(title="提取到的命令列表")
                        cmd_table.add_column("序号", style="cyan", justify="right")
                        cmd_table.add_column("命令", style="green")
                        cmd_table.add_column("来源", style="dim")
                        
                        for i, cmd_info in enumerate(extracted_commands, 1):
                            cmd_table.add_row(
                                str(i), 
                                cmd_info["command"], 
                                cmd_info["source"]
                            )
                        
                        self.ui.console.print(cmd_table)
                        
                        self.ui.console.print("\n[bold]请选择要导出的命令:[/bold]")
                        self.ui.console.print("格式：输入序号范围(例如 1-5)或单个序号，多个选择用逗号分隔")
                        self.ui.console.print("特殊选项: 'all' 导出所有命令")
                        
                        cmd_selection = self.ui.get_input("命令选择 > ")
                        
                        commands_to_export = []
                        if cmd_selection.lower() == 'all':
                            commands_to_export = extracted_commands
                        else:
                            try:
                                selected_cmd_indices = set()
                                for part in cmd_selection.split(','):
                                    if '-' in part:
                                        start, end = map(int, part.split('-'))
                                        selected_indices = range(start - 1, end)
                                        selected_cmd_indices.update(selected_indices)
                                    else:
                                        selected_cmd_indices.add(int(part) - 1)
                                
                                selected_cmd_indices = sorted([idx for idx in selected_cmd_indices if 0 <= idx < len(extracted_commands)])
                                
                                for idx in selected_cmd_indices:
                                    commands_to_export.append(extracted_commands[idx])
                                
                                if not commands_to_export:
                                    self.ui.console.print("[bold yellow]未选择任何有效命令，将取消导出[/bold yellow]")
                                    return
                            except Exception as e:
                                self.logger.error(f"解析命令选择时出错: {e}")
                                self.ui.console.print("[bold red]选择格式错误，将导出所有命令[/bold red]")
                                commands_to_export = extracted_commands
                        

                        for i, cmd_info in enumerate(commands_to_export, 1):
                            f.write(f"echo '执行命令 {i}: {cmd_info['command']}'\n")
                            f.write(f"{cmd_info['command']}\n\n")
                    else:

                        f.write("# 未从对话历史中找到可执行命令\n")
                        f.write("echo '未从对话历史中找到可执行命令'\n")
            
            self.ui.console.print(f"[bold green]对话历史已导出为{format_name}格式:[/bold green] [blue]{output_file}[/blue]")
            

            if format_type in ["script", "sh"]:
                try:
                    import stat
                    current_permissions = os.stat(output_file).st_mode
                    os.chmod(output_file, current_permissions | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
                    self.ui.console.print("[bold green]已设置脚本为可执行文件[/bold green]")
                except Exception as e:
                    self.logger.error(f"设置脚本执行权限失败: {e}")
                    self.ui.console.print("[bold yellow]无法设置脚本为可执行文件，请手动设置权限[/bold yellow]")
        
        except Exception as e:
            self.logger.error(f"导出对话历史失败: {e}", exc_info=True)
            self.ui.show_error(f"导出对话历史失败: {e}")

    def _get_command_category(self, command: str) -> str:
        """
        获取命令的类别
        
        Args:
            command: 命令名
            
        Returns:
            命令类别
        """

        file_commands = ["ls", "cp", "mv", "rm", "mkdir", "touch", "chmod", "chown", 
                        "find", "tar", "zip", "unzip", "rsync", "scp", "cat", "head", 
                        "tail", "less", "more"]

        system_commands = ["uname", "df", "du", "free", "top", "htop", "vmstat", 
                          "iostat", "lsof", "dmesg", "uptime"]

        process_commands = ["ps", "kill", "pkill", "pgrep", "nice", "renice", 
                           "nohup", "screen", "tmux", "bg", "fg", "jobs"]
 
        network_commands = ["ping", "ifconfig", "ip", "netstat", "ss", "traceroute", 
                           "route", "iptables", "curl", "wget", "ssh", "telnet"]
        
        package_commands = ["dnf", "yum", "apt", "apt-get", "pacman", "zypper"]

        text_commands = ["grep", "find", "sed", "awk", "awk", "awk", "awk", "awk", "awk", "awk"]

        other_commands = ["tar", "zip", "unzip", "rsync", "scp", "cat", "head", "tail", "less", "more"]

        if command.split()[0] in file_commands:
            return "file_operations"
        elif command.split()[0] in system_commands:
            return "system_info"
        elif command.split()[0] in process_commands:
            return "process_management"
        elif command.split()[0] in network_commands:
            return "network"
        elif command.split()[0] in package_commands:
            return "package_management"
        elif command.split()[0] in text_commands:
            return "text_processing"
        else:
            return "other"

    def _load_benchmarks(self) -> Dict[str, Any]:
        """加载性能基准测试数据"""
        default_data = {
            "command_execution_times": {},
            "api_response_times": {
                "command_generation": [],
                "question_answering": [],
                "output_analysis": []
            }
        }
        
        if os.path.exists(self.benchmark_file):
            try:
                with open(self.benchmark_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                # 确保所有键都存在
                for key, value in default_data.items():
                    if key not in data:
                        data[key] = value
                        
                return data
            except Exception as e:
                self.logger.error(f"加载性能基准测试数据失败: {e}")
                return default_data
        return default_data

    def _save_benchmarks(self) -> None:
        """保存性能基准测试数据"""
        if not self.enable_benchmarking:
            return
            
        try:
            with open(self.benchmark_file, 'w', encoding='utf-8') as f:
                json.dump(self.benchmarks, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.error(f"保存性能基准测试数据失败: {e}")

    def _record_command_benchmark(self, command: str, execution_time: float) -> None:
        """
        记录命令执行时间
        
        Args:
            command: 执行的命令
            execution_time: 执行时间（秒）
        """
        if not self.enable_benchmarking:
            return
            
        cmd_parts = command.split()
        if cmd_parts:
            base_cmd = cmd_parts[0]
            
            if base_cmd not in self.benchmarks["command_execution_times"]:
                self.benchmarks["command_execution_times"][base_cmd] = []
                
            self.benchmarks["command_execution_times"][base_cmd].append(execution_time)
            
            # 限制记录数量，保留最近30条
            if len(self.benchmarks["command_execution_times"][base_cmd]) > 30:
                self.benchmarks["command_execution_times"][base_cmd] = self.benchmarks["command_execution_times"][base_cmd][-30:]
                
            # 定期保存
            self._save_benchmarks()

    def _record_api_benchmark(self, api_type: str, response_time: float) -> None:
        """
        记录API响应时间
        
        Args:
            api_type: API类型（command_generation, question_answering, output_analysis）
            response_time: 响应时间（秒）
        """
        if not self.enable_benchmarking:
            return
            
        if api_type in self.benchmarks["api_response_times"]:
            self.benchmarks["api_response_times"][api_type].append(response_time)
            
            # 限制记录数量，保留最近30条
            if len(self.benchmarks["api_response_times"][api_type]) > 30:
                self.benchmarks["api_response_times"][api_type] = self.benchmarks["api_response_times"][api_type][-30:]
                
            # 定期保存
            self._save_benchmarks()

    def show_analytics_dashboard(self) -> None:
        """显示使用分析仪表板"""
        from rich.table import Table
        from rich.panel import Panel
        from datetime import datetime
        
        # 只在收集分析数据时显示
        if not self.collect_analytics:
            self.ui.console.print("[bold yellow]使用分析功能未启用。请在设置中启用数据分析功能。[/bold yellow]")
            return
            
        # 命令类别使用情况
        categories_table = Table(title="命令类别使用统计")
        categories_table.add_column("类别", style="cyan")
        categories_table.add_column("执行次数", style="green", justify="right")
        categories_table.add_column("成功率", style="yellow", justify="right")
        
        for cat_name, cat_data in self.analytics_data["command_categories"].items():
            # 格式化类别名称
            category_names = {
                "file_operations": "文件操作",
                "system_info": "系统信息",
                "process_management": "进程管理",
                "network": "网络操作",
                "package_management": "包管理",
                "user_management": "用户管理",
                "text_processing": "文本处理",
                "other": "其他命令"
            }
            
            display_name = category_names.get(cat_name, cat_name)
            count = cat_data["count"]
            
            if count > 0:
                success_rate = f"{cat_data['success_rate'] * 100:.1f}%"
                categories_table.add_row(display_name, str(count), success_rate)
        
        # 最常用命令
        top_commands = sorted(self.analytics_data["command_frequency"].items(), 
                              key=lambda x: x[1], reverse=True)[:10]
        
        commands_table = Table(title="最常用命令")
        commands_table.add_column("命令", style="cyan")
        commands_table.add_column("使用次数", style="green", justify="right")
        
        for cmd, count in top_commands:
            commands_table.add_row(cmd, str(count))
        
        # 使用时间分布
        time_table = Table(title="使用时间分布")
        time_table.add_column("时段", style="cyan")
        time_table.add_column("使用次数", style="green", justify="right")
        
        # 按4小时分组显示
        hour_groups = [
            ("00:00 - 05:59", sum(self.analytics_data["hourly_usage"].get(str(h), 0) for h in range(0, 6))),
            ("06:00 - 11:59", sum(self.analytics_data["hourly_usage"].get(str(h), 0) for h in range(6, 12))),
            ("12:00 - 17:59", sum(self.analytics_data["hourly_usage"].get(str(h), 0) for h in range(12, 18))),
            ("18:00 - 23:59", sum(self.analytics_data["hourly_usage"].get(str(h), 0) for h in range(18, 24)))
        ]
        
        for time_range, count in hour_groups:
            time_table.add_row(time_range, str(count))
        
        # 按星期显示
        weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        day_table = Table(title="每日使用情况")
        day_table.add_column("星期", style="cyan")
        day_table.add_column("使用次数", style="green", justify="right")
        
        for day_num, day_name in enumerate(weekday_names):
            count = self.analytics_data["daily_usage"].get(str(day_num), 0)
            day_table.add_row(day_name, str(count))
            
            # 总体使用情况
        total_commands = sum(self.analytics_data["command_frequency"].values())
        api_calls = self.analytics_data["api_calls"]
        
        summary = [
            f"总执行命令数: {total_commands}",
            f"API 调用次数: {api_calls.get('total', 0)}",
            f"成功率: {(api_calls.get('successful', 0) / api_calls.get('total', 1) * 100):.1f}% (API调用)"
        ]
        
        if self.enable_benchmarking and self.benchmarks.get("command_execution_times"):
            avg_times = {}
            for cmd, times in self.benchmarks["command_execution_times"].items():
                if times:
                    avg_times[cmd] = sum(times) / len(times)
            
            slowest_commands = sorted(avg_times.items(), key=lambda x: x[1], reverse=True)[:5]
            
            if slowest_commands:
                perf_table = Table(title="命令性能分析（平均执行时间）")
                perf_table.add_column("命令", style="cyan")
                perf_table.add_column("平均执行时间", style="yellow", justify="right")
                
                for cmd, avg_time in slowest_commands:
                    perf_table.add_row(cmd, f"{avg_time:.2f} 秒")
                    
                self.ui.console.print(perf_table)
        
        # 显示所有表格
        self.ui.console.print(Panel(
            "\n".join(summary),
            title="使用统计摘要",
            border_style="green"
        ))
        
        self.ui.console.print(categories_table)
        self.ui.console.print(commands_table)
        
        # 显示时间分布
        self.ui.console.print(time_table)
        self.ui.console.print(day_table)
        
        # 显示更新时间
        self.ui.console.print(f"\n[dim]数据更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}[/dim]")

        # 显示性能建议
        if self.detailed_stats and total_commands > 10:
            low_success_categories = []
            for cat_name, cat_data in self.analytics_data["command_categories"].items():
                if cat_data["count"] > 5 and cat_data["success_rate"] < 0.7:
                    low_success_categories.append((cat_name, cat_data["success_rate"]))
            
            if low_success_categories:
                suggestions = ["[bold]改进建议:[/bold]"]
                
                category_names = {
                    "file_operations": "文件操作",
                    "system_info": "系统信息",
                    "process_management": "进程管理",
                    "network": "网络操作",
                    "package_management": "包管理",
                    "user_management": "用户管理",
                    "text_processing": "文本处理",
                    "other": "其他命令"
                }
                
                for cat_name, success_rate in low_success_categories:
                    display_name = category_names.get(cat_name, cat_name)
                    suggestions.append(f"- {display_name}命令的成功率较低 ({success_rate*100:.1f}%)，可能需要更仔细地检查语法")
                
                self.ui.console.print(Panel(
                    "\n".join(suggestions),
                    title="性能改进建议",
                    border_style="yellow"
                ))

    def show_command_recommendations(self, recommendations: List[Dict[str, str]]):
        """
        显示命令推荐
        
        Args:
            recommendations: 推荐命令列表，每项包含命令和描述
        """
        if not recommendations:
            return
            
        from rich.table import Table
        
        table = Table(title="命令推荐")
        table.add_column("命令", style="green")
        table.add_column("描述", style="dim")
        
        for rec in recommendations:
            table.add_row(rec["command"], rec["description"])
        
        self.ui.console.print(table)

    def _display_segmented_text(self, text: str, title: str = None, panel_style: str = None) -> None:
        """
        对长文本进行分段显示，防止界面卡顿
        
        Args:
            text: 要显示的文本
            title: 可选的面板标题
            panel_style: 可选的面板样式
        """
        from rich.panel import Panel
        
        segment_threshold = getattr(self.config.ui, 'segment_threshold', 5000)
        segment_size = getattr(self.config.ui, 'segment_size', 2000)
        
        if len(text) <= segment_threshold:
            if title or panel_style:
                self.ui.console.print(Panel(text, title=title, border_style=panel_style or "cyan"))
            else:
                self.ui.console.print(text)
            return
        
        if not title:
            self.ui.console.print("[bold yellow]内容较长，将分段显示...[/bold yellow]")
        
        paragraphs = text.split("\n\n")
        current_segment = ""
        segment_count = 1
        
        for para in paragraphs:
            if len(current_segment) + len(para) + 2 > segment_size and current_segment:
                segment_title = f"{title} - 第 {segment_count} 段" if title else f"第 {segment_count} 段"
                
                if title or panel_style:
                    self.ui.console.print(Panel(current_segment, title=segment_title, border_style=panel_style or "cyan"))
                else:
                    self.ui.console.print(f"[bold cyan]--- 第 {segment_count} 段 ---[/bold cyan]")
                    self.ui.console.print(current_segment)
                
                if segment_count * segment_size < len(text):
                    if not self.ui.confirm("\n[bold]继续显示下一段?[/bold]"):
                        self.ui.console.print("[bold yellow]已中止显示剩余内容[/bold yellow]")
                        return
                
                current_segment = ""
                segment_count += 1
            
            if current_segment:
                current_segment += "\n\n"
            current_segment += para
        
        if current_segment:
            if segment_count > 1:
                segment_title = f"{title} - 第 {segment_count} 段（最后）" if title else f"第 {segment_count} 段（最后）"
                
                if title or panel_style:
                    self.ui.console.print(Panel(current_segment, title=segment_title, border_style=panel_style or "cyan"))
                else:
                    self.ui.console.print(f"[bold cyan]--- 第 {segment_count} 段 ---[/bold cyan]")
                    self.ui.console.print(current_segment)
            else:
                if title or panel_style:
                    self.ui.console.print(Panel(current_segment, title=title, border_style=panel_style or "cyan"))
                else:
                    self.ui.console.print(current_segment)

    def _load_command_history(self) -> List[Dict[str, Any]]:
        """加载命令历史，用于推荐功能"""
        if os.path.exists(self.command_history_file):
            try:
                with open(self.command_history_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                self.logger.error(f"加载命令历史失败: {e}")
                return []
        return []

    def _save_command_history(self) -> None:
        """保存命令历史"""
        try:
            if len(self.command_history) > 1000:
                self.command_history = self.command_history[-1000:]
                
            with open(self.command_history_file, 'w', encoding='utf-8') as f:
                json.dump(self.command_history, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.error(f"保存命令历史失败: {e}")

    def _add_to_command_history(self, command: str, success: bool, context: str = "") -> None:
        """
        添加命令到历史记录
        
        Args:
            command: 执行的命令
            success: 是否执行成功
            context: 命令执行的上下文
        """
        if not self.enable_recommendations:
            return
            

        if not command or command.strip() in ["help", "exit", "clear", "history"]:
            return
            
        self.command_history.append({
            "command": command,
            "timestamp": time.time(),
            "success": success,
            "context": context[:200] if context else "",  
        })
        
        # 保存历史记录
        self._save_command_history()
        
        # 如果开启分析，则更新分析数据
        if self.collect_analytics:
            self._update_analytics(command, success)

    def _load_analytics_data(self) -> Dict[str, Any]:
        """加载使用分析数据"""
        default_data = {
            "command_categories": {
                "file_operations": {"count": 0, "success_rate": 0},
                "system_info": {"count": 0, "success_rate": 0},
                "process_management": {"count": 0, "success_rate": 0},
                "network": {"count": 0, "success_rate": 0},
                "package_management": {"count": 0, "success_rate": 0},
                "user_management": {"count": 0, "success_rate": 0},
                "text_processing": {"count": 0, "success_rate": 0},
                "other": {"count": 0, "success_rate": 0}
            },
            "command_frequency": {},
            "hourly_usage": {str(i): 0 for i in range(24)},
            "daily_usage": {str(i): 0 for i in range(7)},
            "api_calls": {
                "total": 0,
                "successful": 0,
                "failed": 0
            }
        }
        
        if os.path.exists(self.analytics_file):
            try:
                with open(self.analytics_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                for key, value in default_data.items():
                    if key not in data:
                        data[key] = value
                        
                return data
            except Exception as e:
                self.logger.error(f"加载使用分析数据失败: {e}")
                return default_data
        return default_data

    def _save_analytics_data(self) -> None:
        """保存使用分析数据"""
        if not self.collect_analytics:
            return
            
        try:
            with open(self.analytics_file, 'w', encoding='utf-8') as f:
                json.dump(self.analytics_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.error(f"保存使用分析数据失败: {e}")

    def _update_analytics(self, command: str, success: bool) -> None:
        """
        更新使用分析数据
        
        Args:
            command: 执行的命令
            success: 是否执行成功
        """
        if not self.collect_analytics:
            return
            
        # 更新命令频率
        cmd_parts = command.split()
        if cmd_parts:
            base_cmd = cmd_parts[0]
            
            # 更新命令频率
            if base_cmd in self.analytics_data["command_frequency"]:
                self.analytics_data["command_frequency"][base_cmd] += 1
            else:
                self.analytics_data["command_frequency"][base_cmd] = 1
                
            # 更新命令类别统计
            category = self._get_command_category(base_cmd)
            cat_data = self.analytics_data["command_categories"][category]
            cat_data["count"] += 1
            
            # 更新成功率
            if success:
                # 计算新的成功率
                current_success = cat_data["success_rate"] * (cat_data["count"] - 1)
                cat_data["success_rate"] = (current_success + 1) / cat_data["count"]
            else:
                # 计算新的成功率
                current_success = cat_data["success_rate"] * (cat_data["count"] - 1)
                cat_data["success_rate"] = current_success / cat_data["count"]
                
        current_time = time.localtime()
        hour = str(current_time.tm_hour)
        day = str(current_time.tm_wday) 
        
        self.analytics_data["hourly_usage"][hour] += 1
        self.analytics_data["daily_usage"][day] += 1
        
        self._save_analytics_data()

    def get_command_recommendations(self, user_input: str, count: int = 3) -> List[Dict[str, str]]:
        """
        根据用户输入获取命令推荐
        
        Args:
            user_input: 用户输入
            count: 推荐数量
            
        Returns:
            推荐命令列表，每项包含命令和描述
        """
        if not self.enable_recommendations or not self.command_history:
            return []
            
        recommendations = []
        
        keywords = user_input.lower().split()
        
        stop_words = ["help", "请", "帮忙", "帮我", "如何", "怎么", "执行", "运行", "命令"]
        keywords = [kw for kw in keywords if kw not in stop_words and len(kw) > 1]
        
        if not keywords:
            recent_commands = []
            for cmd_record in reversed(self.command_history):
                if cmd_record.get("success", False):
                    cmd = cmd_record.get("command", "")
                    if cmd and cmd not in [rc["command"] for rc in recent_commands]:
                        recent_commands.append({
                            "command": cmd,
                            "description": "最近使用的命令"
                        })
                        if len(recent_commands) >= count:
                            break
            return recent_commands
        
        # 计算每个历史命令的匹配分数
        scored_commands = []
        for cmd_record in self.command_history:
            cmd = cmd_record.get("command", "")
            success = cmd_record.get("success", False)
            context = cmd_record.get("context", "")
            
            if not cmd:
                continue
                
            # 只推荐成功执行过的命令
            if not success:
                continue
                
            # 计算匹配分数
            score = 0
            cmd_lower = cmd.lower()
            for keyword in keywords:
                if keyword in cmd_lower:
                    score += 5
                if context and keyword in context.lower():
                    score += 3
            
            if score > 0:
                scored_commands.append({
                    "command": cmd,
                    "score": score
                })
        

        scored_commands.sort(key=lambda x: x["score"], reverse=True)
        
        recommendations = []
        seen_commands = set()
        for cmd_info in scored_commands:
            cmd = cmd_info["command"]
            if cmd not in seen_commands:
                recommendations.append({
                    "command": cmd,
                    "description": "基于您的历史使用推荐"
                })
                seen_commands.add(cmd)
                if len(recommendations) >= count:
                    break
        
        return recommendations