# LinuxAgent - 基于DeepSeek API的Linux运维助手

<div align="center">
  <img src="logo.jpg" alt="LinuxAgent Logo" width="400" />
  <p>
    <a href="#introduction-cn">🇨🇳 简体中文</a> | 
    <a href="#introduction-en">🇺🇸 English</a> | 
    <a href="#introduction-ja">🇯🇵 日本語</a> | 
    <a href="#introduction-ko">🇰🇷 한국어</a>
  </p>
</div>


---

<a id="introduction-cn"></a>

## 📌 简体中文

LinuxAgent是一个智能运维助手，通过接入DeepSeek API实现对Linux终端的自然语言控制，帮助用户更高效地进行系统运维工作。

### 更新日志

#### v2.0.5 (最新版本)

- 🔧 优化：移除了Windows特有的代码，提高在Linux系统下的兼容性
- 🚀 改进：简化流式输出逻辑，消除滚动功能带来的终端状态问题
- ✨ 增强：修复了AI回答完成后无法继续输入的bug
- 🛠️ 重构：优化代码结构，删除无用的平台检测逻辑
- 🔄 增强：改进了AgentMode和ChatMode的模式切换功能，提供更流畅的交互体验

#### v2.0.4

- 🚀 增加了流式输出功能，使AI回答更流畅
- 🎨 新增自定义主题功能，支持多种界面风格切换
- 📚 添加了交互式教程，帮助新用户快速上手
- 🔄 优化了多轮对话体验

#### v2.0.3

- 🔧 添加自动模式与手动模式切换功能
- 💬 增强了自然语言理解能力
- 🛡️ 增强安全检查机制

### 版本特性对比

| 特性 | v1.4.1 | v2.0.3 | v2.0.4 | v2.0.5 (最新) |
|------|--------|--------|--------|--------------|
| 自然语言理解 | ✓ | ✓ | ✓ | ✓ |
| 智能命令执行 | ✗ | ✓ | ✓ | ✓ |
| 安全控制机制 | ✓ | ✓ | ✓ | ✓ |
| 多轮对话支持 | ✗ | ✓ | ✓+ | ✓+ |
| 自动/手动模式切换 | ✗ | ✓ | ✓ | ✓ |
| 流式输出回答 | ✗ | ✗ | ✓ | ✓ |
| 自定义主题 | ✗ | ✗ | ✓ | ✓ |
| 交互式教程 | ✗ | ✗ | ✓ | ✓ |
| Linux专属优化 | ✗ | ✗ | ✗ | ✓ |
| 输入阻塞问题修复 | ✗ | ✗ | ✗ | ✓ |
| 终端状态恢复 | ✗ | ✗ | ✗ | ✓ |

### 功能特点

- 自然语言理解：通过DeepSeek API理解用户的自然语言指令
- 智能命令执行：将用户意图转换为Linux命令并安全执行
- 结果反馈：清晰展示命令执行结果
- 安全控制：内置安全检查机制，防止危险操作
- 历史记录：保存交互历史，方便复用和追踪

### 系统要求

- Rocky Linux 9.4 或其他兼容系统
- Python 3.8+
- 网络连接（用于访问DeepSeek API）
- DeepSeek API密钥

> **重要提示**: 从版本2.0.5起，LinuxAgent已专门针对Linux环境进行优化，移除了Windows相关代码，解决了终端状态和键盘输入问题。如果您在之前版本遇到过终端输入阻塞或"msvcrt"模块相关错误，强烈建议升级到最新版本。

### 安装说明

1. 克隆代码库

```bash
git clone https://gitcode.com/qq_69174109/LinuxAgent.git
cd LinuxAgent
```

2. 安装依赖

```bash
pip install -r requirements.txt
```

3. 配置DeepSeek API密钥

```bash
cp config.yaml.example config.yaml
# 编辑config.yaml，填入DeepSeek API密钥
```

### 详细使用指南

#### 获取DeepSeek API密钥

1. 访问DeepSeek官方网站（https://deepseek.com）注册账号
2. 在个人设置或API页面申请API密钥
3. 复制获得的API密钥

#### 配置系统

1. 编辑`config.yaml`文件：

```bash
vi config.yaml
```

2. 将您的API密钥填入配置文件的相应位置：

```yaml
api:
  api_key: "your_deepseek_api_key"  # 将此处替换为真实API密钥
```

3. 其他配置项说明：
   - `base_url`: DeepSeek API的基础URL，默认不需要修改
   - `model`: 使用的模型名称，默认使用"deepseek-chat"
   - `timeout`: API请求超时时间，默认30秒

4. 安全设置：
   - `confirm_dangerous_commands`: 是否确认危险命令(建议保持为true)
   - `blocked_commands`: 完全禁止执行的命令列表
   - `confirm_patterns`: 需要确认才能执行的命令模式

#### 启动运行

1. 直接运行主程序：

```bash
python linuxagent.py
```

2. 使用调试模式运行（显示更多日志信息）：

```bash
python linuxagent.py -d
```

3. 指定配置文件路径：

```bash
python linuxagent.py -c /path/to/your/config.yaml
```

### 日常使用

1. **基本交互方式**：

   - 启动程序后，您会看到提示符`[LinuxAgent] >`
   - 直接输入自然语言指令，例如："帮我查看系统内存使用情况"
   - 系统会调用DeepSeek API分析您的指令并生成对应的Linux命令
   - 显示命令并执行，然后返回结果分析

2. **内置命令**：

   - `help`: 显示帮助信息
   - `exit`或`quit`: 退出程序
   - `clear`: 清屏
   - `history`: 显示历史记录
   - `config`: 显示当前配置

3. **常用示例**：

   系统信息类：

   - "显示系统基本信息"
   - "查看当前系统负载情况"
   - "检查系统已运行时间和登录用户"

   文件操作类：

   - "查找/var目录下最近7天修改的大于100MB的文件"
   - "找出/home目录下权限为777的文件并列出"
   - "将/tmp目录下30天前的日志文件压缩"

   服务管理类：

   - "查看所有正在运行的服务"
   - "检查nginx服务状态并确保它在启动时自动运行"
   - "重启MySQL服务并查看最近的错误日志"

   网络操作类：

   - "检查网络连接状态"
   - "显示所有开放的网络端口和对应的进程"
   - "测试到百度和谷歌的网络连接"

4. **高级用法**：

   - 管道和复杂命令：
     "查找占用CPU最高的5个进程，并显示它们的详细信息"

   - 多步骤任务：
     "备份MySQL数据库，压缩备份文件，然后移动到/backup目录"

   - 定期任务设置：
     "创建一个cron任务，每天凌晨3点自动清理/tmp目录下的临时文件"

5. **设置功能**：

   - 主题设置：
     ```
     [LinuxAgent] > theme
     ```
     可选择不同的界面主题，包括默认、暗色、亮色、复古和海洋等主题风格。

   - 语言设置：
     ```
     [LinuxAgent] > language
     ```
     支持切换中文、英文等多种语言界面。

   - 模式切换：
     ```
     [LinuxAgent] > mode
     [LinuxAgent] > chat mode
     [LinuxAgent] > agent mode
     [LinuxAgent] > auto mode
     ```
     在聊天模式、命令执行模式和自动模式之间切换。

   - API密钥设置：
     ```
     [LinuxAgent] > set api_key YOUR_API_KEY
     ```
     在不修改配置文件的情况下，直接在程序内设置DeepSeek API密钥。

   - 教程启动：
     ```
     [LinuxAgent] > tutorial
     ```
     启动交互式教程，学习如何使用LinuxAgent。
     
   - 会话导出：
     ```
     [LinuxAgent] > export chat
     ```
     将当前会话内容导出为文档或脚本。

### 安全注意事项

1. **命令确认机制**：
   - 对于潜在危险的命令（如删除文件、修改系统配置等），系统会要求确认
   - 确认提示格式为："此命令可能有风险: [风险原因]。确认执行? [y/N]"
   - 输入y或yes确认执行，其他输入会取消执行

2. **命令审查建议**：
   - 即使LinuxAgent有安全机制，仍建议您在执行前仔细审查生成的命令
   - 特别是在生产环境中使用时，确保理解命令的作用和可能的影响

3. **权限控制**：
   - LinuxAgent继承您当前用户的权限执行命令
   - 建议使用普通用户运行，需要特权时手动确认sudo操作

### 疑难解答

1. **API连接问题**：
   - 确认网络连接正常
   - 验证API密钥正确且未过期
   - 检查base_url配置是否正确

2. **命令执行失败**：
   - 查看错误信息和建议修复方法
   - 确认系统中已安装相关命令所需的程序
   - 检查用户权限是否足够

3. **性能问题**：
   - 如果响应缓慢，可以调整timeout参数
   - 对于复杂任务，考虑拆分为多个简单指令

4. **日志信息**：
   - 日志文件默认保存在`~/.linuxagent.log`
   - 使用`-d`参数启动可查看更详细的调试信息

### 联系方式

- 作者QQ：3068504755
- QQ群：281392454

## 许可证

MIT License

## 特性功能

- 🚀 使用自然语言描述需求，自动转换为Linux命令
- 🔍 命令执行前的安全检查和风险提示
- 📊 命令执行结果的智能分析和解释
- 🔄 多命令序列的拆分执行和状态跟踪
- 📝 支持交互式命令的智能识别与执行（如vim、nano等编辑器）
- ⏱️ 长时间运行命令的智能超时管理
- 🎨 美观的终端用户界面

## 使用方法

### 基本用法

```bash
# 启动LinuxAgent
./linuxagent.py
```

输入自然语言命令，LinuxAgent会自动转换为相应的Linux命令并执行：

```
[LinuxAgent] > 查找最近7天内修改过的大于100MB的日志文件
```

### 特殊命令

- `help` - 显示帮助信息
- `exit` 或 `quit` - 退出程序
- `clear` - 清屏
- `history` - 显示命令历史
- `config` - 显示当前配置

### 交互式命令

LinuxAgent支持直接使用交互式命令或自然语言描述：

```
# 直接使用命令
[LinuxAgent] > vim /etc/nginx/nginx.conf

# 使用自然语言描述
[LinuxAgent] > 使用nano编辑apache配置文件
[LinuxAgent] > 编辑/etc/fstab文件用vim
[LinuxAgent] > 用htop查看系统资源占用
```

支持的交互式命令包括：

- 文本编辑器：vim, vi, nano, emacs
- 命令行工具：top, htop, less, more
- 数据库客户端：mysql, psql, sqlite3
- Shell程序：bash, sh, zsh
- 网络工具：ssh, telnet, ftp, sftp

## 高级功能

### 命令拆分执行

对于复杂的多步骤命令，LinuxAgent可以将其拆分为多个步骤执行，提供更好的可控性：

```
[LinuxAgent] > 更新系统，安装nginx，并设置开机启动
```

系统会询问是否要将这个复杂命令拆分为多个步骤执行。

### 交互式编辑

可以通过`edit`命令直接编辑文件：

```
[LinuxAgent] > edit /etc/hosts vim
```

或者使用自然语言描述：

```
[LinuxAgent] > 使用nano编辑/etc/resolv.conf
```

---

<a id="introduction-en"></a>

## 📌 English

LinuxAgent is an intelligent operations assistant that enables natural language control of the Linux terminal through the DeepSeek API, helping users perform system operations more efficiently.

### Update Log

#### v2.0.5 (Latest)

- 🔧 Optimized: Removed Windows-specific code to improve compatibility on Linux systems
- 🚀 Improved: Simplified stream output logic, eliminating terminal state issues caused by scrolling
- ✨ Enhanced: Fixed the bug where input was blocked after AI response completion
- 🛠️ Refactored: Optimized code structure, removed unnecessary platform detection logic
- 🔄 Enhanced: Improved AgentMode and ChatMode switching functionality for a smoother interaction experience

#### v2.0.4

- 🚀 Added streaming output functionality for smoother AI responses
- 🎨 Added custom theme feature with multiple interface styles
- 📚 Added interactive tutorial to help new users get started
- 🔄 Improved multi-turn conversation experience

#### v2.0.3

- 🔧 Added automatic and manual mode switching
- 💬 Enhanced natural language understanding capabilities
- 🛡️ Strengthened security check mechanisms

### Feature Comparison

| Feature | v1.4.1 | v2.0.3 | v2.0.4 | v2.0.5 (Latest) |
|---------|--------|--------|--------|-----------------|
| Natural Language Understanding | ✓ | ✓ | ✓ | ✓ |
| Intelligent Command Execution | ✗ | ✓ | ✓ | ✓ |
| Security Control Mechanism | ✓ | ✓ | ✓ | ✓ |
| Multi-turn Conversation | ✗ | ✓ | ✓+ | ✓+ |
| Auto/Manual Mode Switching | ✗ | ✓ | ✓ | ✓ |
| Streaming Output | ✗ | ✗ | ✓ | ✓ |
| Custom Themes | ✗ | ✗ | ✓ | ✓ |
| Interactive Tutorial | ✗ | ✗ | ✓ | ✓ |
| Linux-specific Optimization | ✗ | ✗ | ✗ | ✓ |
| Input Blocking Issue Fixed | ✗ | ✗ | ✗ | ✓ |
| Terminal State Recovery | ✗ | ✗ | ✗ | ✓ |

### Features

- Natural Language Understanding: Understands user's natural language instructions through the DeepSeek API
- Intelligent Command Execution: Converts user intent into Linux commands and executes them safely
- Result Feedback: Clearly displays command execution results
- Security Control: Built-in security check mechanism to prevent dangerous operations
- History Record: Saves interaction history for reuse and tracking

### System Requirements

- Rocky Linux 9.4 or other compatible systems
- Python 3.8+
- Network connection (for accessing DeepSeek API)
- DeepSeek API key

> **Important Note**: Starting from version 2.0.5, LinuxAgent has been specifically optimized for Linux environments, removing Windows-related code and solving terminal state and keyboard input issues. If you encountered terminal input blocking or "msvcrt" module-related errors in previous versions, it is strongly recommended to upgrade to the latest version.

### Installation Guide

1. Clone the repository

```bash
git clone https://gitcode.com/qq_69174109/LinuxAgent.git
cd LinuxAgent
```

2. Install dependencies

```bash
pip install -r requirements.txt
```

3. Configure DeepSeek API key

```bash
cp config.yaml.example config.yaml
# Edit config.yaml and fill in your DeepSeek API key
```

### Detailed Usage Guide

#### Obtaining a DeepSeek API Key

1. Visit the DeepSeek official website (https://deepseek.com) to register an account
2. Apply for an API key in personal settings or API page
3. Copy the obtained API key

#### System Configuration

1. Edit the `config.yaml` file:

```bash
vi config.yaml
```

2. Fill in your API key in the appropriate location in the configuration file:

```yaml
api:
  api_key: "your_deepseek_api_key"  # Replace with your actual API key
```

3. Other configuration items:
   - `base_url`: Base URL of the DeepSeek API, usually doesn't need modification
   - `model`: Model name to use, defaults to "deepseek-chat"
   - `timeout`: API request timeout, default is 30 seconds

4. Security settings:
   - `confirm_dangerous_commands`: Whether to confirm dangerous commands (recommended to keep as true)
   - `blocked_commands`: List of commands completely forbidden to execute
   - `confirm_patterns`: Command patterns that need confirmation before execution

#### Launching

1. Run the main program directly:

```bash
python linuxagent.py
```

2. Run in debug mode (shows more log information):

```bash
python linuxagent.py -d
```

3. Specify configuration file path:

```bash
python linuxagent.py -c /path/to/your/config.yaml
```

### Daily Usage

1. **Basic Interaction**:

   - After starting the program, you will see a prompt `[LinuxAgent] >`
   - Enter natural language instructions directly, e.g., "Show me system memory usage"
   - The system will call the DeepSeek API to analyze your instructions and generate corresponding Linux commands
   - Display the command and execute it, then return result analysis

2. **Built-in Commands**:

   - `help`: Display help information
   - `exit` or `quit`: Exit the program
   - `clear`: Clear the screen
   - `history`: Show command history
   - `config`: Display current configuration

3. **Common Examples**:

   System Information:

   - "Show basic system information"
   - "Check current system load"
   - "Check system uptime and logged-in users"

   File Operations:

   - "Find files in /var modified in the last 7 days larger than 100MB"
   - "Find files with 777 permissions in /home and list them"
   - "Compress log files in /tmp that are older than 30 days"

   Service Management:

   - "View all running services"
   - "Check nginx service status and ensure it runs at startup"
   - "Restart MySQL service and check recent error logs"

   Network Operations:

   - "Check network connection status"
   - "Show all open network ports and corresponding processes"
   - "Test network connection to Baidu and Google"

4. **Advanced Usage**:

   - Pipes and complex commands:
     "Find the top 5 CPU-consuming processes and show their details"

   - Multi-step tasks:
     "Backup MySQL database, compress the backup file, then move it to /backup directory"

   - Scheduled tasks:
     "Create a cron job to automatically clean temporary files in /tmp directory at 3 AM daily"

5. **Setting Features**:

   - Theme Setting:
     ```
     [LinuxAgent] > theme
     ```
     Select different interface themes, including default, dark, light, retro, and ocean themes.

   - Language Setting:
     ```
     [LinuxAgent] > language
     ```
     Support switching between Chinese, English, and other language interfaces.

   - Mode Switching:
     ```
     [LinuxAgent] > mode
     [LinuxAgent] > chat mode
     [LinuxAgent] > agent mode
     [LinuxAgent] > auto mode
     ```
     Switch between chat mode, command execution mode, and auto mode.

   - API Key Setting:
     ```
     [LinuxAgent] > set api_key YOUR_API_KEY
     ```
     Configure DeepSeek API key directly within the program without modifying the configuration file.

   - Tutorial Launch:
     ```
     [LinuxAgent] > tutorial
     ```
     Launch interactive tutorial to learn how to use LinuxAgent.
     
   - Session Export:
     ```
     [LinuxAgent] > export chat
     ```
     Export current session content as document or script.

### Security Considerations

1. **Command Confirmation Mechanism**:
   - For potentially dangerous commands (such as deleting files, modifying system configurations), the system will require confirmation
   - Confirmation prompt format: "This command may be risky: [risk reason]. Confirm execution? [y/N]"
   - Enter y or yes to confirm execution, other inputs will cancel execution

2. **Command Review Suggestions**:
   - Even though LinuxAgent has security mechanisms, it is still recommended to carefully review generated commands before execution
   - Especially when used in production environments, ensure you understand the function and potential impact of commands

3. **Permission Control**:
   - LinuxAgent inherits your current user's permissions to execute commands
   - It is recommended to run with a regular user and manually confirm sudo operations when privileges are needed

### Troubleshooting

1. **API Connection Issues**:
   - Confirm normal network connection
   - Verify API key is correct and not expired
   - Check if base_url configuration is correct

2. **Command Execution Failure**:
   - View error information and suggested fixes
   - Confirm that required programs for relevant commands are installed on the system
   - Check if user permissions are sufficient

3. **Performance Issues**:
   - If response is slow, adjust the timeout parameter
   - For complex tasks, consider breaking them down into multiple simple instructions

4. **Log Information**:
   - Log files are saved by default in `~/.linuxagent.log`
   - Use the `-d` parameter to start for more detailed debug information

### Contact Information

- Author QQ: 3068504755
- QQ Group: 281392454

## License

MIT License

## 特性功能

- 🚀 使用自然语言描述需求，自动转换为Linux命令
- 🔍 命令执行前的安全检查和风险提示
- 📊 命令执行结果的智能分析和解释
- 🔄 多命令序列的拆分执行和状态跟踪
- 📝 支持交互式命令的智能识别与执行（如vim、nano等编辑器）
- ⏱️ 长时间运行命令的智能超时管理
- 🎨 美观的终端用户界面

## 使用方法

### 基本用法

```bash
# 启动LinuxAgent
./linuxagent.py
```

输入自然语言命令，LinuxAgent会自动转换为相应的Linux命令并执行：

```
[LinuxAgent] > 查找最近7天内修改过的大于100MB的日志文件
```

### 特殊命令

- `help` - 显示帮助信息
- `exit` 或 `quit` - 退出程序
- `clear` - 清屏
- `history` - 显示命令历史
- `config` - 显示当前配置

### 交互式命令

LinuxAgent supports direct use of interactive commands or natural language description:

```
# 直接使用命令
[LinuxAgent] > vim /etc/nginx/nginx.conf

# 使用自然语言描述
[LinuxAgent] > 使用nano编辑apache配置文件
[LinuxAgent] > 编辑/etc/fstab文件用vim
[LinuxAgent] > 用htop查看系统资源占用
```

支持的交互式命令包括：

- 文本编辑器：vim, vi, nano, emacs
- 命令行工具：top, htop, less, more
- 数据库客户端：mysql, psql, sqlite3
- Shell程序：bash, sh, zsh
- 网络工具：ssh, telnet, ftp, sftp

## 高级功能

### 命令拆分执行

对于复杂的多步骤命令，LinuxAgent can split it into multiple steps to provide better controllability:

```
[LinuxAgent] > 更新系统，安装nginx，并设置开机启动
```

System will ask whether to split this complex command into multiple steps.

### Interactive Editing

You can edit files directly using the `edit` command:

```
[LinuxAgent] > edit /etc/hosts vim
```

Or use natural language description:

```
[LinuxAgent] > 使用nano编辑/etc/resolv.conf
```

---

<a id="introduction-ja"></a>

## 📌 日本語

LinuxAgentは、DeepSeek APIを通じてLinuxターミナルの自然言語制御を実現するインテリジェントな運用アシスタントで、ユーザーがシステム運用をより効率的に行うのを支援します。

### 更新ログ

#### v2.0.5 (最新)

- 🔧 最適化：Windows固有のコードを削除し、Linux環境での互換性を向上
- 🚀 改善：ストリーミング出力ロジックを簡素化し、スクロール機能によるターミナル状態の問題を解消
- ✨ 機能強化：AI応答完了後に入力ができなくなるバグを修正
- 🛠️ リファクタリング：コード構造を最適化し、不要なプラットフォーム検出ロジックを削除
- 🔄 強化：AgentModeとChatModeのモード切り替え機能を改善し、よりスムーズなインタラクション体験を提供

#### v2.0.4

- 🚀 スムーズなAI応答のためのストリーミング出力機能を追加
- 🎨 複数のインターフェーススタイルを持つカスタムテーマ機能を追加
- 📚 新規ユーザーの学習を支援する対話型チュートリアルを追加
- 🔄 複数回の会話体験を改善

#### v2.0.3

- 🔧 自動モードと手動モード切替機能を追加
- 💬 自然言語理解能力を強化
- 🛡️ セキュリティチェックメカニズムを強化

### 機能 比較

| 機能 | v1.4.1 | v2.0.3 | v2.0.4 | v2.0.5 (最新) |
|------|--------|--------|--------|--------------|
| 自然言語理解 | ✓ | ✓ | ✓ | ✓ |
| インテリジェントなコマンド実行 | ✗ | ✓ | ✓ | ✓ |
| セキュリティ制御メカニズム | ✓ | ✓ | ✓ | ✓ |
| 複数回の会話 | ✗ | ✓ | ✓+ | ✓+ |
| 自動/手動モード切替 | ✗ | ✓ | ✓ | ✓ |
| ストリーミング出力 | ✗ | ✗ | ✓ | ✓ |
| カスタムテーマ | ✗ | ✗ | ✓ | ✓ |
| 対話型チュートリアル | ✗ | ✗ | ✓ | ✓ |
| Linux専用最適化 | ✗ | ✗ | ✗ | ✓ |
| 入力ブロック問題の修正 | ✗ | ✗ | ✗ | ✓ |
| ターミナル状態の復元 | ✗ | ✗ | ✗ | ✓ |

### 特徴

- 自然言語理解：DeepSeek APIを通じてユーザーの自然言語指示を理解
- インテリジェントなコマンド実行: ユーザーの意図をLinuxコマンドに変換し、安全に実行
- 結果フィードバック：コマンド実行結果を明確に表示
- セキュリティ制御：危険な操作を防ぐ内蔵セキュリティチェックメカニズム
- 履歴記録：再利用と追跡を行うための対話履歴を保存

### システム要件

- Rocky Linux 9.4またはその他の互換性のあるシステム
- Python 3.8+
- ネットワーク接続（DeepSeek APIへのアクセス用）
- DeepSeek APIキー

### インストールガイド

1. リポジトリのクローン

```bash
git clone https://gitcode.com/qq_69174109/LinuxAgent.git
cd LinuxAgent
```

2. 依存関係のインストール

```bash
pip install -r requirements.txt
```

3. DeepSeek APIキーの設定

```bash
cp config.yaml.example config.yaml
# config.yamlを編集し、DeepSeek APIキーを入力
```

### 詳細な使用ガイド

#### DeepSeek APIキーの取得

1. DeepSeek公式ウェブサイト(https://deepseek.com)にアクセスしてアカウントを登録
2. 個人設定またはAPIページでAPIキーを申請
3. 取得したAPIキーをコピー

#### システム設定

1. `config.yaml`ファイルを編集：

```bash
vi config.yaml
```

2. 設定ファイルの適切な場所にAPIキーを入力：

```yaml
api:
  api_key: "your_deepseek_api_key"  # 実際のAPIキーに置き換える
```

3. その他の設定項目：
   - `base_url`: DeepSeek APIのベースURL、通常は変更不要
   - `model`: 使用するモデル名、デフォルトは"deepseek-chat"
   - `timeout`: APIリクエストのタイムアウト、デフォルトは30秒

4. セキュリティ設定：
   - `confirm_dangerous_commands`: 危険なコマンドを確認するかどうか（trueに保つことを推奨）
   - `blocked_commands`: 実行が完全に禁止されているコマンドのリスト
   - `confirm_patterns`: 実行前に確認が必要なコマンドパターン

#### 起動

1. メインプログラムを直接実行：

```bash
python linuxagent.py
```

2. デバッグモードで実行（より多くのログ情報を表示）：

```bash
python linuxagent.py -d
```

3. 設定ファイルのパスを指定：

```bash
python linuxagent.py -c /path/to/your/config.yaml
```

### 日常的な使用

1. **基本的な対話**：

   - プログラムを起動すると、プロンプト`[LinuxAgent] >`が表示されます
   - "システムメモリの使用状況を表示して"などの自然言語指示を直接入力します
   - システムはDeepSeek APIを呼び出して指示を分析し、対応するLinuxコマンドを生成します
   - コマンドを表示して実行し、結果分析を返します

2. **組み込みコマンド**：

   - `help`: ヘルプ情報を表示
   - `exit` または`quit`: プログラムを終了
   - `clear`: 画面をクリア
   - `history`: コマンド履歴を表示
   - `config`: 現在の設定を表示

3. **一般的な例**：

   システム情報：

   - "基本的なシステム情報を表示"
   - "現在のシステム負荷を確認"
   - "システムの稼働時間とログインユーザーを確認"

   ファイル操作：

   - "/varディレクトリに過去7日間に変更された100MB以上のファイルを検索"
   - "/homeディレクトリに権限が777のファイルを検索して一覧表示"
   - "/tmpディレクトリにある30日以上前のログファイルを圧縮"

   サービス管理：

   - "実行中のすべてのサービスを表示"
   - "nginxサービスのステータスを確認し、起動時に自動実行されるようにする"
   - "MySQLサービスを再起動し、最近のエラーログを確認"

   ネットワーク操作：

   - "ネットワーク接続状態を確認"
   - "すべての開いているネットワークポートと対応するプロセスを表示"
   - "BaiduとGoogleに対するネットワーク接続をテスト"

4. **高度な使用法**：

   - パイプと複雑なコマンド：
     "CPU 使用率が最も高い5つのプロセスを検索し、詳細を表示"

   - 複数ステップのタスク：
     "MySQLデータベースをバックアップし、バックアップファイルを圧縮してから/backupディレクトリに移動"

   - 定期的なタスク設定：
     "/tmpディレクトリの一時ファイルを毎日午前3時に自動的にクリーンアップするcronジョブを作成"

5. **設定機能**：

   - テーマ設定：
     ```
     [LinuxAgent] > theme
     ```
     異なるインターフェーステーマを選択可能。

   - 言語設定：
     ```
     [LinuxAgent] > language
     ```
     中国語、英語などの言語インターフェースに切り替え可能。

   - モード切り替え：
     ```
     [LinuxAgent] > mode
     [LinuxAgent] > chat mode
     [LinuxAgent] > agent mode
     [LinuxAgent] > auto mode
     ```
     コマンド実行モード、自動モード間の切り替えが可能です。

   - APIキー設定：
     ```
     [LinuxAgent] > set api_key YOUR_API_KEY
     ```
     設定ファイルを修正せずにプログラム内で直接DeepSeek APIキーを設定します。

   - チュートリアル実行：
     ```
     [LinuxAgent] > tutorial
     ```
     対話型チュートリアルを開始してLinuxAgentの使用方法を学習します。
     
   - 会話エクスポート：
     ```
     [LinuxAgent] > export chat
     ```
     現在の会話内容をドキュメントやスクリプトとしてエクスポートします。

### セキュリティに関する考慮事項

1. **コマンド確認メカニズム**：
   - 潜在的に危険なコマンド(ファイルの削除、システム構成の変更等)の場合、システムは確認を要求します
   - 確認プロンプトの形式：「このコマンドは危険かもしれません: [リスク理由]. 実行を確認しますか？ [y/N]"
   - y または yesを入力して実行を確認し、他の入力は実行をキャンセルします

2. **コマンドレビューの提案**：
   - LinuxAgentにセキュリティメカニズムがあっても、実行前に生成されたコマンドを慎重にレビューすることをお勧めします
   - 特に本番環境で使用する場合は、コマンドの機能と潜在的な影響を理解していることを確認してください

3. **権限制御**：
   - LinuxAgentは現在のユーザーの権限を継承してコマンドを実行します
   - 通常のユーザーで実行し、特権が必要な場合はsudo操作を手動で確認することをお勧めします

### トラブルシューティング

1. **API接続の問題**：
   - 正常なネットワーク接続を確認
   - APIキーが正しく、期限切れでないことを確認
   - base_url設定が正しいかどうかを確認

2. **コマンド実行の失敗**：
   - エラー情報と提案された修正を表示
   - 関連するコマンドに必要なプログラムがシステムにインストールされていることを確認
   - ユーザー権限が十分かどうかを確認

3. **性能の問題**：
   - 応答が遅い場合は、timeoutパラメータを調整します
   - 複雑なタスクの場合は、複数の簡単な指示に分解することを検討してください

4. **ログ情報**：
   - ログファイルはデフォルトで`~/.linuxagent.log`に保存されます
   - 使用`-d`パラメータ起動でより詳細なデバッグ情報を表示できます

### 連絡先

- 作者QQ：3068504755
- QQグループ：281392454

## ライセンス

MIT License

---

<a id="introduction-ko"></a>

## 📌 한국어

LinuxAgent는 DeepSeek API를 통해 Linux 터미널의 자연어 제어를 실현하는 지능형 운영 보조 도구로, 사용자가 시스템 운영 작업을 더 효율적으로 수행할 수 있도록 도와줍니다.

### 업데이트 로그

#### v2.0.5 (최신)

- 🔧 최적화: Windows 특정 코드 제거로 Linux 시스템 호환성 향상
- 🚀 개선: 스트리밍 출력 로직 단순화, 스크롤 기능으로 인한 터미널 상태 문제 해결
- ✨ 향상: AI 응답 완료 후 입력이 차단되는 버그 수정
- 🛠️ 리팩터링: 코드 구조 최적화, 불필요한 플랫폼 감지 로직 제거
- 🔄 강화: AgentMode와 ChatMode의 모드 전환 기능을 개선하여 더 원활한 인터랙션 경험을 제공

#### v2.0.4

- 🚀 스트리밍 출력 기능을 추가하여 원활한 AI 응답을 제공
- 🎨 다양한 인터페이스 스타일을 가진 커스텀 테마 기능을 추가
- 📚 새로운 사용자를 지원하는 대화형 튜토리얼을 추가
- 🔄 다중 대화 경험을 개선

#### v2.0.3

- 🔧 자동 모드와 수동 모드 전환 기능을 추가
- 💬 자연어 이해 능력을 강화
- 🛡️ 보안 검사 메커니즘을 강화

### 기능 비교

| 기능 | v1.4.1 | v2.0.3 | v2.0.4 | v2.0.5 (최신) |
|------|--------|--------|--------|--------------|
| 자연어 이해 | ✓ | ✓ | ✓ | ✓ |
| 지능형 명령 실행 | ✗ | ✓ | ✓ | ✓ |
| 보안 제어 메커니즘 | ✓ | ✓ | ✓ | ✓ |
| 다중 대화 지원 | ✗ | ✓ | ✓+ | ✓+ |
| 자동/수동 모드 전환 | ✗ | ✓ | ✓ | ✓ |
| 스트리밍 출력 | ✗ | ✗ | ✓ | ✓ |
| 사용자 정의 테마 | ✗ | ✗ | ✓ | ✓ |
| 대화형 튜토리얼 | ✗ | ✗ | ✓ | ✓ |
| Linux 전용 최적화 | ✗ | ✗ | ✗ | ✓ |
| 입력 차단 문제 수정 | ✗ | ✗ | ✗ | ✓ |
| 터미널 상태 복구 | ✗ | ✗ | ✗ | ✓ |

### 기능 특징

- 자연어 이해: DeepSeek API를 통해 사용자의 자연어 지시를 이해
- 지능형 명령 실행: 사용자 의도를 Linux 명령으로 변환하고 안전하게 실행
- 결과 피드백: 명령 실행 결과를 명확하게 표시
- 보안 제어: 위험한 작업을 방지하는 내장 보안 검사 메커니즘
- 기록 저장: 재사용 및 추적을 위한 상호작용 기록 저장

### 시스템 요구사항

- Rocky Linux 9.4 또는 기타 호환 시스템
- Python 3.8+
- 네트워크 연결(DeepSeek API 액세스용)
- DeepSeek API 키

### 설치 안내

1. 저장소 복제

```bash
git clone https://gitcode.com/qq_69174109/LinuxAgent.git
cd LinuxAgent
```

2. 의존성 설치

```bash
pip install -r requirements.txt
```

3. DeepSeek API 키 구성

```bash
cp config.yaml.example config.yaml
# config.yaml을 편집하고 DeepSeek API 키를 입력
```

### 자세한 사용 안내

#### DeepSeek API 키 얻기

1. DeepSeek 공식 웹사이트(https://deepseek.com)를 방문하여 계정 등록
2. 개인 설정 또는 API 페이지에서 API 키 신청
3. 얻은 API 키 복사

#### 시스템 구성

1. `config.yaml` 파일 편집:

```bash
vi config.yaml
```

2. 구성 파일의 적절한 위치에 API 키 입력:

```yaml
api:
  api_key: "your_deepseek_api_key"  # 실제 API 키로 대체
```

3. 기타 구성 항목:
   - `base_url`: DeepSeek API의 기본 URL, 일반적으로 수정 필요 없음
   - `model`: 사용할 모델 이름, 기본값은 "deepseek-chat"
   - `timeout`: API 요청 시간 초과, 기본값은 30초

4. 보안 설정:
   - `confirm_dangerous_commands`: 위험한 명령을 확인할지 여부(true로 유지 권장)
   - `blocked_commands`: 실행이 완전히 금지된 명령 목록
   - `confirm_patterns`: 실행 전 확인이 필요한 명령 패턴

#### 시작하기

1. 메인 프로그램 직접 실행:

```bash
python linuxagent.py
```

2. 디버그 모드로 실행(더 많은 로그 정보 표시):

```bash
python linuxagent.py -d
```

3. 구성 파일 경로 지정:

```bash
python linuxagent.py -c /path/to/your/config.yaml
```

### 일상적인 사용

1. **기본 상호작용**:

   - 프로그램 시작 후 프롬프트`[LinuxAgent] >`가 표시됩니다
   - "시스템 메모리의 사용 상태를 보여줘"와 같은 자연어 지시를 직접 입력합니다
   - 시스템은 DeepSeek API를 호출하여 지시를 분석하고 해당 Linux 명령을 생성합니다
   - 명령을 표시하고 실행한 다음 결과 분석을 반환합니다

2. **내장 명령**:

   - `help`: 도움말 정보 표시
   - `exit` 또는 `quit`: 프로그램 종료
   - `clear`: 화면 지우기
   - `history`: 명령 기록 표시
   - `config`: 현재 구성 표시

3. **일반적인 예**:

   시스템 정보:

   - "기본 시스템 정보를 보여줘"
   - "현재 시스템 부하를 확인하세요"
   - "시스템의 가동 시간과 로그인 사용자를 확인하세요"

   파일 작업:

   - "/var 디렉토리에서 최근 7일간에 수정된 100MB 이상의 파일을 찾아보세요"
   - "/home 디렉토리에서 권한이 777인 파일을 찾고 나열해보세요"
   - "/tmp 디렉토리에서 30일 이상 된 로그 파일을 압축해보세요"

   서비스 관리:

   - "실행 중인 모든 서비스를 보여줘"
   - "nginx 서비스의 상태를 확인하고 시작 시에 자동으로 실행되도록 보장하세요"
   - "MySQL 서비스를 다시 시작하고 최근 오류 로그를 확인하세요"

   네트워크 작업:

   - "네트워크 연결 상태를 확인하세요"
   - "모든 열린 네트워크 포트와 해당 프로세스를 보여줘"
   - "Baidu와 Google에 대한 네트워크 연결을 테스트하세요"

4. **고급 사용법**:

   - 파이프와 복잡한 명령:
     "CPU 사용률이 가장 높은 5개 프로세스를 찾고 세부 정보를 보여줘"

   - 다단계 작업:
     "MySQL 데이터베이스를 백업하고 백업 파일을 압축한 다음 /backup 디렉토리로 이동하세요"

   - 정기 작업 설정:
     "/tmp 디렉토리의 임시 파일을 매일 오전 3시에 자동으로 정리하는 cron 작업을 만들어보세요"

5. **설정 기능**:

   - 테마 설정:
     ```
     [LinuxAgent] > theme
     ```
     다양한 인터페이스 테마를 선택할 수 있습니다.

   - 언어 설정:
     ```
     [LinuxAgent] > language
     ```
     중국어, 영어 등의 언어 인터페이스로 전환할 수 있습니다.

   - 모드 전환:
     ```
     [LinuxAgent] > mode
     [LinuxAgent] > chat mode
     [LinuxAgent] > agent mode
     [LinuxAgent] > auto mode
     ```
     채팅 모드, 명령 실행 모드, 자동 모드 간 전환이 가능합니다.

   - API 키 설정:
     ```
     [LinuxAgent] > set api_key YOUR_API_KEY
     ```
     설정 파일을 수정하지 않고 프로그램 내에서 직접 DeepSeek API 키를 설정합니다.

   - 튜토리얼 실행:
     ```
     [LinuxAgent] > tutorial
     ```
     대화형 튜토리얼을 시작하여 LinuxAgent 사용법을 학습합니다.
     
   - 대화 내보내기:
     ```
     [LinuxAgent] > export chat
     ```
     현재 대화 내용을 문서나 스크립트로 내보냅니다.

### 보안에 대한 고려 사항

1. **커맨드 확인 메커니즘**:
   - 잠재적으로 위험한 커맨드(파일 삭제, 시스템 구성 변경 등)의 경우 시스템은 확인을 요구합니다
   - 확인 프롬프트 형식: "이 커맨드는 위험할 수도 있습니다: [위험 이유]. 실행을 확인하시겠습니까? [y/N]"
   - y 또는 yes를 입력하여 실행을 확인하고 다른 입력은 실행을 취소합니다

2. **커맨드 검토 제안**:
   - LinuxAgent에 보안 메커니즘이 있더라도 실행 전에 생성된 커맨드를 주의 깊게 검토하는 것을 권장합니다
   - 특히 프로덕션 환경에서 사용할 때는 커맨드의 기능과 잠재적인 영향을 이해하고 있는지 확인하세요

3. **권한 제어**:
   - LinuxAgent는 현재 사용자의 권한을 상속하여 명령을 실행합니다
   - 일반 사용자로 실행하고 권한이 필요한 경우 sudo 작업을 수동으로 확인하는 것을 권장합니다

### 트러블슈팅

1. **API 연결 문제**:
   - 정상적인 네트워크 연결을 확인
   - API 키가 올바르고 만료되지 않았는지 확인
   - base_url 설정이 올바한지 확인

2. **명령 실행 실패**:
   - 오류 정보와 제안된 수정을 표시
   - 관련된 명령에 필요한 프로그램이 시스템에 설치되어 있는지 확인
   - 사용자 권한이 충분한지 확인

3. **성능 문제**:
   - 응답이 느린 경우 timeout 파라메터를 조정
   - 복잡한 작업의 경우 여러 개의 간단한 지시로 분해하는 것을 고려

4. **로그 정보**:
   - 로그 파일은 기본적으로 `~/.linuxagent.log`에 저장됩니다
   - 더 자세한 디버그 정보를 표시하려면 `-d` 파라메터를 사용하여 시작

### 연락처

- 작가 QQ: 3068504755
- QQ 그룹: 281392454

## 라이센스

MIT License