#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
LinuxAgent - 基于大语言模型的Linux运维助手
主程序入口
"""

import os
import sys
import logging
import argparse
from src.config import Config
from src.agent import Agent
from src.logger import setup_logger


def parse_arguments():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="LinuxAgent - 基于大语言模型的Linux运维助手"
    )
    parser.add_argument(
        "-c", "--config", 
        help="配置文件路径", 
        default="config.yaml"
    )
    parser.add_argument(
        "-d", "--debug", 
        help="启用调试模式", 
        action="store_true"
    )
    parser.add_argument(
        "-p", "--provider",
        help="指定LLM提供者 (deepseek, openai)",
        choices=["deepseek", "openai"],
        default=None
    )
    parser.add_argument(
        "-k", "--api-key",
        help="设置API密钥",
        default=None
    )
    parser.add_argument(
        "-v", "--version", 
        help="显示版本信息", 
        action="store_true"
    )
    
    return parser.parse_args()


def main():
    """主程序入口"""
    args = parse_arguments()
    
    if args.version:
        print("LinuxAgent v3.0.1")
        return 0
        
    try:
        config = Config(args.config)
        
        # 命令行参数覆盖配置文件设置
        if args.provider:
            config.api.provider = args.provider
        if args.api_key:
            config.api.api_key = args.api_key
            
    except Exception as e:
        print(f"配置加载失败: {e}")
        print(f"请确保配置文件 {args.config} 存在并格式正确")
        print(f"您可以从 config.yaml.example 复制并修改创建配置文件")
        return 1
    
    log_level = logging.DEBUG if args.debug else getattr(logging, config.logging.level)
    logger = setup_logger(
        level=log_level,
        log_file=os.path.expanduser(config.logging.file),
        max_size_mb=config.logging.max_size_mb,
        backup_count=config.logging.backup_count
    )
    
    logger.info("LinuxAgent启动中...")
    
    # 创建代理实例
    agent = Agent(config=config, logger=logger)
    
    try:
        agent.run()
    except KeyboardInterrupt:
        logger.info("用户中断，正在退出...")
    except Exception as e:
        logger.error(f"运行时错误: {e}", exc_info=True)
        return 1
    
    logger.info("LinuxAgent已退出")
    return 0


if __name__ == "__main__":
    sys.exit(main())
