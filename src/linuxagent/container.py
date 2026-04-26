"""Minimal dependency-injection container.

Hand-wired factories rather than a decorator-driven framework: the call graph
stays explicit, the lifecycle is obvious, and module-level mutable state is
avoided (R-ARCH-05). The container is instantiated once per process in
:mod:`linuxagent.cli` and passed downstream.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar, cast

from langchain_core.tools import BaseTool
from langchain_openai import OpenAIEmbeddings

from .app import LinuxAgent
from .audit import AuditLog
from .cluster import SSHManager
from .executors import LinuxCommandExecutor
from .graph import GraphDependencies, build_agent_graph
from .graph.agent_graph import AgentGraph
from .intelligence import (
    CommandLearner,
    ContextManager,
    EmbeddingCache,
    KnowledgeBase,
    NLPEnhancer,
    PatternAnalyzer,
    RecommendationEngine,
)
from .interfaces import LLMProvider
from .policy import PolicyEngine, runtime_policy_config
from .providers import provider_factory
from .runbooks import RunbookEngine, find_runbooks_dir, load_runbooks
from .services import ChatService, ClusterService, CommandService, MonitoringService
from .telemetry import TelemetryRecorder
from .tools import build_intelligence_tools, build_system_tools
from .ui import ConsoleUI

if TYPE_CHECKING:
    from .config.models import AppConfig
_T = TypeVar("_T")


class Container:
    """Holds configuration and lazily-built singletons."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._singletons: dict[str, object] = {}

    @property
    def config(self) -> AppConfig:
        return self._config

    def build_agent(self) -> LinuxAgent:
        return LinuxAgent(
            graph=self.graph(),
            ui=self.ui(),
            chat_service=self.chat_service(),
            context_manager=self.context_manager(),
            monitoring_service=self.monitoring_service(),
            cluster_service=self.cluster_service(),
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
            ),
        )

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
                    cluster_service=self.cluster_service(),
                    tools=tuple(self.tools()),
                    telemetry=self.telemetry(),
                    runbook_engine=self.runbook_engine(),
                )
            ),
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
            ),
        )

    def intelligence_tools(self) -> list[BaseTool]:
        def factory() -> list[BaseTool]:
            if not self._config.intelligence.enabled:
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

    def tools(self) -> list[BaseTool]:
        return self._cached(
            "tools",
            lambda: [*self.system_tools(), *self.intelligence_tools()],
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
