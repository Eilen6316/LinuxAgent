# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller规格文件 - 用于将LinuxAgent打包成独立可执行文件
版本：2.0.5

使用方法:
    1. 安装PyInstaller: pip install pyinstaller
    2. 清理构建并打包: pyinstaller --clean pyinstaller.spec
    3. 获取打包文件: 生成的文件在dist/linuxagent目录下
    4. 复制配置文件到dist目录cp config.yaml dist/
    5. 运行程序: cd dist/linuxagent && ./linuxagent

注意事项:
    - 确保config.yaml文件存在于项目根目录
    - 打包会创建文件夹模式的可执行程序，配置文件会自动包含
    - 分发时只需将dist/linuxagent目录整体复制或打包
"""


block_cipher = None

# 定义应用程序的分析配置
a = Analysis(
    ['linuxagent.py'],            # 主程序入口文件
    pathex=[],                    # 额外的导入路径
    binaries=[],                  # 额外的二进制文件
    datas=[
        ('config.yaml', '.'),  # 配置文件模板
        ('README.md', '.'),           # 说明文档
        ('requirements.txt', '.'),     # 依赖列表
    ],
    hiddenimports=[               # 隐式导入的模块
        'rich.markdown',
        'rich.syntax',
        'rich.panel',
        'rich.console',
        'rich.theme',
        'rich.progress',
        'rich.live',
    ],
    hookspath=[],                 # 钩子脚本路径
    hooksconfig={},               # 钩子配置
    runtime_hooks=[],             # 运行时钩子
    excludes=[],                  # 排除的模块
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# 打包纯Python模块
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# 创建可执行文件
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='linuxagent',            # 可执行文件名称
    debug=False,                  # 是否包含调试信息
    bootloader_ignore_signals=False,
    strip=False,                  # 是否剥离符号表
    upx=True,                     # 是否使用UPX压缩
    upx_exclude=[],               # 不使用UPX压缩的文件
    runtime_tmpdir=None,          # 运行时临时目录
    console=True,                 # 是否显示控制台窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,             # 目标架构
    codesign_identity=None,       # 代码签名身份
    entitlements_file=None,       # 权限文件
) 