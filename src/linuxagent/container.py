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
from .app.runtime_messages import command_event_key, runtime_event_message, tool_activity_message
from .app.runtime_telemetry import record_runtime_event
from .audit import AuditLog
from .audit_sink import HttpAuditSink
from .cluster import SSHManager
from .executors import LinuxCommandExecutor
from .graph import GraphDependencies, build_agent_graph
from .graph.agent_graph import AgentGraph
from .graph.checkpoint import PersistentMemorySaver
from .i18n import Translator
from .interfaces import ExecutionResult, LLMProvider, UserInterface
from .operating_manifest import operating_manifest_context
from .policy import PolicyEngine, runtime_policy_config
from .product_context import product_capability_context
from .providers import provider_factory
from .runbooks import RunbookEngine, find_runbooks_dir, load_runbooks
from .sandbox import (
    BubblewrapSandboxRunner,
    LocalProcessSandboxRunner,
    NoopSandboxRunner,
    SandboxRunner,
)
from .sandbox.models import SandboxRunnerKind
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
from .skills import load_skill_manifests, skill_planner_guidance, skill_runbooks
from .telemetry import TelemetryRecorder
from .tools import (
    ToolCatalogReport,
    ToolRuntimeLimits,
    build_intelligence_tools,
    build_system_tools,
    build_workspace_tools,
    compact_tool_catalog_summary,
    inspect_tool_catalog,
)
from .ui import ConsoleUI, WizardAwareUserInterface
from .usage_insights import (
    CommandLearner,
    ContextManager,
    EmbeddingCache,
    KnowledgeBase,
    NLPEnhancer,
    PatternAnalyzer,
    RecommendationEngine,
)

if TYPE_CHECKING:
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
                    background_jobs=self.background_jobs(),
                    tools=tuple(self.tools()),
                    telemetry=self.telemetry(),
                    runbook_engine=self.runbook_engine(),
                    command_plan_config=self._config.command_plan,
                    file_patch_config=self._config.file_patch,
                    tool_observer=self._tool_event_observer(),
                    runtime_observer=self._runtime_event_observer(),
                    tool_runtime_limits=self.tool_runtime_limits(),
                    product_context=self.product_context(),
                    operating_manifest=self.operating_manifest(),
                    translator=self.translator(),
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
                (*load_runbooks(find_runbooks_dir()), *skill_runbooks(self.skill_manifests())),
                policy_engine=self.policy_engine(),
                telemetry=self.telemetry(),
                extra_guidance=skill_planner_guidance(self.skill_manifests()),
            ),
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
        return self._config.intelligence.tools_enabled is True

    def tools(self) -> list[BaseTool]:
        return self._cached(
            "tools",
            lambda: list(self.tool_catalog().tools),
        )

    def tool_catalog(self) -> ToolCatalogReport:
        return self._cached(
            "tool_catalog",
            lambda: inspect_tool_catalog(
                [
                    *self.system_tools(),
                    *build_workspace_tools(self._config.file_patch, self._config.sandbox.tools),
                    *self.intelligence_tools(),
                ]
            ),
        )

    def tool_runtime_limits(self) -> ToolRuntimeLimits:
        tools = self._config.sandbox.tools
        return ToolRuntimeLimits(
            max_rounds=tools.max_rounds,
            timeout_seconds=tools.timeout_seconds,
            max_output_chars=tools.max_output_chars,
            max_total_output_chars=tools.max_total_output_chars,
        )

    def product_context(self) -> str:
        catalog = self.tool_catalog()
        return product_capability_context(
            provider=self._config.api.provider.value,
            model=self._config.api.model,
            tool_names=tuple(item.name for item in catalog.items),
            tool_catalog=compact_tool_catalog_summary(catalog),
        )

    def operating_manifest(self) -> str:
        return self._cached("operating_manifest", operating_manifest_context)

    def _tool_event_observer(self) -> Callable[[dict[str, Any]], Any]:
        async def observe(event: dict[str, Any]) -> None:
            message = tool_activity_message(event, self.translator())
            if message:
                await self.ui().print_activity(message)

        return observe

    def _runtime_event_observer(self) -> Callable[[dict[str, Any]], Any]:
        async def observe(event: dict[str, Any]) -> None:
            record_runtime_event(self.telemetry(), event)
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
                    streamed = command_event_key(event) in self._streamed_outputs
                    self._streamed_outputs.discard(command_event_key(event))
                    printer = getattr(self.ui(), "print_execution_result", None)
                    if callable(printer):
                        await printer(result, include_output=not streamed)

        return observe

    def ui(self) -> UserInterface:
        return self._cached(
            "ui",
            lambda: WizardAwareUserInterface(
                ConsoleUI(
                    theme=self._config.ui.theme,
                    prompt_symbol=self._config.ui.prompt_symbol,
                    history_path=self._config.ui.history_path.with_name("prompt_history"),
                    translator=self.translator(),
                ),
                translator=self.translator(),
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
