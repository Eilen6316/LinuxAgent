#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
LinuxAgent 安装配置脚本
用于将LinuxAgent打包并安装为Python包

使用方法:
    1. 直接安装: python setup.py install
    2. 开发模式安装: python setup.py develop
    3. 构建分发包: python setup.py sdist bdist_wheel
    4. 上传到PyPI: python setup.py sdist bdist_wheel && twine upload dist/*
"""

from setuptools import setup, find_packages


with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

with open("requirements.txt", "r", encoding="utf-8") as f:
    requirements = f.read().splitlines()

# 配置包的元数据和安装选项
setup(
    # 包的基本信息
    name="linuxagent",        
    version="2.0.4",              
    author="树苗",                
    author_email="3068504755@qq.com", 
    description="基于大语言模型的Linux运维助手",  
    long_description=long_description,  
    long_description_content_type="text/markdown",  
    
    url="https://github.com/eilen6316/LinuxAgent",  
    
    packages=find_packages(),     
    
    classifiers=[
        "Programming Language :: Python :: 3",  
        "License :: OSI Approved :: MIT License",  
        "Operating System :: OS Independent",  
    ],
    
    python_requires=">=3.7",     

    install_requires=requirements,  
    
    entry_points={
        "console_scripts": [
            "linuxagent=linuxagent:main",  
        ],
    },
) 