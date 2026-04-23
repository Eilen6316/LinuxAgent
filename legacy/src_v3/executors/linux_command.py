#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Linux命令执行器
负责安全地执行系统命令并获取结果
"""

import os
import re
import subprocess
import shlex
import logging
from typing import Dict, Tuple, List, Optional, Any

from src.interfaces.command_executor import CommandExecutorInterface


class LinuxCommandExecutor(CommandExecutorInterface):
    """Linux命令执行器"""
    
    def __init__(self, security_config, logger=None):
        """初始化命令执行器"""
        self.confirm_dangerous_commands = security_config.confirm_dangerous_commands
        self.blocked_commands = security_config.blocked_commands
        self.confirm_patterns = security_config.confirm_patterns
        
        self.logger = logger or logging.getLogger("command_executor")
        
        self.interactive_commands = [
            'vim', 'vi', 'nano', 'emacs', 'less', 'more', 'top', 'htop',
            'mysql', 'psql', 'sqlite3', 'python', 'ipython', 'bash', 'sh',
            'zsh', 'ssh', 'telnet', 'ftp', 'sftp'
        ]
    
    def is_command_safe(self, command: str) -> Tuple[bool, str]:
        """检查命令是否安全"""
        for blocked in self.blocked_commands:
            if command.strip() == blocked or command.strip().startswith(f"{blocked} "):
                reason = f"命令 '{blocked}' 已被禁止执行"
                self.logger.warning(f"发现禁止命令: {command}")
                return False, reason
        
        for pattern in self.confirm_patterns:
            if pattern in command:
                reason = f"命令包含潜在危险操作 '{pattern}'"
                self.logger.info(f"发现需要确认的命令模式: {pattern} in {command}")
                return False, reason
        
        return True, ""
    
    def get_system_info(self) -> Dict[str, Any]:
        """获取系统信息"""
        info = {}
        
        try:
            if os.path.exists("/etc/os-release"):
                with open("/etc/os-release", "r") as f:
                    for line in f:
                        if "=" in line:
                            key, value = line.strip().split("=", 1)
                            value = value.strip('"')
                            info[key] = value
            
            kernel = subprocess.check_output(["uname", "-r"], text=True).strip()
            info["KERNEL"] = kernel
            
            hostname = subprocess.check_output(["hostname"], text=True).strip()
            info["HOSTNAME"] = hostname
            
            cpu_info = {}
            if os.path.exists("/proc/cpuinfo"):
                with open("/proc/cpuinfo", "r") as f:
                    for line in f:
                        if ":" in line:
                            key, value = line.strip().split(":", 1)
                            key = key.strip()
                            value = value.strip()
                            if key == "model name":
                                cpu_info["MODEL"] = value
                                break
            
            try:
                cpu_cores = subprocess.check_output(
                    "nproc", text=True, stderr=subprocess.PIPE
                ).strip()
                cpu_info["CORES"] = cpu_cores
            except:
                pass
                
            info["CPU"] = cpu_info
            
            mem_info = {}
            if os.path.exists("/proc/meminfo"):
                with open("/proc/meminfo", "r") as f:
                    for line in f:
                        if ":" in line:
                            key, value = line.strip().split(":", 1)
                            key = key.strip()
                            value = value.strip()
                            if key in ["MemTotal", "MemFree", "MemAvailable"]:
                                mem_info[key] = value
            
            info["MEMORY"] = mem_info
            
        except Exception as e:
            self.logger.error(f"获取系统信息失败: {e}")
            
            # 如果是Windows系统或者其他无法获取Linux系统信息的环境
            # 提供基本系统信息
            import platform
            info = {
                "OS": platform.system(),
                "VERSION": platform.version(),
                "MACHINE": platform.machine(),
                "PROCESSOR": platform.processor(),
                "PYTHON_VERSION": platform.python_version()
            }
        
        return info
    
    def _get_command_timeout(self, command: str) -> int:
        """根据命令类型获取适当的超时时间"""
        pkg_managers = ['dnf', 'yum', 'apt', 'apt-get', 'pacman', 'zypper']
        
        for pm in pkg_managers:
            if f"{pm} update" in command or f"{pm} upgrade" in command:
                return 600  # 10分钟
            elif f"{pm} install" in command:
                return 600  # 10分钟
        
        if command.count('&&') > 2 or command.count(';') > 2:
            return 300  # 5分钟
            
        return 120  # 2分钟
    
    def execute_command(self, command: str, timeout: Optional[int] = None) -> Tuple[str, str, int]:
        """执行命令，并返回执行结果"""
        self.logger.info(f"执行命令: {command}")
        
        if self._is_interactive_command(command):
            self.logger.info("检测到交互式命令，使用交互式执行方式")
            return self._execute_interactive_command(command)
        
        if timeout is None:
            timeout = self._get_command_timeout(command)
            
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=True,
                text=True,
                encoding='utf-8',
                errors='replace'
            )
            
            stdout, stderr = process.communicate(timeout=timeout)
            return_code = process.returncode
            
            self.logger.info(f"命令执行完成，返回码: {return_code}")
            if return_code != 0:
                self.logger.warning(f"命令执行返回非零状态: {stderr}")
                
            return stdout, stderr, return_code
            
        except subprocess.TimeoutExpired:
            process.kill()
            self.logger.error(f"命令执行超时 (超过 {timeout}秒)")
            return "", f"命令执行超时 (超过 {timeout}秒)", 1
            
        except Exception as e:
            self.logger.error(f"命令执行失败: {e}", exc_info=True)
            return "", str(e), 1
    
    def _is_interactive_command(self, command: str) -> bool:
        """检查命令是否是交互式命令"""
        first_word = command.split()[0] if command else ""
        if first_word in self.interactive_commands:
            return True
            
        return any(ic in command for ic in self.interactive_commands)
        
    def _execute_interactive_command(self, command: str) -> Tuple[str, str, int]:
        """执行交互式命令"""
        self.logger.info(f"执行交互式命令: {command}")
        
        try:
            editor_cmds = ["vim", "vi", "nano", "emacs"]
            first_cmd = command.split()[0]
            
            if any(editor in first_cmd for editor in editor_cmds):
                editor_name = first_cmd.split('/')[-1]
                print(f"\n{'='*60}")
                print(f"正在启动 {editor_name} 编辑器...")
                
                if editor_name in ["vim", "vi"]:
                    print("Vim 基本使用说明:")
                    print("- 按下 i 键进入插入模式")
                    print("- 编辑完成后，按下 ESC 键退出插入模式")
                    print("- 输入 :wq 保存并退出")
                    print("- 输入 :q! 不保存直接退出")
                elif editor_name == "nano":
                    print("Nano 基本使用说明:")
                    print("- 直接编辑文本")
                    print("- Ctrl+O 保存文件")
                    print("- Ctrl+X 退出编辑器")
                elif editor_name == "emacs":
                    print("Emacs 基本使用说明:")
                    print("- 直接编辑文本")
                    print("- Ctrl+X Ctrl+S 保存文件")
                    print("- Ctrl+X Ctrl+C 退出编辑器")
                
                print(f"{'='*60}\n")
            
            return_code = os.system(command)
            if os.name == 'posix':
                actual_return_code = return_code >> 8
            else:
                actual_return_code = return_code
                
            return "", "", actual_return_code
            
        except Exception as e:
            self.logger.error(f"执行交互式命令失败: {e}", exc_info=True)
            return "", str(e), 1
            
    def execute_file_editor(self, file_path: str, editor: str = "vim") -> Tuple[str, str, int]:
        """使用指定编辑器打开文件"""
        self.logger.info(f"使用 {editor} 打开文件: {file_path}")
        
        try:
            dir_path = os.path.dirname(file_path)
            if dir_path and not os.path.exists(dir_path):
                os.makedirs(dir_path, exist_ok=True)
        except Exception as e:
            self.logger.error(f"创建目录失败: {str(e)}")
            return "", f"创建目录失败: {str(e)}", 1
        
        if not os.path.exists(file_path):
            try:
                with open(file_path, 'w') as f:
                    pass
            except Exception as e:
                if "Permission denied" in str(e):
                    cmd = f"sudo touch {file_path}"
                    os.system(cmd)
                else:
                    self.logger.error(f"创建文件失败: {str(e)}")
                    return "", f"创建文件失败: {str(e)}", 1
        
        if os.path.exists(file_path) and not os.access(file_path, os.W_OK):
            command = f"sudo {editor} {file_path}"
        else:
            command = f"{editor} {file_path}"
            
        return self._execute_interactive_command(command)
    
    def execute_multiple_commands(self, commands: List[str]) -> List[tuple]:
        """依次执行多个命令"""
        results = []
        
        for cmd in commands:
            stdout, stderr, return_code = self.execute_command(cmd)
            results.append((cmd, stdout, stderr, return_code))
            
            if return_code != 0:
                self.logger.warning(f"命令 '{cmd}' 执行失败，停止后续命令执行")
                break
                
        return results 