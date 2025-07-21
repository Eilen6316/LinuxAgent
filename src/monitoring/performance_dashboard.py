#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
性能监控仪表板模块
提供实时系统监控面板和性能可视化
"""

from rich.console import Console
from rich.table import Table
from rich.live import Live
from rich.layout import Layout
from rich.panel import Panel
from rich.progress import Progress, BarColumn, TextColumn
import time
from .system_monitor import SystemMonitor, SystemMetrics


class PerformanceDashboard:
    """性能监控仪表板"""
    
    def __init__(self, monitor: SystemMonitor):
        """
        初始化仪表板
        
        Args:
            monitor: 关联的系统监控器实例
        """
        self.monitor = monitor
        self.console = Console()
        
    def create_metrics_table(self, metrics: SystemMetrics) -> Table:
        """创建系统指标的表格显示"""
        table = Table(title="系统性能指标", show_header=True, header_style="bold magenta")
        table.add_column("指标", style="cyan")
        table.add_column("当前值", style="green")
        table.add_column("状态", style="yellow")
        
        # CPU 使用率
        cpu_status = "正常" if metrics.cpu_percent < 80 else "[警告] 高"
        table.add_row("CPU 使用率", f"{metrics.cpu_percent:.1f}%", cpu_status)
        
        # 内存使用率
        mem_status = "正常" if metrics.memory_percent < 80 else "[警告] 高"
        table.add_row("内存使用率", f"{metrics.memory_percent:.1f}%", mem_status)
        
        # 磁盘使用率
        disk_status = "正常" if metrics.disk_percent < 90 else "[警告] 高"
        table.add_row("磁盘使用率", f"{metrics.disk_percent:.1f}%", disk_status)
        
        # 进程数
        table.add_row("进程数", str(metrics.process_count), "正常")
        
        return table
    
    def create_progress_bars(self, metrics: SystemMetrics) -> Panel:
        """创建各项指标的进度条"""
        progress = Progress(
            TextColumn("[bold blue]{task.fields[name]}", justify="right"),
            BarColumn(bar_width=None),
            "[progress.percentage]{task.percentage:>3.1f}%"
        )
        
        cpu_task = progress.add_task("CPU", total=100, name="CPU 使用率")
        mem_task = progress.add_task("Memory", total=100, name="内存使用率")
        disk_task = progress.add_task("Disk", total=100, name="磁盘使用率")
        
        progress.update(cpu_task, completed=metrics.cpu_percent)
        progress.update(mem_task, completed=metrics.memory_percent)
        progress.update(disk_task, completed=metrics.disk_percent)
        
        return Panel(progress, title="系统资源使用率", border_style="green")
    
    def show_live_dashboard(self):
        """显示实时监控面板"""
        with Live(console=self.console, refresh_per_second=1) as live:
            while self.monitor.running:
                metrics = self.monitor.get_latest_metrics()
                
                if metrics:
                    layout = Layout()
                    layout.split(
                        Layout(self.create_metrics_table(metrics), name="metrics"),
                        Layout(self.create_progress_bars(metrics), name="progress")
                    )
                    live.update(layout)
                time.sleep(1)


# 测试运行
if __name__ == "__main__":
    from .system_monitor import SystemMonitor
    import logging

    logging.basicConfig(level=logging.INFO)

    monitor = SystemMonitor(collection_interval=5)
    dashboard = PerformanceDashboard(monitor)
    
    try:
        monitor.start_monitoring()
        dashboard.show_live_dashboard()
    except KeyboardInterrupt:
        print("退出监控仪表板...")
    finally:
        monitor.stop_monitoring()
