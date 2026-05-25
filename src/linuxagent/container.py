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

from .active_view import ActiveTurnView, apply_event
from .app import LinuxAgent
from .app.runtime_messages import command_event_key, runtime_event_message, tool_activity_message
from .app.runtime_telemetry import record_runtime_event
from .audit import AuditLog
from .audit_sink import HttpAuditSink
from .cluster import SSHManager
from .event_replay import RuntimeEventStore
from .executors import LinuxCommandExecutor
from .graph import GraphRuntime
from .graph.agent_graph import AgentGraph
from .graph.checkpoint import PersistentMemorySaver
from .i18n import Translator
from .interfaces import ExecutionResult, LLMProvider, UserInterface
from .operating_manifest import operating_manifest_context
from .policy import PolicyEngine, runtime_policy_config
from .sandbox import SandboxRunner
from .services import (
    BackgroundJobController,
    BackgroundJobService,
    ChatService,
    ClusterService,
    CommandService,
    JobDaemonClient,
    JobDaemonServer,
    JobDaemonUnit,
    MonitoringService,
    build_job_daemon_unit,
    daemon_socket_path,
    daemon_store_path,
)
from .skills import load_skill_manifests
from .telemetry import TelemetryRecorder
from .tools import ToolCatalogReport, ToolRuntimeLimits, build_network_tools
from .turn_history import TurnHistorySummary, consolidate_turn_history
from .usage_insights import (
    CommandLearner,
    ContextManager,
    EmbeddingCache,
    KnowledgeBase,
    NLPEnhancer,
    PatternAnalyzer,
    RecommendationEngine,
)
from .wiring.graph import build_graph, build_graph_runtime
from .wiring.providers import build_embeddings, build_provider
from .wiring.sandbox import build_sandbox_runner
from .wiring.tools import (
    build_intelligence_tool_list,
    build_product_context,
    build_system_tool_list,
    build_tool_catalog,
    build_tool_runtime_limits,
    intelligence_tools_enabled,
)
from .wiring.ui import build_ui

if TYPE_CHECKING:
    from langchain_openai import OpenAIEmbeddings

    from .config.models import AppConfig
    from .skills import SkillManifest
_T = TypeVar("_T")


class Container:
    """Holds configuration and lazily-built singletons."""

    def __init__(self, config: AppConfig, *, config_path: Path | None = None) -> None:
        self._config = config
        self._config_path = config_path
        self._singletons: dict[str, object] = {}
        self._streamed_outputs: set[tuple[str, str]] = set()
        self._last_activity_message = ""
        self._active_turn_view = ActiveTurnView()
        self._turn_history_summaries: list[TurnHistorySummary] = []
        self._last_turn_history_key: tuple[str, str, str] | None = None
        self._runtime_event_store = RuntimeEventStore()

    @property
    def config(self) -> AppConfig:
        return self._config

    def build_agent(self) -> LinuxAgent:
        return LinuxAgent(
            graph_runtime=self.graph_runtime(),
            ui=self.ui(),
            chat_service=self.chat_service(),
            command_service=self.command_service(),
            audit=self.audit_log(),
            context_manager=self.context_manager(),
            monitoring_service=self.monitoring_service(),
            cluster_service=self.cluster_service(),
            background_jobs=self.background_jobs(),
            job_daemon_unit=self.job_daemon_unit(),
            telemetry=self.telemetry(),
            tool_names=tuple(item.name for item in self.tool_catalog().items),
            prompt_cache_enabled=self._config.api.prompt_cache,
            translator=self.translator(),
        )

    def audit_log(self) -> AuditLog:
        return self._cached(
            "audit_log",
            lambda: AuditLog(self._config.audit.path, sink=self._audit_sink()),
        )

    def _audit_sink(self) -> HttpAuditSink | None:
        cfg = self._config.audit
        if not cfg.sink_enabled or cfg.sink_url is None:
            return None
        secret = cfg.sink_header_value.get_secret_value() if cfg.sink_header_value else None
        return HttpAuditSink(
            cfg.sink_url,
            timeout_seconds=cfg.sink_timeout_seconds,
            header_name=cfg.sink_header_name,
            header_value=secret,
        )

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

    def background_jobs(self) -> BackgroundJobController:
        return self._cached(
            "background_jobs",
            lambda: self._build_background_jobs(),
        )

    def build_job_daemon(self) -> JobDaemonServer:
        return JobDaemonServer(socket_path=self.job_daemon_socket_path(), jobs=self.local_jobs())

    def job_daemon_unit(self) -> JobDaemonUnit:
        return build_job_daemon_unit(config_path=self._config_path)

    def local_jobs(self) -> BackgroundJobService:
        return self._cached(
            "local_jobs",
            lambda: BackgroundJobService(
                self.command_service(),
                path=self.job_store_path(),
                max_history=self._config.jobs.max_history,
                retention_days=self._config.jobs.retention_days,
                event_observer=self._runtime_event_observer(),
            ),
        )

    def job_daemon_socket_path(self) -> Path:
        return daemon_socket_path(self._config.ui.history_path)

    def job_store_path(self) -> Path:
        return daemon_store_path(self._config.ui.history_path)

    def _build_background_jobs(self) -> BackgroundJobController:
        if self._config.jobs.daemon_enabled:
            return JobDaemonClient(
                socket_path=self.job_daemon_socket_path(),
                store_path=self.job_store_path(),
            )
        return self.local_jobs()

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
        return build_sandbox_runner(self._config.sandbox)

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
            lambda: build_graph(
                self._config,
                provider=self.provider(),
                command_service=self.command_service(),
                audit=self.audit_log(),
                checkpointer=self.checkpointer(),
                cluster_service=self.cluster_service(),
                background_jobs=self.background_jobs(),
                tools=tuple(self.tools()),
                telemetry=self.telemetry(),
                tool_observer=self._tool_event_observer(),
                runtime_observer=self._runtime_event_observer(),
                tool_runtime_limits=self.tool_runtime_limits(),
                product_context=self.product_context(),
                operating_manifest=self.operating_manifest(),
                translator=self.translator(),
            ),
        )

    def graph_runtime(self) -> GraphRuntime:
        return self._cached(
            "graph_runtime",
            lambda: build_graph_runtime(
                self.graph(),
                self._runtime_event_observer(),
                self._runtime_event_store.latest,
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
                enabled=self._config.telemetry.enabled,
                exporter=self._config.telemetry.exporter,
                otlp_endpoint=self._config.telemetry.otlp_endpoint,
            ),
        )

    def translator(self) -> Translator:
        return self._cached(
            "translator",
            lambda: Translator(self._config.language),
        )

    def provider(self) -> LLMProvider:
        return self._cached("provider", lambda: build_provider(self._config.api))

    def recommendation_engine(self) -> RecommendationEngine:
        return self._cached(
            "recommendation_engine",
            lambda: RecommendationEngine(self.learner(), self.nlp_enhancer()),
        )

    def skill_manifests(self) -> tuple[SkillManifest, ...]:
        def factory() -> tuple[SkillManifest, ...]:
            if not self._config.skills.enabled:
                return ()
            return load_skill_manifests(self._config.skills.manifests)

        return self._cached("skill_manifests", factory)

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
            lambda: build_system_tool_list(self._config, self.executor()),
        )

    def intelligence_tools(self) -> list[BaseTool]:
        def factory() -> list[BaseTool]:
            if not intelligence_tools_enabled(self._config):
                return []
            return build_intelligence_tool_list(
                self._config,
                learner=self.learner(),
                recommendation_engine=self.recommendation_engine(),
                knowledge_base=self.knowledge_base(),
                pattern_analyzer=self.pattern_analyzer(),
                nlp_enhancer=self.nlp_enhancer(),
            )

        return self._cached(
            "intelligence_tools",
            factory,
        )

    def network_tools(self) -> list[BaseTool]:
        return self._cached(
            "network_tools",
            lambda: build_network_tools(
                self._config.network,
                self.audit_log(),
                self._config.sandbox.tools,
            ),
        )

    def tools(self) -> list[BaseTool]:
        return self._cached(
            "tools",
            lambda: list(self.tool_catalog().tools),
        )

    def tool_catalog(self) -> ToolCatalogReport:
        return self._cached(
            "tool_catalog",
            lambda: build_tool_catalog(
                self._config,
                system_tools=self.system_tools(),
                intelligence_tools=self.intelligence_tools(),
                network_tools=self.network_tools(),
            ),
        )

    def tool_runtime_limits(self) -> ToolRuntimeLimits:
        return build_tool_runtime_limits(self._config)

    def product_context(self) -> str:
        return build_product_context(self._config, self.tool_catalog())

    def operating_manifest(self) -> str:
        return self._cached("operating_manifest", operating_manifest_context)

    def _tool_event_observer(self) -> Callable[[dict[str, Any]], Any]:
        async def observe(event: dict[str, Any]) -> None:
            self._record_tool_audit_event(event)
            message = tool_activity_message(event, self.translator())
            if message:
                await self.ui().print_activity(message)

        return observe

    def _record_tool_audit_event(self, event: dict[str, Any]) -> None:
        raw_args = event.get("args")
        args = raw_args if isinstance(raw_args, dict) else {}
        self.audit_log().record_tool_event(
            tool_name=str(event.get("tool_name") or ""),
            phase=str(event.get("phase") or ""),
            status=str(event.get("status") or ""),
            args=args,
            output_chars=int(event.get("output_chars") or 0),
            truncated=bool(event.get("truncated")),
            trace_id=str(event.get("trace_id")) if event.get("trace_id") else None,
        )

    def _runtime_event_observer(self) -> Callable[[dict[str, Any]], Any]:
        async def observe(event: dict[str, Any]) -> None:
            record_runtime_event(self.telemetry(), event)
            self._runtime_event_store.record(event)
            self._request_pending_input_at_safe_point(event)
            if await self._render_active_runtime_event(event):
                return
            message = runtime_event_message(event, self.translator())
            if message:
                if message != self._last_activity_message:
                    self._last_activity_message = message
                    await self.ui().print_activity(message)
                return
            self._last_activity_message = ""
            stream = event.get("phase")
            if stream in {"stdout", "stderr"}:
                text = str(event.get("text") or "")
                if text:
                    self._streamed_outputs.add(command_event_key(event))
                await self.ui().print_raw(text, stderr=stream == "stderr")
                return
            if stream == "result":
                result = event.get("result")
                if isinstance(result, ExecutionResult):
                    self._streamed_outputs.discard(command_event_key(event))
                    printer = getattr(self.ui(), "print_execution_result", None)
                    if callable(printer):
                        await printer(result, include_output=False)

        return observe

    def _request_pending_input_at_safe_point(self, event: dict[str, Any]) -> None:
        del event

    async def _render_active_runtime_event(self, event: dict[str, Any]) -> bool:
        if not _active_runtime_event(event):
            return False
        self._last_activity_message = ""
        self._active_turn_view = apply_event(self._active_turn_view, event)
        renderer = getattr(self.ui(), "print_active_view", None)
        if callable(renderer):
            await renderer(self._active_turn_view)
        self._consolidate_active_turn_if_ready()
        return True

    def _consolidate_active_turn_if_ready(self) -> None:
        summary = consolidate_turn_history(self._active_turn_view)
        if summary is None:
            return
        key = (summary.thread_id, summary.turn_id, summary.status)
        if key == self._last_turn_history_key:
            return
        self._turn_history_summaries.append(summary)
        self._last_turn_history_key = key
        if summary.status in {"completed", "failed", "cancelled"}:
            self._active_turn_view = ActiveTurnView()
            self._last_turn_history_key = None

    def ui(self) -> UserInterface:
        return self._cached(
            "ui",
            lambda: build_ui(
                self._config.ui,
                self.translator(),
                provider=self._config.api.provider,
                model=self._config.api.model,
            ),
        )

    def embeddings(self) -> OpenAIEmbeddings:
        return self._cached(
            "embeddings",
            lambda: build_embeddings(self._config.api, self._config.intelligence),
        )

    def _cached(self, key: str, factory: Callable[[], _T]) -> _T:
        value = self._singletons.get(key)
        if value is None:
            value = factory()
            self._singletons[key] = value
        return cast(_T, value)


def _active_runtime_event(event: dict[str, Any]) -> bool:
    if event.get("schema_version") != 1:
        return False
    if event.get("kind") in {"turn", "work_item", "request"}:
        return True
    return event.get("kind") == "status" and event.get("phase") == "usage"


def _pending_input_safe_point(event: dict[str, Any]) -> bool:
    if event.get("schema_version") == 1:
        return event.get("kind") == "work_item" and event.get("phase") in {
            "completed",
            "failed",
            "cancelled",
        }
    return event.get("type") in {"command", "command_batch"} and event.get("phase") in {
        "finish",
        "result",
    }
