"""Minimal dependency-injection container.

Hand-wired factories rather than a decorator-driven framework: the call graph
stays explicit, the lifecycle is obvious, and module-level mutable state is
avoided (R-ARCH-05). The container is instantiated once per process in
:mod:`linuxagent.cli` and passed downstream.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar, cast

from langchain_core.tools import BaseTool
from langchain_openai import OpenAIEmbeddings

from .app import LinuxAgent
from .audit import AuditLog
from .cluster import SSHManager
from .config.models import LLMProviderName
from .executors import LinuxCommandExecutor
from .graph import GraphDependencies, build_agent_graph
from .graph.agent_graph import AgentGraph
from .graph.checkpoint import PersistentMemorySaver
from .intelligence import (
    CommandLearner,
    ContextManager,
    EmbeddingCache,
    KnowledgeBase,
    NLPEnhancer,
    PatternAnalyzer,
    RecommendationEngine,
)
from .interfaces import ExecutionResult, LLMProvider
from .policy import PolicyEngine, runtime_policy_config
from .providers import provider_factory
from .runbooks import RunbookEngine, find_runbooks_dir, load_runbooks
from .sandbox import (
    BubblewrapSandboxRunner,
    LocalProcessSandboxRunner,
    NoopSandboxRunner,
    SandboxRunner,
)
from .sandbox.models import SandboxRunnerKind
from .services import ChatService, ClusterService, CommandService, MonitoringService
from .telemetry import TelemetryRecorder
from .tools import (
    ToolRuntimeLimits,
    build_intelligence_tools,
    build_system_tools,
    build_workspace_tools,
)
from .ui import ConsoleUI

if TYPE_CHECKING:
    from .config.models import AppConfig
_T = TypeVar("_T")


class Container:
    """Holds configuration and lazily-built singletons."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._singletons: dict[str, object] = {}
        self._streamed_outputs: set[tuple[str, str]] = set()

    @property
    def config(self) -> AppConfig:
        return self._config

    def build_agent(self) -> LinuxAgent:
        return LinuxAgent(
            graph=self.graph(),
            ui=self.ui(),
            chat_service=self.chat_service(),
            command_service=self.command_service(),
            audit=self.audit_log(),
            context_manager=self.context_manager(),
            monitoring_service=self.monitoring_service(),
            cluster_service=self.cluster_service(),
            telemetry=self.telemetry(),
            tool_names=tuple(tool.name for tool in self.tools()),
        )

    def audit_log(self) -> AuditLog:
        return self._cached("audit_log", lambda: AuditLog(self._config.audit.path))

    def chat_service(self) -> ChatService:
        return self._cached(
            "chat_service",
            lambda: ChatService(self._config.ui.history_path, self._config.ui.max_chat_history),
        )

    def cluster_service(self) -> ClusterService:
        return self._cached(
            "cluster_service",
            lambda: ClusterService(
                self._config.cluster,
                SSHManager(self._config.cluster, telemetry=self.telemetry()),
            ),
        )

    def command_service(self) -> CommandService:
        return self._cached(
            "command_service",
            lambda: CommandService(self.executor(), self.learner()),
        )

    def context_manager(self) -> ContextManager:
        return self._cached(
            "context_manager",
            lambda: ContextManager(self._config.intelligence.context_window),
        )

    def executor(self) -> LinuxCommandExecutor:
        return self._cached(
            "executor",
            lambda: LinuxCommandExecutor(
                self._config.security,
                policy_engine=self.policy_engine(),
                sandbox_config=self._config.sandbox,
                sandbox_runner=self.sandbox_runner(),
            ),
        )

    def sandbox_runner(self) -> SandboxRunner:
        return self._cached(
            "sandbox_runner",
            lambda: self._build_sandbox_runner(),
        )

    def _build_sandbox_runner(self) -> SandboxRunner:
        if self._config.sandbox.runner is SandboxRunnerKind.LOCAL:
            return LocalProcessSandboxRunner(enabled=self._config.sandbox.enabled)
        if self._config.sandbox.runner is SandboxRunnerKind.BUBBLEWRAP:
            return BubblewrapSandboxRunner(enabled=self._config.sandbox.enabled)
        return NoopSandboxRunner(enabled=self._config.sandbox.enabled)

    def policy_engine(self) -> PolicyEngine:
        return self._cached(
            "policy_engine",
            lambda: PolicyEngine(
                runtime_policy_config(
                    path=self._config.policy.path,
                    include_builtin=self._config.policy.include_builtin,
                )
            ),
        )

    def graph(self) -> AgentGraph:
        return self._cached(
            "graph",
            lambda: build_agent_graph(
                GraphDependencies(
                    provider=self.provider(),
                    command_service=self.command_service(),
                    audit=self.audit_log(),
                    checkpointer=self.checkpointer(),
                    cluster_service=self.cluster_service(),
                    tools=tuple(self.tools()),
                    telemetry=self.telemetry(),
                    runbook_engine=self.runbook_engine(),
                    command_plan_config=self._config.command_plan,
                    file_patch_config=self._config.file_patch,
                    tool_observer=self._tool_event_observer(),
                    runtime_observer=self._runtime_event_observer(),
                    tool_runtime_limits=self.tool_runtime_limits(),
                )
            ),
        )

    def checkpointer(self) -> PersistentMemorySaver:
        return self._cached(
            "checkpointer",
            lambda: PersistentMemorySaver(self._config.ui.checkpoint_path),
        )

    def learner(self) -> CommandLearner:
        def factory() -> CommandLearner:
            learner = CommandLearner(Path.home() / ".linuxagent_learner.json")
            learner.load()
            return learner

        return self._cached("learner", factory)

    def monitoring_service(self) -> MonitoringService:
        return self._cached(
            "monitoring_service",
            lambda: MonitoringService(self._config.monitoring),
        )

    def telemetry(self) -> TelemetryRecorder:
        return self._cached(
            "telemetry",
            lambda: TelemetryRecorder(
                self._config.telemetry.path,
                enabled=self._config.telemetry.enabled
                and self._config.telemetry.exporter == "local",
            ),
        )

    def provider(self) -> LLMProvider:
        return self._cached("provider", lambda: provider_factory(self._config.api))

    def recommendation_engine(self) -> RecommendationEngine:
        return self._cached(
            "recommendation_engine",
            lambda: RecommendationEngine(self.learner(), self.nlp_enhancer()),
        )

    def runbook_engine(self) -> RunbookEngine:
        return self._cached(
            "runbook_engine",
            lambda: RunbookEngine(
                load_runbooks(find_runbooks_dir()),
                policy_engine=self.policy_engine(),
                telemetry=self.telemetry(),
            ),
        )

    def knowledge_base(self) -> KnowledgeBase:
        return self._cached("knowledge_base", lambda: KnowledgeBase(self.nlp_enhancer()))

    def nlp_enhancer(self) -> NLPEnhancer:
        return self._cached(
            "nlp_enhancer",
            lambda: NLPEnhancer(
                self.embeddings(),
                EmbeddingCache(self._config.intelligence.embedding_cache_dir),
            ),
        )

    def pattern_analyzer(self) -> PatternAnalyzer:
        return self._cached("pattern_analyzer", PatternAnalyzer)

    def system_tools(self) -> list[BaseTool]:
        return self._cached(
            "system_tools",
            lambda: build_system_tools(
                self.executor(),
                allowed_log_roots=tuple(
                    {path.parent for path in self._config.log_analysis.default_log_paths}
                ),
                monitoring_config=self._config.monitoring,
                tool_config=self._config.sandbox.tools,
            ),
        )

    def intelligence_tools(self) -> list[BaseTool]:
        def factory() -> list[BaseTool]:
            if not self._intelligence_tools_enabled():
                return []
            command_candidates = [command for command, _ in self.learner().top_commands(limit=50)]
            if not command_candidates:
                command_candidates = list(self._config.intelligence.default_command_candidates)
            return build_intelligence_tools(
                recommendation_engine=self.recommendation_engine(),
                knowledge_base=self.knowledge_base(),
                pattern_analyzer=self.pattern_analyzer(),
                nlp_enhancer=self.nlp_enhancer(),
                command_candidates=command_candidates,
            )

        return self._cached("intelligence_tools", factory)

    def _intelligence_tools_enabled(self) -> bool:
        if not self._config.intelligence.enabled:
            return False
        override = self._config.intelligence.tools_enabled
        if override is not None:
            return override
        return self._config.api.provider in (
            LLMProviderName.OPENAI,
            LLMProviderName.OPENAI_COMPATIBLE,
        )

    def tools(self) -> list[BaseTool]:
        return self._cached(
            "tools",
            lambda: [
                *self.system_tools(),
                *build_workspace_tools(self._config.file_patch, self._config.sandbox.tools),
                *self.intelligence_tools(),
            ],
        )

    def tool_runtime_limits(self) -> ToolRuntimeLimits:
        tools = self._config.sandbox.tools
        return ToolRuntimeLimits(
            max_rounds=tools.max_rounds,
            timeout_seconds=tools.timeout_seconds,
            max_output_chars=tools.max_output_chars,
            max_total_output_chars=tools.max_total_output_chars,
        )

    def _tool_event_observer(self) -> Callable[[dict[str, Any]], Any]:
        async def observe(event: dict[str, Any]) -> None:
            message = _tool_event_message(event)
            if message:
                await self.ui().print_raw(f"{message}\n")

        return observe

    def _runtime_event_observer(self) -> Callable[[dict[str, Any]], Any]:
        async def observe(event: dict[str, Any]) -> None:
            self._record_runtime_event(event)
            message = _runtime_event_message(event)
            if message:
                await self.ui().print_activity(message)
                return
            stream = event.get("phase")
            if stream in {"stdout", "stderr"}:
                text = str(event.get("text") or "")
                if text:
                    self._streamed_outputs.add(_command_event_key(event))
                await self.ui().print_raw(text, stderr=stream == "stderr")
                return
            if stream == "result":
                result = event.get("result")
                if isinstance(result, ExecutionResult):
                    streamed = _command_event_key(event) in self._streamed_outputs
                    self._streamed_outputs.discard(_command_event_key(event))
                    await self.ui().print_execution_result(result, include_output=not streamed)

        return observe

    def _record_runtime_event(self, event: dict[str, Any]) -> None:
        event_type = str(event.get("type") or "")
        phase = str(event.get("phase") or "")
        if event_type not in {"activity", "command", "command_batch"} or not phase:
            return
        trace_id = str(event.get("trace_id") or "runtime")
        attributes = {
            "type": event_type,
            "phase": phase,
            "command": event.get("command"),
            "count": event.get("count"),
            "exit_code": event.get("exit_code"),
            "chars": len(str(event.get("text") or "")),
            "redacted_count": event.get("redacted_count"),
            "truncated": event.get("truncated", False),
        }
        status = "truncated" if event.get("truncated") else "ok"
        self.telemetry().event(
            f"runtime.{event_type}.{phase}",
            trace_id=trace_id,
            status=status,
            attributes=attributes,
        )

    def ui(self) -> ConsoleUI:
        return self._cached(
            "ui",
            lambda: ConsoleUI(
                theme=self._config.ui.theme,
                prompt_symbol=self._config.ui.prompt_symbol,
                history_path=self._config.ui.history_path.with_name("prompt_history"),
            ),
        )

    def embeddings(self) -> OpenAIEmbeddings:
        return self._cached(
            "embeddings",
            lambda: OpenAIEmbeddings(
                model=self._config.intelligence.embedding_model,
                api_key=self._config.api.api_key,
                base_url=self._config.api.base_url,
            ),
        )

    def _cached(self, key: str, factory: Callable[[], _T]) -> _T:
        value = self._singletons.get(key)
        if value is None:
            value = factory()
            self._singletons[key] = value
        return cast(_T, value)


def _tool_event_message(event: dict[str, Any]) -> str | None:
    phase = str(event.get("phase") or "")
    tool_name = str(event.get("tool_name") or "")
    raw_args = event.get("args")
    args: dict[str, Any] = raw_args if isinstance(raw_args, dict) else {}
    if phase == "start":
        return _tool_start_message(tool_name, args)
    if phase == "error":
        return (
            f"LinuxAgent 工具调用失败："
            f"{tool_name}: {event.get('output_preview') or 'unknown error'}"
        )
    return None


def _command_event_key(event: dict[str, Any]) -> tuple[str, str]:
    return (str(event.get("trace_id") or ""), str(event.get("command") or ""))


def _runtime_event_message(event: dict[str, Any]) -> str | None:
    event_type = str(event.get("type") or "")
    phase = str(event.get("phase") or "")
    if event_type == "command":
        return _command_event_message(phase, event)
    if event_type == "command_batch":
        return _command_batch_event_message(phase, event)
    if event_type == "activity":
        return _activity_event_message(phase)
    return None


def _command_event_message(phase: str, event: dict[str, Any]) -> str | None:
    command = str(event.get("command") or "")
    if phase == "start":
        return f"LinuxAgent 正在执行命令：{command}"
    if phase == "finish":
        return f"LinuxAgent 命令结束：exit {event.get('exit_code')}"
    return None


def _command_batch_event_message(phase: str, event: dict[str, Any]) -> str | None:
    count = int(event.get("count") or 0)
    if phase == "start":
        return f"LinuxAgent 正在并发执行 {count} 条只读命令"
    if phase == "finish":
        return f"LinuxAgent 并发只读命令已完成：{count} 条"
    return None


def _activity_event_message(phase: str) -> str | None:
    labels = {
        "classify": "LinuxAgent 正在分类意图",
        "plan": "LinuxAgent 正在规划命令",
        "policy": "LinuxAgent 正在评估安全策略",
        "waiting_confirm": "LinuxAgent 正在等待确认",
        "repair_plan": "LinuxAgent 正在生成修复方案",
        "analyze": "LinuxAgent 正在分析执行结果",
    }
    return labels.get(phase)


def _tool_start_message(tool_name: str, args: dict[str, Any]) -> str:
    if tool_name == "read_file":
        return f"LinuxAgent 正在读取文件 {args.get('path') or ''}".strip()
    if tool_name == "list_dir":
        return f"LinuxAgent 正在列目录 {args.get('path') or '.'}"
    if tool_name == "search_files":
        root = args.get("root") or "."
        pattern = args.get("pattern") or ""
        return f"LinuxAgent 正在搜索 {root}: {pattern}"
    if tool_name == "repair_file_patch":
        files = args.get("files") if isinstance(args.get("files"), list) else []
        suffix = f" {', '.join(str(item) for item in files)}" if files else ""
        return f"LinuxAgent 正在重新读取文件并修复 diff{suffix}"
    return f"LinuxAgent 正在调用工具 {tool_name}"
