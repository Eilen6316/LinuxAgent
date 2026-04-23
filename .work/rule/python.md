# python.md · Python 语言特定约定

> 补充 `baseline.md`，仅覆盖 Python 特有的细节。

---

## 类型标注

- 所有公共函数签名**必须**有完整类型标注（参数 + 返回值）
- 使用 `from __future__ import annotations` 延迟求值
- 复杂类型别名用 `type` 语句（Python 3.12+）或 `TypeAlias`

```python
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator
```

## 异步

- I/O 密集型操作（LLM API 调用、SSH）使用 `asyncio`
- 同步包装器用 `asyncio.run()`，不得在异步函数内调用
- 线程只用于 CPU 密集型或阻塞式第三方库（`paramiko`）

## Pydantic 模型

```python
from pydantic import BaseModel, ConfigDict, Field, SecretStr

class APIConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    api_key: SecretStr                                    # 从 config.yaml 加载
    base_url: str = "https://api.openai.com/v1"
    timeout: float = Field(default=30.0, gt=0, le=300)

    def use_key(self) -> str:
        return self.api_key.get_secret_value()            # 显式取值，不在 __repr__ 暴露
```

- Config 模型一律 `frozen=True`（不可变）
- 密钥字段一律 `SecretStr`
- 使用 `Field(...)` 标注约束，不写内联注释
- **不得**用 `os.environ` 读取配置值（仅允许读取配置路径，见 R-SEC-04）

## 日志

```python
import logging
logger = logging.getLogger(__name__)
```

- 每个模块顶部声明 `logger`，名称为 `__name__`
- 禁止 `print()` 用于运行时输出（测试 `assert` 除外）
- 结构化日志用 `logger.info("msg", extra={"key": val})`，不用 f-string 拼接到 msg

## 路径

- 所有文件路径使用 `pathlib.Path`，禁止 `os.path.join`
- 用户家目录用 `Path.home()`，不用 `os.environ["HOME"]`

## 字符串格式化

- 优先 f-string；需要延迟求值时用 `%` 格式（日志内部）
- 禁止 `.format()` 用于新代码

## 数据类 vs Pydantic

| 场景 | 选择 |
|---|---|
| 配置（需验证、序列化） | Pydantic BaseModel |
| 纯数据传输对象（无验证需求） | `dataclasses.dataclass` |
| 枚举 | `enum.Enum` / `enum.StrEnum` |
