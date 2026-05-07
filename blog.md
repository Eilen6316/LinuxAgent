# 为什么 LLM 命令 Agent 不能用 substring 匹配做安全

> 观点：LLM 可以提出命令，但不能成为执行安全边界。命令安全应该由确定性解析、
> capability 策略、HITL、sandbox 和 audit 共同承担。

LLM 命令 Agent 最危险的地方，不是模型会不会说错话，而是系统有没有把“能不能执行命令”的决定权交给一个不可靠的边界。

很多 demo 级 Agent 会做一件看起来很合理的事：拿模型生成的命令字符串，检查里面有没有危险关键词。

比如：

```python
dangerous = ["rm -rf", "mkfs", "dd", "shutdown", "reboot"]

if any(pattern in command for pattern in dangerous):
    reject(command)
else:
    run(command)
```

这个思路很直观，也很容易写。但它不应该作为 LLM 命令执行的安全边界。

原因很简单：shell 命令不是普通字符串。你看到的是一行文本，真正执行的是被 shell 解析后的 token、参数、重定向、管道、子命令和环境。substring 匹配只是在文本表面做检查，它既不理解命令结构，也不理解操作对象，更不理解执行上下文。

## Substring 匹配会漏掉什么

先看几个常见问题。

第一，命令可以被拼接。

```bash
rm -r /tmp/a -f
```

如果规则只匹配 `"rm -rf"`，这条命令就绕过去了。但它的效果和 `rm -rf /tmp/a` 没有本质区别。

第二，危险参数不一定挨在一起。

```bash
rm -r -f /tmp/a
```

字符串规则经常假设危险模式是连续文本。但 shell 的参数顺序和组合方式很多，`-rf`、`-r -f`、`-fr` 在很多命令里都可能表达同一类行为。

第三，危险不总是来自命令名。

```bash
find /tmp/a -delete
```

这里没有 `rm`，但它仍然会删除文件。只盯着几个命令名，会漏掉大量等价的破坏性操作。

第四，同一个 token 在不同位置含义不同。

```bash
echo "please do not run rm -rf /"
```

这条命令包含 `rm -rf`，但它只是打印文本。substring 匹配可能误杀。

第五，shell 语法本身会改变执行边界。

```bash
echo ok && rm -rf /tmp/a
```

如果系统只检查第一个命令，或者把整行命令当作一个简单字符串，就很容易错过后半段真正执行的操作。

这类问题不是靠把关键词列表写长就能解决的。你可以继续加 `find -delete`、`xargs rm`、`truncate`、`dd of=`、`chmod 777`、`chown root`，但列表越长，误杀越多，遗漏也仍然存在。

问题的根源是：你试图用字符串包含关系来判断一个程序的行为。

## 正则也不是根本解法

有人会说，那不用 substring，用正则。

正则当然比裸字符串强一些，但它仍然不是一个可靠的执行安全模型。因为正则处理的是字符序列，而命令执行关心的是结构。

比如下面这些问题，正则都很难稳定解决：

- 这是命令名、参数、字符串字面量，还是文件路径的一部分？
- 这个 `-f` 是 `rm` 的参数，还是另一个命令的普通参数？
- 管道后的命令是否也被检查？
- `sudo`、`env`、`xargs`、`sh -c` 是否改变了实际执行对象？
- 重定向目标是不是敏感文件？
- 这条命令是只读诊断，还是会改变系统状态？

安全判断不能只问“这行文本里有没有某个词”。它至少应该问：

- 要执行的程序是什么？
- 参数 token 是什么？
- 是否出现 shell 元字符？
- 目标资源是什么？
- 操作会不会修改文件、进程、网络、用户、服务或磁盘？
- 这类能力是否允许？
- 是否需要人工确认？
- 这次确认是否可以复用？

这些问题都不是 substring 或正则真正擅长回答的。

## 更合理的第一步：token 级解析

比 substring 更合理的最低门槛，是先把命令按 shell 规则拆成 token。

在 Python 里，可以用 `shlex.split`：

```python
import shlex

argv = shlex.split(command)
program = argv[0]
args = argv[1:]
```

这一步不会让系统突然变得完美，但它至少把判断对象从“原始字符串”变成了“命令结构”。

有了 token，你就可以区分：

```bash
echo "rm -rf /tmp/a"
```

和：

```bash
rm -rf /tmp/a
```

前者的程序是 `echo`，后者的程序是 `rm`。这两者不应该被同一条 substring 规则处理。

token 级解析也能让策略更明确：

```python
if program == "rm" and ("-r" in args or "-rf" in args or "-fr" in args):
    reject(command)
```

这仍然只是一个简化例子。真实系统还需要处理组合短参数、长参数、路径、重定向、管道、子命令等。但方向是对的：先理解结构，再做判断。

## 但 token 级解析还不够

token 级解析是底线，不是终点。

原因是命令安全不只取决于命令文本，还取决于能力边界。一个运维 Agent 需要知道自己允许做什么，不允许做什么。

比如：

- `cat /etc/os-release` 是只读诊断。
- `systemctl status nginx` 是只读服务检查。
- `systemctl restart nginx` 会改变服务状态。
- `systemctl stop nginx` 可能造成业务中断。
- `rm -rf /var/lib/mysql` 是高危破坏性操作。

这些命令不能只按“有没有危险词”分类。它们应该进入一个 capability 模型：

| Capability | 例子 | 默认策略 |
|---|---|---|
| 读取系统信息 | `uname -a`, `cat /etc/os-release` | 低风险，可执行或确认 |
| 查看服务状态 | `systemctl status nginx` | 低到中风险 |
| 修改服务状态 | `systemctl restart nginx` | 必须确认 |
| 删除文件 | `rm -rf /tmp/a` | 必须确认或阻断 |
| 读取敏感文件 | `cat /etc/shadow` | 阻断 |
| 远程执行 | SSH / cluster fan-out | 主机校验 + 批量确认 |

然后每类能力再对应不同策略：

- 只读诊断可以进入低风险路径。
- 状态变更必须要求人工确认。
- 高危破坏性命令永不进入白名单。
- 远程执行必须有 SSH host key 验证。
- 本地执行必须经过 sandbox runner。
- 所有人工决策必须进入审计日志。

这样做的关键，是把 LLM 从“安全裁判”降级为“计划提出者”。

LLM 可以建议命令，可以解释原因，可以根据输出继续分析。但能不能执行，必须由确定性系统决定。

## HITL 不是弹窗，而是权限模型

很多 Agent 也会说自己有 Human-in-the-Loop。问题是，HITL 如果只是“执行前问一句 yes/no”，仍然不够。

真正有用的 HITL 至少要回答几个问题：

- 这次确认允许执行哪一条命令？
- 允许的是原始字符串，还是归一化后的 token 模式？
- 这个授权能不能复用？
- 复用范围是全局、当前会话，还是当前 thread？
- 高危命令能不能加入白名单？
- 用户拒绝的决策有没有被记录？

我的判断是：LLM 生成的命令，首次执行必须确认；确认权限只应该在当前对话和同一个 resume thread 内有效；破坏性命令永远不应该进入白名单。

这不是为了让产品显得保守，而是因为 LLM Agent 的风险来自连续上下文。一次看似合理的授权，如果变成全局长期授权，就会把一次人工判断扩大成长期执行能力。

## LinuxAgent 的取舍

LinuxAgent 的核心设计就是围绕这个判断展开的：

> LLM 可以提出操作计划，但执行必须经过策略、HITL、sandbox、SSH guard 和 audit。

在命令安全上，它避免把 substring 匹配当作安全边界，而是把命令拆到 token 层做策略判断。危险命令不是简单靠 `"pattern in command"` 判断，而是围绕命令、参数、操作类型和策略等级来处理。

v4.1 之后，它继续把这条边界往结构化方向推进：

- 红队 harness 覆盖常见命令 agent 绕过方式。
- Shell 结构分析识别 pipeline、subshell、command substitution 和 redirect。
- LOLBin 规则覆盖 `curl | bash`、`find -exec`、`xargs`、`awk system()`、编辑器 escape 和 interpreter inline execution。
- Policy benchmark 给出 P50/P95/P99 延迟，而不是只说“很快”。
- MCP server 只暴露 policy classify 和 audit verify，不暴露执行。

同时，LinuxAgent 还做了几件事情：

- 本地执行必须经过 sandbox runner。
- LLM tool metadata 必须带 sandbox spec。
- SSH 禁止自动信任未知主机 key。
- 命令首次执行必须进入 HITL。
- 破坏性命令永不进入白名单。
- 人工确认和拒绝都写入 `0o600` 的 JSONL 审计日志。
- 配置用 Pydantic fail-fast，不靠运行时默认值悄悄绕过验证。

这些设计有一个共同点：安全边界不依赖模型自觉。

这也是我认为很多 LLM 命令 Agent demo 到不了生产环境的原因。它们把最难的问题留给 prompt，把最危险的决定交给模型输出后的字符串匹配。demo 可以这样做，真实系统不应该这样做。

## 一个更实用的安全分层

如果要做一个能执行命令的 LLM Agent，我认为至少应该有这几层：

1. **解析层**
   把命令从字符串变成 token，拒绝不支持或无法解释的 shell 语法。

2. **策略层**
   根据命令、参数、资源和操作类型判断风险等级。

3. **能力层**
   明确 Agent 当前允许读取什么、修改什么、远程访问什么。

4. **HITL 层**
   对首次执行、状态变更、高风险操作进行人工确认，并限制授权复用范围。

5. **sandbox 层**
   用系统边界限制工具能触达的文件、网络和进程能力。

6. **审计层**
   记录模型建议、策略判断、人工决策和执行结果。

这几层没有哪一层能单独解决所有问题。它们的价值在于互相补位：模型会错，策略可能漏，人工可能误点，sandbox 也可能配置不完整。安全系统要假设每一层都可能失败，所以不能只有一层。

## 结论

LLM 命令 Agent 的安全问题，本质不是 prompt engineering 问题，而是系统工程问题。

如果一个 Agent 的执行安全主要依赖 substring 匹配，它实际上是在把 shell、权限、上下文和系统状态这些复杂问题，压扁成一个字符串包含判断。这个抽象太弱了。

更可靠的方向是：token 级解析、capability 模型、确定性策略、受限 sandbox、明确的 HITL 授权范围，以及不可关闭的审计。

LLM 适合做计划者，不适合做安全边界。

这就是 LinuxAgent 的基本立场。

如果你也在做能执行命令的 Agent，可以直接拿下面这组问题检查自己的系统：

- 模型输出的命令是否先被结构化验证？
- 安全判断是否依赖 substring 或 prompt 自觉？
- 管道、子 shell、命令替换、重定向是否被策略看见？
- `curl | bash`、`find -exec`、`awk system()` 这类 LOLBin 是否有测试？
- LLM 首次生成命令是否必须人工确认？
- 破坏性命令能不能进入长期白名单？
- 执行结果、拒绝和确认是否能被审计？

LinuxAgent 项目地址：<https://github.com/Eilen6316/LinuxAgent>
