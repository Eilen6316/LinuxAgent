<div align="center">
  <h1>LinuxAgent - 基于LLM大模型的Linux运维助手</h1>
  <img src="logo.jpg" alt="LinuxAgent Logo" width="400" />

  <p>
    <a href="https://gitcode.com/qq_69174109/LinuxAgent.git"><img src="https://img.shields.io/badge/GitCode-项目仓库-blue?style=flat-square&logo=git" alt="GitCode"></a>
    <a href="https://github.com/Eilen6316/LinuxAgent.git"><img src="https://img.shields.io/badge/GitHub-项目仓库-black?style=flat-square&logo=github" alt="GitHub"></a>
    <a href="https://gitee.com/xinsai6316/LinuxAgent.git"><img src="https://img.shields.io/badge/Gitee-项目仓库-red?style=flat-square&logo=gitee" alt="Gitee"></a>
    <a href="http://qm.qq.com/cgi-bin/qm/qr?_wv=1027&k=o2ByKsl_gBN-fODJxH4Ps4Xboa_hCSI3&authKey=nVfsLJBin1CnZBd9pPNkxFk%2FGFqCe1FLsRMQmmxv%2FQnM78bC%2FjcWyMSeQcJDZC1U&noverify=0&group_code=281392454"><img src="https://img.shields.io/badge/QQ群-281392454-brightgreen?style=flat-square&logo=tencent-qq" alt="QQ Group"></a>
    <a href="https://blog.csdn.net/qq_69174109/article/details/146365413">
  <img src="https://img.shields.io/badge/CSDN-项目介绍-blue?style=flat-square&logo=csdn" alt="CSDN博客">
</a>
  </p>


  <p>
    <a href="#introduction-cn">🇨🇳 简体中文</a> | 
    <a href="#introduction-en">🇺🇸 English</a> |
  </p>
</div>


---

<a id="introduction-cn"></a>

## 📌 简体中文

LinuxAgent是一个智能运维助手。通过接入LLM大模型 API实现对Linux终端的自然语言控制，帮助用户更高效地进行系统运维工作。

### 更新日志

#### v3.0.1 (当前版本) - 智能化运维新时代

- 🧠 **全新智能化架构**：集成6大核心智能模块，实现真正的智能运维
- 🎯 **命令学习器**：学习用户命令使用模式、频率和成功率，提供个性化建议
- 🔮 **智能推荐引擎**：基于上下文、历史和知识库的多维度智能命令推荐
- 📚 **Linux知识库**：内置丰富的Linux命令文档、最佳实践和故障排除指南
- 🗣️ **自然语言增强**：支持中英文自然语言理解、转换和参数提取
- 📊 **模式分析器**：用户行为模式识别、时间模式学习和智能预测
- 🧭 **上下文管理器**：智能上下文记忆、会话管理和历史追踪
- 📈 **企业级监控**：实时系统监控、性能告警和资源使用分析
- 🔍 **智能日志分析**：异常检测、日志模式识别和故障诊断
- 🌐 **集群管理**：SSH集群管理、批量操作和分布式任务执行

#### v2.0.5

- 🔧 优化：移除了Windows特有的代码，提高在Linux系统下的兼容性
- 🚀 改进：简化流式输出逻辑，消除滚动功能带来的终端状态问题
- ✨ 增强：修复了AI回答完成后无法继续输入的bug
- 🛠️ 重构：优化代码结构，删除无用的平台检测逻辑

#### v2.0.4

- 🚀 增加了流式输出功能，使AI回答更流畅
- 🎨 新增自定义主题功能，支持多种界面风格切换
- 📚 添加了交互式教程，帮助新用户快速上手

#### v2.0.3

- 🔧 添加自动模式与手动模式切换功能
- 💬 增强了自然语言理解能力
- 🛡️ 增强安全检查机制

### 版本特性演进对比

| 功能特性 | v1.4.1 | v2.0.3 | v2.0.4 | v2.0.5 | **v3.0.1 (当前)** |
|---------|---------|---------|---------|---------|------------------|
| 自然语言理解 | ✓ | ✓ | ✓ | ✓ | **✓ (大幅增强)** |
| 智能命令执行 | ✗ | ✓ | ✓ | ✓ | **✓ (智能推荐)** |
| 安全控制机制 | ✓ | ✓ | ✓ | ✓ | **✓ (多层防护)** |
| 多轮对话支持 | ✗ | ✓ | ✓+ | ✓+ | **✓+ (上下文记忆)** |
| 自动/手动模式 | ✗ | ✓ | ✓ | ✓ | **✓ (智能切换)** |
| 流式输出 | ✗ | ✗ | ✓ | ✓ | **✓ (优化体验)** |
| 自定义主题 | ✗ | ✗ | ✓ | ✓ | **✓ (扩展主题)** |
| 交互式教程 | ✗ | ✗ | ✓ | ✓ | **✓ (智能引导)** |
| Linux专属优化 | ✗ | ✗ | ✗ | ✓ | **✓ (深度优化)** |
| **命令学习器** | ✗ | ✗ | ✗ | ✗ | **✓ (全新)** |
| **智能推荐引擎** | ✗ | ✗ | ✗ | ✗ | **✓ (全新)** |
| **Linux知识库** | ✗ | ✗ | ✗ | ✗ | **✓ (全新)** |
| **自然语言增强** | ✗ | ✗ | ✗ | ✗ | **✓ (全新)** |
| **模式分析器** | ✗ | ✗ | ✗ | ✗ | **✓ (全新)** |
| **上下文管理** | ✗ | ✗ | ✗ | ✗ | **✓ (全新)** |
| **系统监控** | ✗ | ✗ | ✗ | ✗ | **✓ (全新)** |
| **日志分析** | ✗ | ✗ | ✗ | ✗ | **✓ (全新)** |
| **集群管理** | ✗ | ✗ | ✗ | ✗ | **✓ (全新)** |

### 🌟 v3.0.1 突出亮点

#### 💡 **智能化程度质的飞跃**
- **从被动执行到主动推荐**：不再只是执行命令，而是能够主动学习和推荐
- **从单次交互到上下文记忆**：具备长期记忆和上下文理解能力  
- **从命令翻译到智能助手**：从简单的自然语言转命令工具演进为智能运维助手

#### 🔬 **技术架构的重大升级** 
- **模块化设计**：六大智能化核心模块，各司其职，松耦合设计
- **可配置性**：丰富的配置选项，适应不同使用场景
- **扩展性**：插件化架构，支持功能扩展和定制

#### 📈 **运维效率的显著提升**
- **学习能力**：随使用时间增长，系统越来越智能
- **推荐精度**：基于多维度分析的高精度命令推荐  
- **知识积累**：内置和用户扩展的Linux知识库

#### 📊 **性能提升数据对比**

| 指标 | v2.0.5 | v3.0.1 | 提升幅度 |
|------|---------|---------|----------|
| 核心模块数 | 3个 | 12个 | **300%** |
| 智能化功能 | 0个 | 6个 | **全新突破** |
| 配置选项 | 15项 | 50+项 | **233%** |
| 功能完整度 | 基础版 | 企业级 | **质的飞跃** |

### 功能特点

- 自然语言理解：通过LLM API理解用户的自然语言指令
- 智能命令执行：将用户意图转换为Linux命令并安全执行
- 结果反馈：清晰展示命令执行结果
- 安全控制：内置安全检查机制，防止危险操作
- 历史记录：保存交互历史，方便复用和追踪

### 系统要求

- Rocky Linux 9.4 或其他兼容系统
- Python 3.8+
- 网络连接（用于访问LLM API）
- LLM API密钥

#### 推荐配置 (v3.0.1)
- **内存**: 512MB+ (智能化功能需要额外内存)
- **磁盘空间**: 100MB+ (用于智能学习数据和知识库存储)
- **Python包**: 自动安装智能化依赖包 (numpy, scikit-learn, jieba等)

> **重要提示**: v3.0.1版本引入了全新的智能化功能架构，包括命令学习、模式分析、智能推荐等企业级功能。首次启动会进行智能化模块初始化，可能需要几分钟时间下载和配置相关依赖。建议在稳定的网络环境下进行首次启动。

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

3. 配置LLM API密钥

```bash
cp config.yaml.example config.yaml
# 编辑config.yaml，填入LLM API密钥
```

### 详细使用指南

#### 获取LLM API密钥

1. 访问LLM官方网站（https://deepseek.com）注册账号
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
  api_key: "your_LLM_api_key"  # 将此处替换为真实API密钥
```

3. 其他配置项说明：
   - `base_url`: LLM API的基础URL，默认不需要修改
   - `model`: 使用的模型名称，默认使用"LLM-chat"
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
   - 系统会调用LLM API分析您的指令并生成对应的Linux命令
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
     在不修改配置文件的情况下，直接在程序内设置LLM API密钥。

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

LinuxAgent is an intelligent operations assistant that enables natural language control of the Linux terminal through the LLM API, helping users perform system operations more efficiently.

### Update Log

#### v3.0.1 (Current) - Era of Intelligent Operations

- 🧠 **Revolutionary Intelligence Architecture**: Integrated 6 core intelligent modules for true intelligent operations
- 🎯 **Command Learner**: Learn user command patterns, frequency, and success rates for personalized suggestions
- 🔮 **Smart Recommendation Engine**: Multi-dimensional intelligent command recommendations based on context, history, and knowledge base
- 📚 **Linux Knowledge Base**: Built-in comprehensive Linux command documentation, best practices, and troubleshooting guides
- 🗣️ **Natural Language Enhancement**: Support for Chinese-English natural language understanding, conversion, and parameter extraction
- 📊 **Pattern Analyzer**: User behavior pattern recognition, time pattern learning, and intelligent prediction
- 🧭 **Context Manager**: Intelligent context memory, session management, and history tracking
- 📈 **Enterprise Monitoring**: Real-time system monitoring, performance alerts, and resource usage analysis
- 🔍 **Intelligent Log Analysis**: Anomaly detection, log pattern recognition, and fault diagnosis
- 🌐 **Cluster Management**: SSH cluster management, batch operations, and distributed task execution

#### v2.0.5

- 🔧 Optimized: Removed Windows-specific code to improve compatibility on Linux systems
- 🚀 Improved: Simplified stream output logic, eliminating terminal state issues caused by scrolling
- ✨ Enhanced: Fixed the bug where input was blocked after AI response completion
- 🛠️ Refactored: Optimized code structure, removed unnecessary platform detection logic

#### v2.0.4

- 🚀 Added streaming output functionality for smoother AI responses
- 🎨 Added custom theme feature with multiple interface styles
- 📚 Added interactive tutorial to help new users get started

#### v2.0.3

- 🔧 Added automatic and manual mode switching
- 💬 Enhanced natural language understanding capabilities
- 🛡️ Strengthened security check mechanisms

### Feature Evolution Comparison

| Feature | v1.4.1 | v2.0.3 | v2.0.4 | v2.0.5 | **v3.0.1 (Current)** |
|---------|--------|--------|--------|--------|---------------------|
| Natural Language Understanding | ✓ | ✓ | ✓ | ✓ | **✓ (Greatly Enhanced)** |
| Intelligent Command Execution | ✗ | ✓ | ✓ | ✓ | **✓ (Smart Recommendations)** |
| Security Control Mechanism | ✓ | ✓ | ✓ | ✓ | **✓ (Multi-layer Protection)** |
| Multi-turn Conversation | ✗ | ✓ | ✓+ | ✓+ | **✓+ (Context Memory)** |
| Auto/Manual Mode | ✗ | ✓ | ✓ | ✓ | **✓ (Smart Switching)** |
| Streaming Output | ✗ | ✗ | ✓ | ✓ | **✓ (Optimized Experience)** |
| Custom Themes | ✗ | ✗ | ✓ | ✓ | **✓ (Extended Themes)** |
| Interactive Tutorial | ✗ | ✗ | ✓ | ✓ | **✓ (Smart Guidance)** |
| Linux-specific Optimization | ✗ | ✗ | ✗ | ✓ | **✓ (Deep Optimization)** |
| **Command Learner** | ✗ | ✗ | ✗ | ✗ | **✓ (Brand New)** |
| **Smart Recommendation Engine** | ✗ | ✗ | ✗ | ✗ | **✓ (Brand New)** |
| **Linux Knowledge Base** | ✗ | ✗ | ✗ | ✗ | **✓ (Brand New)** |
| **Natural Language Enhancement** | ✗ | ✗ | ✗ | ✗ | **✓ (Brand New)** |
| **Pattern Analyzer** | ✗ | ✗ | ✗ | ✗ | **✓ (Brand New)** |
| **Context Management** | ✗ | ✗ | ✗ | ✗ | **✓ (Brand New)** |
| **System Monitoring** | ✗ | ✗ | ✗ | ✗ | **✓ (Brand New)** |
| **Log Analysis** | ✗ | ✗ | ✗ | ✗ | **✓ (Brand New)** |
| **Cluster Management** | ✗ | ✗ | ✗ | ✗ | **✓ (Brand New)** |

### 🌟 v3.0.1 Key Highlights

#### 💡 **Quantum Leap in Intelligence**
- **From Passive Execution to Proactive Recommendations**: No longer just executing commands, but actively learning and recommending
- **From Single Interaction to Context Memory**: Long-term memory and contextual understanding capabilities
- **From Command Translation to Intelligent Assistant**: Evolution from simple natural language-to-command tool to intelligent operations assistant

#### 🔬 **Major Technology Architecture Upgrade**
- **Modular Design**: Six core intelligent modules with distinct responsibilities and loose coupling
- **Configurability**: Rich configuration options adaptable to different usage scenarios
- **Extensibility**: Plugin architecture supporting feature extension and customization

#### 📈 **Significant Operations Efficiency Improvement**
- **Learning Capability**: System becomes increasingly intelligent with usage time
- **Recommendation Accuracy**: High-precision command recommendations based on multi-dimensional analysis
- **Knowledge Accumulation**: Built-in and user-extended Linux knowledge base

#### 📊 **Performance Improvement Data**

| Metric | v2.0.5 | v3.0.1 | Improvement |
|--------|---------|---------|-------------|
| Core Modules | 3 | 12 | **300%** |
| Intelligence Features | 0 | 6 | **Brand New** |
| Configuration Options | 15 | 50+ | **233%** |
| Feature Completeness | Basic | Enterprise | **Quantum Leap** |

### Features

- Natural Language Understanding: Understands user's natural language instructions through the LLM API
- Intelligent Command Execution: Converts user intent into Linux commands and executes them safely
- Result Feedback: Clearly displays command execution results
- Security Control: Built-in security check mechanism to prevent dangerous operations
- History Record: Saves interaction history for reuse and tracking

### System Requirements

- Rocky Linux 9.4 or other compatible systems
- Python 3.8+
- Network connection (for accessing LLM API)
- LLM API key

#### Recommended Configuration (v3.0.1)
- **Memory**: 512MB+ (Intelligence features require additional memory)
- **Disk Space**: 100MB+ (for intelligent learning data and knowledge base storage)
- **Python Packages**: Auto-install intelligence dependencies (numpy, scikit-learn, jieba, etc.)

> **Important Note**: v3.0.1 introduces a revolutionary intelligent functionality architecture, including command learning, pattern analysis, smart recommendations, and other enterprise-grade features. First startup will initialize intelligence modules, which may take several minutes to download and configure related dependencies. It is recommended to perform the first startup in a stable network environment.

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

3. Configure LLM API key

```bash
cp config.yaml.example config.yaml
# Edit config.yaml and fill in your LLM API key
```

### Detailed Usage Guide

#### Obtaining a LLM API Key

1. Visit the LLM official website (https://deepseek.com) to register an account
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
  api_key: "your_LLM_api_key"  # Replace with your actual API key
```

3. Other configuration items:
   - `base_url`: Base URL of the LLM API, usually doesn't need modification
   - `model`: Model name to use, defaults to "LLM-chat"
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
   - The system will call the LLM API to analyze your instructions and generate corresponding Linux commands
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
     Configure LLM API key directly within the program without modifying the configuration file.

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

LinuxAgent supports direct use of interactive commands or natural language descriptions:

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
