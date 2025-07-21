#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
控制台用户界面
提供与用户交互的命令行界面
"""

import os
import sys
import time
import logging
from typing import Optional, List, Dict, Any, Union, Generator
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.styles import Style
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from rich.syntax import Syntax
from rich.theme import Theme
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.live import Live

from src.interfaces.user_interface import UserInterface


class ConsoleUI(UserInterface):
    """控制台用户界面"""
    
    def __init__(self, config):
        """
        初始化控制台UI
        
        Args:
            config: UI配置
        """
        self.config = config
        
        # 加载主题设置
        self.themes = {
            "default": {
                "prompt": "#00aa00 bold",
                "input": "#ffffff",
                "title": "blue bold",
                "heading": "cyan bold",
                "info": "green",
                "warning": "yellow",
                "error": "red bold",
                "highlight": "magenta",
            },
            "dark": {
                "prompt": "#00ff00 bold",
                "input": "#cccccc",
                "title": "#0088ff bold",
                "heading": "#00ccff bold",
                "info": "#00ff88",
                "warning": "#ffcc00",
                "error": "#ff0000 bold",
                "highlight": "#ff00ff",
            },
            "light": {
                "prompt": "#007700 bold",
                "input": "#333333",
                "title": "#0066cc bold",
                "heading": "#0099cc bold",
                "info": "#009955",
                "warning": "#cc9900",
                "error": "#cc0000 bold",
                "highlight": "#cc00cc",
            },
            "retro": {
                "prompt": "#33ff33 bold",
                "input": "#33ff33",
                "title": "#33ff33 bold",
                "heading": "#33ff33 bold",
                "info": "#33ff33",
                "warning": "#ffff33",
                "error": "#ff3333 bold",
                "highlight": "#33ffff",
            },
            "ocean": {
                "prompt": "#00ffff bold",
                "input": "#ffffff",
                "title": "#0088ff bold",
                "heading": "#00ccff bold",
                "info": "#00ff88",
                "warning": "#ffcc00",
                "error": "#ff0000 bold",
                "highlight": "#8800ff",
            }
        }
        
        self.current_theme = getattr(config, 'theme', 'default')
        if self.current_theme not in self.themes:
            self.current_theme = 'default'
        
        theme_style = self.themes[self.current_theme]
        
        # 创建rich控制台主题
        rich_theme = Theme({
            "info": f"{theme_style['info']}",
            "warning": f"{theme_style['warning']}",
            "error": f"{theme_style['error']}",
            "highlight": f"{theme_style['highlight']}",
            "title": f"{theme_style['title']}",
            "heading": f"{theme_style['heading']}",
        })
        
        self.console = Console(theme=rich_theme)
        
        # 设置提示风格
        self.style = Style.from_dict({
            'prompt': theme_style['prompt'],
            'input': theme_style['input'],
        })
        
        history_file = os.path.expanduser(config.history_file)
        history_dir = os.path.dirname(history_file)
        if history_dir and not os.path.exists(history_dir):
            os.makedirs(history_dir)
            
        self.session = PromptSession(
            history=FileHistory(history_file),
            auto_suggest=AutoSuggestFromHistory(),
            style=self.style,
            complete_in_thread=True
        )
        
        # 常用命令提示
        self.common_commands = [
            'help', 'exit', 'clear', 'history', 'config', 'settings',
            'ls', 'ps', 'df', 'top', 'systemctl', 'journalctl',
            'find', 'grep', 'awk', 'sed', 'cat', 'tail', 'netstat',
            'chat history', 'clear chat', 'save chat',
            'chat mode', 'agent mode', 'auto mode', 'mode',
            'tutorial', 'export chat', 'theme'  
        ]
        

        self.refresh_rate = 15  # 默认刷新率
        self.initial_panel_height = 12  # 默认初始面板高度
        
        self.tutorial_state_file = os.path.expanduser("~/.linuxagent_tutorial_completed")
        self.tutorial_completed = self._load_tutorial_completed()
        
        self.languages = {
            "zh": "中文",
            "en": "English"
        }
        
        self.current_language = getattr(config, 'language', 'zh')
        if self.current_language not in self.languages:
            self.current_language = 'zh'
        
    def welcome(self):
        """显示欢迎信息"""
        logo = r"""
  _     _                      _                    _   
 | |   (_)_ __  _   ___  __   / \   __ _  ___ _ __ | |_ 
 | |   | | '_ \| | | \ \/ /  / _ \ / _` |/ _ \ '_ \| __|
 | |___| | | | | |_| |>  <  / ___ \ (_| |  __/ | | | |_ 
 |_____|_|_| |_|\__,_/_/\_\/_/   \_\__, |\___|_| |_|\__|
                                    |___/                
        """
        
        version_info = """
┌─────────────────────────────────────────────────────┐
│ [bold green]LinuxAgent[/bold green] - 基于大语言模型的智能Linux运维助手      │
│                                                     │
│ [bold]Version:[/bold] [yellow]3.0.1[/yellow]                                      │
│ [bold]Author:[/bold]  [cyan]树苗[/cyan]                                       │
│ [bold]Contact:[/bold] [blue]QQ: 3068504755[/blue]                             │
│ [bold]QQ Group:[/bold] [magenta]281392454[/magenta]                                 │
└─────────────────────────────────────────────────────┘
        """
        
        open_source_info = """
┌─────────────────────────────────────────────────────┐
│ [bold]开源地址:[/bold]                                           │
│ [blue]https://github.com/eilen6316/LinuxAgent[/blue]             │
│ [green]https://gitcode.com/qq_69174109/LinuxAgent[/green]          │
│ [yellow]https://gitee.com/xinsai6316/LinuxAgent[/yellow]             │
└─────────────────────────────────────────────────────┘
        """
        
        self.console.print(f"[bold blue]{logo}[/bold blue]")
        self.console.print(version_info)
        self.console.print(open_source_info)
        
        self.console.print("\n[bold]输入命令获取帮助:[/bold] [cyan]help[/cyan]")
        self.console.print("[bold]要退出程序，请输入:[/bold] [cyan]exit[/cyan]")
        self.console.print("\n[bold yellow]请描述您需要的Linux运维任务，LinuxAgent将协助您完成。[/bold yellow]")
        self.console.print("[bold green]支持多轮对话，可以连续提问![/bold green]")
        self.console.print("[bold cyan]可使用[/bold cyan] [bold yellow]chat mode[/bold yellow][bold cyan]/[/bold cyan][bold yellow]agent mode[/bold yellow] [bold cyan]手动切换模式[/bold cyan]\n")
        
    def get_input(self, prompt_text="[LinuxAgent] > ") -> str:
        """
        获取用户输入
        
        Args:
            prompt_text: 提示文本
        
        Returns:
            用户输入
        """
        if prompt_text == "[LinuxAgent] > " and hasattr(self, 'agent') and hasattr(self.agent, 'working_mode'):
            mode = self.agent.working_mode
            mode_indicators = {
                "auto": "",  
                "chat": "[ChatAI] ",
                "agent": "[AgentAI] "
            }
            prompt_text = f"[LinuxAgent]{mode_indicators.get(mode, '')}> "
            
        command_completer = WordCompleter(self.common_commands, ignore_case=True)
        
        user_input = self.session.prompt(
            f"\n{prompt_text} ",
            completer=command_completer
        )
        return user_input.strip()
    
    def show_thinking(self):
        """显示思考中的动画"""
        with self.console.status("[bold green]思考中...[/bold green]", spinner="dots"):
            time.sleep(0.1)  
            
    def show_result(self, result: Union[str, Dict[str, Any]], command: Optional[str] = None):
        """
        显示结果
        
        Args:
            result: 结果文本或字典
            command: 执行的命令(如果有)
        """
        if command:
            self.console.print("[bold]执行命令:[/bold]", style="yellow")
            self.console.print(Syntax(command, "bash", theme="monokai"))
            
        if isinstance(result, str):
            self.console.print("[bold]执行结果:[/bold]", style="green")
            try:
                self.console.print(Markdown(result))
            except:
                self.console.print(result)
        elif isinstance(result, dict):
            explanation = result.get("explanation", "")
            recommendations = result.get("recommendations", [])
            next_steps = result.get("next_steps", [])
            
            content = []
            
            if explanation:
                content.append(f"[bold]分析:[/bold] {explanation}")
                
            if recommendations:
                content.append("\n[bold]建议:[/bold]")
                for i, rec in enumerate(recommendations, 1):
                    content.append(f"  {i}. {rec}")
                    
            if next_steps:
                content.append("\n[bold]下一步操作:[/bold]")
                for i, step in enumerate(next_steps, 1):
                    step_cmd = step.get("command", "")
                    step_explanation = step.get("explanation", "")
                    
                    if step_cmd:
                        content.append(f"  {i}. [yellow]{step_cmd}[/yellow]")
                        if step_explanation:
                            content.append(f"     {step_explanation}")
                    elif step_explanation:
                        content.append(f"  {i}. {step_explanation}")
                        
            self.console.print(Panel(
                "\n".join(content),
                title="执行结果分析",
                border_style="green"
            ))
    
    def show_error(self, message: str):
        """
        显示错误信息
        
        Args:
            message: 错误信息
        """
        self.console.print(f"[bold red]错误:[/bold red] {message}")
    
    def confirm(self, message: str) -> bool:
        """
        获取用户确认
        
        Args:
            message: 确认消息
        
        Returns:
            是否确认
        """
        response = self.session.prompt(
            f"{message} [y/N] "
        ).strip().lower()
        return response in ['y', 'yes']
    
    def show_help(self):
        """显示帮助信息"""
        help_text = """
# LinuxAgent 使用帮助

## 基本用法
直接输入自然语言描述您想要执行的操作，例如：
- '查看系统内存使用情况'
- '找出占用CPU最高的5个进程'
- '检查/var/log目录下最近修改的日志文件'

## 交互模式
LinuxAgent支持两种主要交互模式，可以手动切换：

### AgentAI模式（命令执行）
输入包含执行意图的描述，LinuxAgent会解析并执行相应的命令。
使用类似'执行'、'运行'、'查看'、'检查'、'显示'等词语表明执行意图。
例如：
- `帮我检查系统负载`
- `执行内存使用情况统计`
- `查看当前运行的进程`

### ChatAI模式（问答交流）
以问号结尾或包含'什么是'、'如何'等词的输入会进入问答模式，使用流式输出回答您的问题。
例如：
- `什么是inode？`
- `如何优化Linux系统性能？`
- `请解释crontab的用法`

## 手动切换模式
您可以使用以下命令手动切换工作模式：
- `chat mode`：切换到ChatAI模式，所有输入都会以问答方式处理
- `agent mode`：切换到AgentAI模式，所有输入都会尝试解析为命令执行
- `auto mode`：切换到自动模式，系统将自动判断输入类型
- `mode`：显示当前的工作模式

## 新增功能
- `tutorial`：开始交互式教程，学习如何使用LinuxAgent
- `export chat`：将当前会话导出为文档或脚本
- `theme`：自定义界面主题和颜色
"""
        
        self.console.print(Panel(
            Markdown(help_text),
            title="帮助信息",
            border_style="blue"
        ))
    
    def clear_screen(self):
        """清屏"""
        self.console.clear()
        
    def show_history(self, entries: List[str]):
        """
        显示历史记录
        
        Args:
            entries: 历史记录条目
        """
        self.console.print("[bold]历史记录:[/bold]", style="blue")
        for i, entry in enumerate(entries, 1):
            self.console.print(f"{i:3d}. {entry}")
    
    def show_config(self, config: Dict[str, Any]):
        """
        显示配置信息
        
        Args:
            config: 配置字典
        """
        self.console.print("[bold]当前配置:[/bold]", style="blue")
        # 隐藏API密钥
        if 'api' in config and 'api_key' in config['api']:
            api_key = config['api']['api_key']
            if api_key:
                config['api']['api_key'] = api_key[:4] + '*' * (len(api_key) - 8) + api_key[-4:]
            
        import yaml
        config_yaml = yaml.dump(config, default_flow_style=False)
        self.console.print(Syntax(config_yaml, "yaml", theme="monokai"))
    
    def print_command_execution_info(self, command, start_time, end_time=None, status="进行中"):
        """
        打印命令执行相关信息
        
        Args:
            command: 执行的命令
            start_time: 开始时间
            end_time: 结束时间，如果为None表示命令仍在执行
            status: 命令状态
        """
        if end_time:
            duration = end_time - start_time
            duration_str = f"{duration:.2f}秒"
            if duration > 60:
                minutes = int(duration // 60)
                seconds = int(duration % 60)
                duration_str = f"{minutes}分{seconds}秒"
        else:
            duration_str = f"{time.time() - start_time:.2f}秒"
            
        status_color = {
            "进行中": "yellow",
            "成功": "green",
            "失败": "red",
            "超时": "red",
            "取消": "yellow"
        }.get(status, "white")
        
        self.console.print(f"[bold]命令:[/bold] [yellow]{command}[/yellow]")
        self.console.print(f"[bold]状态:[/bold] [{status_color}]{status}[/{status_color}]")
        self.console.print(f"[bold]耗时:[/bold] {duration_str}")
        
    def stream_output(self, generator: Generator[str, None, None]):
        """
        流式显示输出
        
        Args:
            generator: 输出生成器
        """
        import threading
        
        self.console.print("\n[bold cyan]AI回答中...[/bold cyan]")
        
        if hasattr(self, 'agent') and hasattr(self.agent, 'config') and hasattr(self.agent.config, 'ui'):
            buffer_size = getattr(self.agent.config.ui, 'buffer_size', 100)
        
        with Live("", console=self.console, refresh_per_second=self.refresh_rate, transient=False) as live:
            accumulated_text = ""
            current_height = self.initial_panel_height  
            last_update_time = time.time()
            chunk_timeout = 5.0  
            last_chunk_time = time.time()
            empty_chunks_count = 0
            update_counter = 0
            
            try:
                for chunk in generator:
                    current_time = time.time()
                    update_counter += 1
                    
                    if not chunk:
                        empty_chunks_count += 1
                        if empty_chunks_count > 3 and current_time - last_chunk_time > 1.0:
                            live.update("正在思考..." + "." * (empty_chunks_count % 5))
                            last_chunk_time = current_time
                        continue
                    
                    empty_chunks_count = 0
                    last_chunk_time = current_time
                    accumulated_text += chunk
                    text_lines = accumulated_text.split('\n')
                    
                    lines_count = len(text_lines) + 5  
                    target_height = min(40, max(10, lines_count))
                    
                    if target_height > current_height:
                        current_height = min(target_height, current_height + 2)
                    elif target_height < current_height:
                        current_height = max(target_height, current_height - 1)
                    
                    force_update = (update_counter % 10 == 0) or (current_time - last_update_time > 0.5)
                    
                    if force_update:
                        try:

                            panel = Panel(
                                Markdown(accumulated_text), 
                                title="[bold blue]回答中...[/bold blue]",
                                border_style="blue",
                                padding=(1, 2),
                                height=current_height
                            )
                            live.update(panel)
                            last_update_time = current_time
                        except Exception as e:
                            logging.warning(f"面板更新错误: {e}")
                            try:
                                live.update(accumulated_text[-2000:])
                                last_update_time = current_time
                            except:
                                pass
                    
                    if update_counter % 50 == 0:
                        time.sleep(0.01)
                    
                    if current_time - last_chunk_time > chunk_timeout:
                        logging.warning(f"流式输出超时: {chunk_timeout}秒内未收到新块")
                        try:
                            live.update(Panel(
                                Markdown(accumulated_text), 
                                title="[bold yellow]回答可能未完成[/bold yellow]",
                                border_style="yellow",
                                padding=(1, 2)
                            ))
                        except:
                            live.update(accumulated_text)
                        break
                
                try:
                    final_panel = Panel(
                        Markdown(accumulated_text), 
                        title="[bold green]✓ 完成[/bold green]",
                        border_style="green",
                        padding=(1, 2)
                    )
                    live.update(final_panel)
                except Exception as e:
                    logging.warning(f"最终面板更新错误: {e}")
                    try:
                        live.update(accumulated_text)
                    except:
                        pass
                    
            except Exception as e:
                logging.error(f"流式输出错误: {e}", exc_info=True)

                try:
                    live.update(f"输出错误: {e}\n\n已收到的内容:\n{accumulated_text}")
                except:
                    pass
        
        self.console.print("[dim]回答已完成[/dim]")

    def set_agent(self, agent):
        """
        设置Agent引用，用于获取模式信息
        
        Args:
            agent: Agent对象引用
        """
        self.agent = agent
        
        if not hasattr(self, 'tutorial_completed') or not self.tutorial_completed:
            import time
            time.sleep(1)  
            if self.confirm("\n这看起来是您第一次使用 LinuxAgent，是否要开始交互式教程？"):
                self.start_tutorial()

    def start_tutorial(self):
        """开始交互式教程"""
        steps = [
            {
                "title": "欢迎使用 LinuxAgent 教程",
                "content": "本教程将带您了解 LinuxAgent 的基本功能和使用方法。在每个步骤后，按回车键继续。",
                "demo": None
            },
            {
                "title": "基本用法：自然语言命令",
                "content": "LinuxAgent 允许您使用自然语言描述您想要执行的操作。例如，您可以输入'查看系统内存使用情况'，系统会自动执行适当的命令。",
                "demo": "查看系统内存使用情况"
            },
            {
                "title": "模式切换：ChatAI 模式",
                "content": "使用 'chat mode' 命令切换到问答模式。在该模式下，所有输入都会被当作问题处理，系统会提供详细解答。",
                "demo": "chat mode"
            },
            {
                "title": "提问示例",
                "content": "在 ChatAI 模式下，尝试提问。例如：'什么是Linux内核？'",
                "demo": "什么是Linux内核？"
            },
            {
                "title": "模式切换：AgentAI 模式",
                "content": "使用 'agent mode' 命令切换到命令执行模式。在该模式下，系统会尝试将所有输入解析为可执行命令。",
                "demo": "agent mode"
            },
            {
                "title": "命令执行示例",
                "content": "在 AgentAI 模式下，尝试请求执行命令。例如：'显示当前目录下的文件'",
                "demo": "显示当前目录下的文件"
            },
            {
                "title": "模式切换：自动模式",
                "content": "使用 'auto mode' 命令切换回自动模式。在该模式下，系统会根据您的输入自动判断是问答还是命令执行。",
                "demo": "auto mode"
            },
            {
                "title": "会话历史与导出",
                "content": "使用 'chat history' 查看对话历史，使用 'export chat' 将对话导出为文档或脚本。",
                "demo": "chat history"
            },
            {
                "title": "自定义主题",
                "content": "使用 'theme' 命令自定义界面颜色和风格。",
                "demo": "theme"
            },
            {
                "title": "教程完成",
                "content": "恭喜您完成了 LinuxAgent 的基本教程！现在您可以开始使用这个强大的工具来协助您的 Linux 运维工作。\n\n如需帮助，随时输入 'help' 查看帮助信息。",
                "demo": None
            }
        ]
        
        self.console.print("[bold green]开始交互式教程[/bold green]")
        self.console.print("[bold yellow]您可以随时按 Ctrl+C 退出教程[/bold yellow]\n")
        
        try:
            for i, step in enumerate(steps, 1):
                panel_content = f"[bold]{step['content']}[/bold]"
                if step["demo"]:
                    panel_content += f"\n\n示例: [yellow]{step['demo']}[/yellow]"
                    
                self.console.print(Panel(
                    panel_content,
                    title=f"[{i}/{len(steps)}] {step['title']}",
                    border_style="green"
                ))
                
                if i < len(steps):
                    self.console.print("[dim]按回车键继续...[/dim]")
                    input()
                    
            self.tutorial_completed = True
            self._save_tutorial_completed()
            self.console.print("[bold green]教程已完成！现在您可以开始使用 LinuxAgent 了。[/bold green]")
        except KeyboardInterrupt:
            self.console.print("\n[bold yellow]教程已中断。您可以随时输入 'tutorial' 重新开始教程。[/bold yellow]")

    def show_theme_settings(self):
        """显示并修改主题设置"""
        from rich.table import Table
        
        table = Table(title="主题设置")
        table.add_column("编号", style="cyan", justify="center")
        table.add_column("主题名称", style="green")
        table.add_column("描述", style="white")
        
        themes_info = {
            "default": "默认主题 - 经典绿色终端风格",
            "dark": "暗色主题 - 适合夜间使用",
            "light": "亮色主题 - 柔和的色彩",
            "retro": "复古主题 - 老式计算机风格",
            "ocean": "海洋主题 - 蓝色调优雅风格"
        }
        
        for i, (theme_name, description) in enumerate(themes_info.items(), 1):
            marker = "✓ " if theme_name == self.current_theme else ""
            table.add_row(str(i), f"{marker}{theme_name}", description)
        
        self.console.print(table)
        self.console.print("\n[bold]请选择要应用的主题编号，或按q返回:[/bold]")
        
        choice = self.get_input("主题 > ")
        
        if choice.lower() in ['q', 'quit', 'exit', 'back']:
            return
        
        try:
            theme_num = int(choice)
            themes = list(themes_info.keys())
            if 1 <= theme_num <= len(themes):
                selected_theme = themes[theme_num - 1]
                self._apply_theme(selected_theme)
            else:
                self.console.print("[bold red]无效的主题编号[/bold red]")
        except ValueError:
            self.console.print("[bold red]请输入数字或q退出[/bold red]")

    def _apply_theme(self, theme_name):
        """应用选择的主题"""
        if theme_name not in self.themes:
            self.console.print(f"[bold red]未知的主题: {theme_name}[/bold red]")
            return
        
        self.current_theme = theme_name
        theme_style = self.themes[theme_name]
        
        rich_theme = Theme({
            "info": f"{theme_style['info']}",
            "warning": f"{theme_style['warning']}",
            "error": f"{theme_style['error']}",
            "highlight": f"{theme_style['highlight']}",
            "title": f"{theme_style['title']}",
            "heading": f"{theme_style['heading']}",
        })
        
        self.console = Console(theme=rich_theme)
        
        self.style = Style.from_dict({
            'prompt': theme_style['prompt'],
            'input': theme_style['input'],
        })
        
        self.session.style = self.style
        
        self.console.print(f"[bold green]已应用主题:[/bold green] [highlight]{theme_name}[/highlight]")
        
        if hasattr(self, 'agent') and hasattr(self.agent, 'config'):
            setattr(self.agent.config.ui, 'theme', theme_name)
            self.console.print("[dim]主题设置已更新，重启后自动生效[/dim]")
            
            if self.confirm("是否将主题设置保存到配置文件?"):
                self.agent._save_config_to_file()

    def _load_tutorial_completed(self) -> bool:
        """加载教程完成状态"""
        if os.path.exists(self.tutorial_state_file):
            try:
                with open(self.tutorial_state_file, 'r') as f:
                    return f.read().strip() == "completed"
            except:
                return False
        return False

    def _save_tutorial_completed(self) -> None:
        """保存教程完成状态"""
        try:
            with open(self.tutorial_state_file, 'w') as f:
                f.write("completed")
        except:
            pass  