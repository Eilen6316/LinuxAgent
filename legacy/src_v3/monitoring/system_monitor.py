#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
系统监控模块 - 数据收集器
负责收集系统性能指标和健康状态数据
"""

import psutil
import time
import json
import logging
import threading
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Any, Callable
from pathlib import Path


@dataclass
class SystemMetrics:
    """系统指标数据类"""
    timestamp: float
    cpu_percent: float
    memory_percent: float
    memory_total: int
    memory_available: int
    disk_percent: float
    disk_total: int
    disk_free: int
    network_bytes_sent: int
    network_bytes_recv: int
    load_avg: List[float]
    process_count: int
    boot_time: float
    temperature: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return asdict(self)


class SystemMonitor:
    """系统监控器"""
    
    def __init__(self, collection_interval: int = 60, history_size: int = 1440):
        """
        初始化系统监控器
        
        Args:
            collection_interval: 数据收集间隔（秒）
            history_size: 历史数据最大保存数量
        """
        self.collection_interval = collection_interval
        self.history_size = history_size
        self.running = False
        self.metrics_history: List[SystemMetrics] = []
        self.callbacks: List[Callable[[SystemMetrics], None]] = []
        self.logger = logging.getLogger(__name__)
        self._monitor_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        
    def add_callback(self, callback: Callable[[SystemMetrics], None]):
        """添加监控数据回调函数"""
        self.callbacks.append(callback)
        
    def remove_callback(self, callback: Callable[[SystemMetrics], None]):
        """移除监控数据回调函数"""
        if callback in self.callbacks:
            self.callbacks.remove(callback)
    
    def collect_metrics(self) -> SystemMetrics:
        """收集当前系统指标"""
        try:
            # CPU信息
            cpu_percent = psutil.cpu_percent(interval=1)
            
            # 内存信息
            memory = psutil.virtual_memory()
            
            # 磁盘信息
            disk = psutil.disk_usage('/')
            
            # 网络信息
            net_io = psutil.net_io_counters()
            
            # 负载信息
            load_avg = list(psutil.getloadavg()) if hasattr(psutil, 'getloadavg') else [0.0, 0.0, 0.0]
            
            # 进程数量
            process_count = len(psutil.pids())
            
            # 系统启动时间
            boot_time = psutil.boot_time()
            
            # 温度信息（如果可用）
            temperature = None
            try:
                temps = psutil.sensors_temperatures()
                if temps:
                    # 取第一个温度传感器的当前温度
                    for name, entries in temps.items():
                        if entries:
                            temperature = entries[0].current
                            break
            except AttributeError:
                pass
            
            return SystemMetrics(
                timestamp=time.time(),
                cpu_percent=cpu_percent,
                memory_percent=memory.percent,
                memory_total=memory.total,
                memory_available=memory.available,
                disk_percent=disk.percent,
                disk_total=disk.total,
                disk_free=disk.free,
                network_bytes_sent=net_io.bytes_sent,
                network_bytes_recv=net_io.bytes_recv,
                load_avg=load_avg,
                process_count=process_count,
                boot_time=boot_time,
                temperature=temperature
            )
            
        except Exception as e:
            self.logger.error(f"收集系统指标时出错: {e}")
            # 返回默认值
            return SystemMetrics(
                timestamp=time.time(),
                cpu_percent=0.0,
                memory_percent=0.0,
                memory_total=0,
                memory_available=0,
                disk_percent=0.0,
                disk_total=0,
                disk_free=0,
                network_bytes_sent=0,
                network_bytes_recv=0,
                load_avg=[0.0, 0.0, 0.0],
                process_count=0,
                boot_time=0.0
            )
    
    def get_latest_metrics(self) -> Optional[SystemMetrics]:
        """获取最新的系统指标"""
        with self._lock:
            return self.metrics_history[-1] if self.metrics_history else None
    
    def get_metrics_history(self, count: Optional[int] = None) -> List[SystemMetrics]:
        """获取历史指标数据"""
        with self._lock:
            if count is None:
                return self.metrics_history.copy()
            return self.metrics_history[-count:] if count > 0 else []
    
    def start_monitoring(self):
        """启动监控线程"""
        if self.running:
            self.logger.warning("监控已经在运行中")
            return
            
        self.running = True
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()
        self.logger.info("系统监控已启动")
    
    def stop_monitoring(self):
        """停止监控线程"""
        self.running = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5)
        self.logger.info("系统监控已停止")
    
    def _monitor_loop(self):
        """监控主循环"""
        while self.running:
            try:
                # 收集指标
                metrics = self.collect_metrics()
                
                # 保存到历史记录
                with self._lock:
                    self.metrics_history.append(metrics)
                    
                    # 保持历史记录大小
                    if len(self.metrics_history) > self.history_size:
                        self.metrics_history.pop(0)
                
                # 调用回调函数
                for callback in self.callbacks:
                    try:
                        callback(metrics)
                    except Exception as e:
                        self.logger.error(f"回调函数执行出错: {e}")
                
                # 等待下一次收集
                time.sleep(self.collection_interval)
                
            except Exception as e:
                self.logger.error(f"监控循环出错: {e}")
                time.sleep(self.collection_interval)
    
    def save_history_to_file(self, file_path: str):
        """保存历史数据到文件"""
        try:
            with self._lock:
                data = [metrics.to_dict() for metrics in self.metrics_history]
            
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            self.logger.info(f"历史数据已保存到 {file_path}")
            
        except Exception as e:
            self.logger.error(f"保存历史数据失败: {e}")
    
    def load_history_from_file(self, file_path: str):
        """从文件加载历史数据"""
        try:
            if not Path(file_path).exists():
                self.logger.warning(f"历史数据文件不存在: {file_path}")
                return
            
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            with self._lock:
                self.metrics_history = [
                    SystemMetrics(**item) for item in data
                ]
            
            self.logger.info(f"从 {file_path} 加载了 {len(self.metrics_history)} 条历史数据")
            
        except Exception as e:
            self.logger.error(f"加载历史数据失败: {e}")
    
    def get_system_info(self) -> Dict[str, Any]:
        """获取系统基本信息"""
        try:
            return {
                'platform': psutil.LINUX,
                'cpu_count': psutil.cpu_count(),
                'cpu_count_logical': psutil.cpu_count(logical=True),
                'memory_total': psutil.virtual_memory().total,
                'disk_total': psutil.disk_usage('/').total,
                'boot_time': datetime.fromtimestamp(psutil.boot_time()).strftime('%Y-%m-%d %H:%M:%S'),
                'python_version': f"{psutil.version_info.major}.{psutil.version_info.minor}.{psutil.version_info.micro}"
            }
        except Exception as e:
            self.logger.error(f"获取系统信息失败: {e}")
            return {}


if __name__ == "__main__":
    # 测试代码
    logging.basicConfig(level=logging.INFO)
    
    def on_metrics_collected(metrics: SystemMetrics):
        print(f"CPU: {metrics.cpu_percent:.1f}%, "
              f"Memory: {metrics.memory_percent:.1f}%, "
              f"Disk: {metrics.disk_percent:.1f}%")
    
    monitor = SystemMonitor(collection_interval=5)
    monitor.add_callback(on_metrics_collected)
    
    try:
        monitor.start_monitoring()
        time.sleep(30)  # 运行30秒
    except KeyboardInterrupt:
        print("监控被中断")
    finally:
        monitor.stop_monitoring()
