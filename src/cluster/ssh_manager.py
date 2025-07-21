#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
SSH集群管理模块
负责管理多服务器SSH连接和批量命令执行
"""

import asyncio
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Tuple, Any, Union
from pathlib import Path

try:
    import paramiko
except ImportError:
    paramiko = None


@dataclass
class ServerInfo:
    """服务器信息"""
    hostname: str
    username: str
    port: int = 22
    password: Optional[str] = None
    private_key_path: Optional[str] = None
    private_key_passphrase: Optional[str] = None
    group: str = "default"
    description: str = ""
    enabled: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        data = asdict(self)
        # 不包含敏感信息
        data.pop('password', None)
        data.pop('private_key_passphrase', None)
        return data


@dataclass
class CommandResult:
    """命令执行结果"""
    hostname: str
    command: str
    stdout: str
    stderr: str
    return_code: int
    execution_time: float
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return asdict(self)


@dataclass
class ServerStatus:
    """服务器状态"""
    hostname: str
    online: bool
    last_check: float
    response_time: float
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return asdict(self)


class SSHConnection:
    """SSH连接管理"""
    
    def __init__(self, server_info: ServerInfo):
        self.server_info = server_info
        self.client: Optional[paramiko.SSHClient] = None
        self.connected = False
        self.last_used = time.time()
        self.logger = logging.getLogger(f"{__name__}.{server_info.hostname}")
    
    def connect(self) -> bool:
        """建立SSH连接"""
        if paramiko is None:
            raise ImportError("paramiko库未安装，请运行: pip install paramiko")
        
        try:
            self.client = paramiko.SSHClient()
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            # 准备连接参数
            connect_kwargs = {
                'hostname': self.server_info.hostname,
                'port': self.server_info.port,
                'username': self.server_info.username,
                'timeout': 10
            }
            
            # 认证方式
            if self.server_info.private_key_path:
                # 使用私钥认证
                key_path = Path(self.server_info.private_key_path).expanduser()
                if key_path.exists():
                    try:
                        if self.server_info.private_key_passphrase:
                            private_key = paramiko.RSAKey.from_private_key_file(
                                str(key_path),
                                password=self.server_info.private_key_passphrase
                            )
                        else:
                            private_key = paramiko.RSAKey.from_private_key_file(str(key_path))
                        connect_kwargs['pkey'] = private_key
                    except paramiko.PasswordRequiredException:
                        self.logger.error(f"私钥需要密码: {key_path}")
                        return False
                    except Exception as e:
                        self.logger.error(f"加载私钥失败: {e}")
                        return False
                else:
                    self.logger.error(f"私钥文件不存在: {key_path}")
                    return False
            elif self.server_info.password:
                # 使用密码认证
                connect_kwargs['password'] = self.server_info.password
            else:
                self.logger.error("未提供认证信息")
                return False
            
            # 建立连接
            self.client.connect(**connect_kwargs)
            self.connected = True
            self.last_used = time.time()
            self.logger.info(f"SSH连接建立成功: {self.server_info.hostname}")
            return True
            
        except Exception as e:
            self.logger.error(f"SSH连接失败: {e}")
            self.connected = False
            if self.client:
                self.client.close()
                self.client = None
            return False
    
    def disconnect(self):
        """断开SSH连接"""
        if self.client:
            self.client.close()
            self.client = None
        self.connected = False
        self.logger.info(f"SSH连接已断开: {self.server_info.hostname}")
    
    def execute_command(self, command: str, timeout: int = 30) -> CommandResult:
        """执行命令"""
        start_time = time.time()
        
        if not self.connected or not self.client:
            return CommandResult(
                hostname=self.server_info.hostname,
                command=command,
                stdout="",
                stderr="",
                return_code=-1,
                execution_time=0,
                error="SSH连接未建立"
            )
        
        try:
            stdin, stdout, stderr = self.client.exec_command(command, timeout=timeout)
            
            # 读取输出
            stdout_data = stdout.read().decode('utf-8', errors='replace')
            stderr_data = stderr.read().decode('utf-8', errors='replace')
            return_code = stdout.channel.recv_exit_status()
            
            execution_time = time.time() - start_time
            self.last_used = time.time()
            
            return CommandResult(
                hostname=self.server_info.hostname,
                command=command,
                stdout=stdout_data,
                stderr=stderr_data,
                return_code=return_code,
                execution_time=execution_time
            )
            
        except Exception as e:
            execution_time = time.time() - start_time
            self.logger.error(f"命令执行失败: {e}")
            
            return CommandResult(
                hostname=self.server_info.hostname,
                command=command,
                stdout="",
                stderr="",
                return_code=-1,
                execution_time=execution_time,
                error=str(e)
            )
    
    def is_alive(self) -> bool:
        """检查连接是否存活"""
        if not self.connected or not self.client:
            return False
        
        try:
            transport = self.client.get_transport()
            return transport and transport.is_active()
        except:
            return False


class SSHManager:
    """SSH集群管理器"""
    
    def __init__(self, max_connections: int = 10, connection_timeout: int = 300):
        """
        初始化SSH管理器
        
        Args:
            max_connections: 最大并发连接数
            connection_timeout: 连接超时时间（秒）
        """
        self.max_connections = max_connections
        self.connection_timeout = connection_timeout
        self.servers: Dict[str, ServerInfo] = {}
        self.connections: Dict[str, SSHConnection] = {}
        self.groups: Dict[str, List[str]] = {}
        self.executor = ThreadPoolExecutor(max_workers=max_connections)
        self.logger = logging.getLogger(__name__)
        self._lock = threading.Lock()
        
        # 启动连接清理线程
        self._cleanup_thread = threading.Thread(target=self._cleanup_connections, daemon=True)
        self._cleanup_thread.start()
    
    def add_server(self, server_info: ServerInfo):
        """添加服务器"""
        with self._lock:
            self.servers[server_info.hostname] = server_info
            
            # 更新分组
            if server_info.group not in self.groups:
                self.groups[server_info.group] = []
            
            if server_info.hostname not in self.groups[server_info.group]:
                self.groups[server_info.group].append(server_info.hostname)
        
        self.logger.info(f"添加服务器: {server_info.hostname} (组: {server_info.group})")
    
    def remove_server(self, hostname: str):
        """移除服务器"""
        with self._lock:
            if hostname in self.servers:
                server_info = self.servers[hostname]
                
                # 断开连接
                if hostname in self.connections:
                    self.connections[hostname].disconnect()
                    del self.connections[hostname]
                
                # 从分组中移除
                if server_info.group in self.groups:
                    if hostname in self.groups[server_info.group]:
                        self.groups[server_info.group].remove(hostname)
                    
                    # 如果分组为空，删除分组
                    if not self.groups[server_info.group]:
                        del self.groups[server_info.group]
                
                del self.servers[hostname]
                self.logger.info(f"移除服务器: {hostname}")
    
    def get_server(self, hostname: str) -> Optional[ServerInfo]:
        """获取服务器信息"""
        return self.servers.get(hostname)
    
    def list_servers(self, group: str = None) -> List[ServerInfo]:
        """列出服务器"""
        if group is None:
            return list(self.servers.values())
        else:
            hostnames = self.groups.get(group, [])
            return [self.servers[hostname] for hostname in hostnames if hostname in self.servers]
    
    def list_groups(self) -> List[str]:
        """列出所有分组"""
        return list(self.groups.keys())
    
    def get_group_servers(self, group: str) -> List[str]:
        """获取分组中的服务器"""
        return self.groups.get(group, [])
    
    def _get_connection(self, hostname: str) -> Optional[SSHConnection]:
        """获取SSH连接"""
        if hostname not in self.servers:
            return None
        
        with self._lock:
            # 检查是否存在连接
            if hostname in self.connections:
                conn = self.connections[hostname]
                if conn.is_alive():
                    return conn
                else:
                    # 连接已断开，移除
                    conn.disconnect()
                    del self.connections[hostname]
            
            # 创建新连接
            server_info = self.servers[hostname]
            if not server_info.enabled:
                return None
            
            conn = SSHConnection(server_info)
            if conn.connect():
                self.connections[hostname] = conn
                return conn
            else:
                return None
    
    def _cleanup_connections(self):
        """清理过期连接"""
        while True:
            try:
                current_time = time.time()
                
                with self._lock:
                    expired_connections = []
                    
                    for hostname, conn in self.connections.items():
                        if (current_time - conn.last_used > self.connection_timeout or
                            not conn.is_alive()):
                            expired_connections.append(hostname)
                    
                    for hostname in expired_connections:
                        self.connections[hostname].disconnect()
                        del self.connections[hostname]
                        self.logger.info(f"清理过期连接: {hostname}")
                
                time.sleep(60)  # 每分钟清理一次
                
            except Exception as e:
                self.logger.error(f"连接清理出错: {e}")
                time.sleep(60)
    
    def execute_command(self, hostname: str, command: str, timeout: int = 30) -> CommandResult:
        """在单个服务器上执行命令"""
        conn = self._get_connection(hostname)
        if not conn:
            return CommandResult(
                hostname=hostname,
                command=command,
                stdout="",
                stderr="",
                return_code=-1,
                execution_time=0,
                error="无法建立SSH连接"
            )
        
        return conn.execute_command(command, timeout)
    
    def execute_command_parallel(self, hostnames: List[str], command: str, 
                                timeout: int = 30) -> Dict[str, CommandResult]:
        """在多个服务器上并行执行命令"""
        results = {}
        
        # 创建执行任务
        futures = {}
        for hostname in hostnames:
            if hostname in self.servers and self.servers[hostname].enabled:
                future = self.executor.submit(self.execute_command, hostname, command, timeout)
                futures[future] = hostname
        
        # 收集结果
        for future in as_completed(futures):
            hostname = futures[future]
            try:
                result = future.result()
                results[hostname] = result
            except Exception as e:
                results[hostname] = CommandResult(
                    hostname=hostname,
                    command=command,
                    stdout="",
                    stderr="",
                    return_code=-1,
                    execution_time=0,
                    error=str(e)
                )
        
        return results
    
    def execute_command_on_group(self, group: str, command: str, 
                               timeout: int = 30) -> Dict[str, CommandResult]:
        """在分组上执行命令"""
        hostnames = self.get_group_servers(group)
        return self.execute_command_parallel(hostnames, command, timeout)
    
    def check_server_status(self, hostname: str) -> ServerStatus:
        """检查服务器状态"""
        start_time = time.time()
        
        try:
            result = self.execute_command(hostname, "echo 'ping'", timeout=5)
            response_time = time.time() - start_time
            
            if result.return_code == 0:
                return ServerStatus(
                    hostname=hostname,
                    online=True,
                    last_check=time.time(),
                    response_time=response_time
                )
            else:
                return ServerStatus(
                    hostname=hostname,
                    online=False,
                    last_check=time.time(),
                    response_time=response_time,
                    error=result.error or result.stderr
                )
        except Exception as e:
            response_time = time.time() - start_time
            return ServerStatus(
                hostname=hostname,
                online=False,
                last_check=time.time(),
                response_time=response_time,
                error=str(e)
            )
    
    def check_all_servers_status(self) -> Dict[str, ServerStatus]:
        """检查所有服务器状态"""
        results = {}
        
        futures = {}
        for hostname in self.servers:
            future = self.executor.submit(self.check_server_status, hostname)
            futures[future] = hostname
        
        for future in as_completed(futures):
            hostname = futures[future]
            try:
                result = future.result()
                results[hostname] = result
            except Exception as e:
                results[hostname] = ServerStatus(
                    hostname=hostname,
                    online=False,
                    last_check=time.time(),
                    response_time=0,
                    error=str(e)
                )
        
        return results
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            total_servers = len(self.servers)
            enabled_servers = sum(1 for server in self.servers.values() if server.enabled)
            active_connections = len(self.connections)
            total_groups = len(self.groups)
        
        return {
            'total_servers': total_servers,
            'enabled_servers': enabled_servers,
            'active_connections': active_connections,
            'total_groups': total_groups,
            'groups': {group: len(hostnames) for group, hostnames in self.groups.items()}
        }
    
    def close_all_connections(self):
        """关闭所有连接"""
        with self._lock:
            for conn in self.connections.values():
                conn.disconnect()
            self.connections.clear()
        
        self.executor.shutdown(wait=False)
        self.logger.info("所有SSH连接已关闭")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ssh_manager = SSHManager()
    
    # 添加测试服务器（自己修改不固定）
    test_server = ServerInfo(
        hostname="localhost",
        username="test_user",
        password="test_password",
        group="test_group",
        description="测试服务器"
    )
    
    ssh_manager.add_server(test_server)
    
    # 测试命令执行
    print("测试服务器状态...")
    status = ssh_manager.check_server_status("localhost")
    print(f"服务器状态: {status.online}")
    
    if status.online:
        print("执行测试命令...")
        result = ssh_manager.execute_command("localhost", "uname -a")
        print(f"命令结果: {result.stdout}")
    
    # 显示统计信息
    stats = ssh_manager.get_statistics()
    print(f"统计信息: {stats}")
    
    # 清理资源
    ssh_manager.close_all_connections()
