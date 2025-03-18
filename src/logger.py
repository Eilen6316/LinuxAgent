#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
日志模块
负责设置和管理应用日志
"""

import os
import logging
from logging.handlers import RotatingFileHandler


def setup_logger(
    level=logging.INFO,
    log_file="~/.linuxagent.log",
    max_size_mb=10,
    backup_count=5
):
    """设置应用日志"""
    logger = logging.getLogger("linuxagent")
    logger.setLevel(level)
    
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    
    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(level)
    logger.addHandler(console_handler)
    
    if log_file:
        log_file = os.path.expanduser(log_file)
        
        log_dir = os.path.dirname(log_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir)
        
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=max_size_mb * 1024 * 1024,
            backupCount=backup_count,
            encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(level)
        logger.addHandler(file_handler)
    
    return logger 