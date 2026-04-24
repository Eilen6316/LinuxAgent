"""Thin LinuxAgent coordinator over LangGraph and UI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from ..graph import initial_state
from ..interfaces import CommandSource, UserInterface
from ..services import ChatService, ClusterService, MonitoringService


@dataclass
class LinuxAgent:
    graph: CompiledStateGraph
    ui: UserInterface
    chat_service: ChatService
    monitoring_service: MonitoringService
    cluster_service: ClusterService | None = None

    async def run(self, *, thread_id: str = "default") -> None:
        await self.monitoring_service.start()
        try:
            async for user_input in self.ui.input_stream():
                await self.run_turn(user_input, thread_id=thread_id)
        finally:
            await self.monitoring_service.stop()
            if self.cluster_service is not None:
                await self.cluster_service.close()

    async def run_turn(self, user_input: str, *, thread_id: str) -> dict[str, Any]:
        config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
        state: Any = initial_state(user_input, source=CommandSource.USER)
        while True:
            result = await self.graph.ainvoke(state, config=config)
            interrupts = await self._interrupts(result, config)
            if not interrupts:
                if isinstance(result, dict) and result.get("messages"):
                    self.chat_service.add(result["messages"])
                    await self.ui.print(str(result["messages"][-1].content))
                return result if isinstance(result, dict) else {}
            payload = interrupts[0].value
            response = await self.ui.handle_interrupt(payload)
            state = Command(resume=response)

    async def _interrupts(self, result: Any, config: RunnableConfig) -> list[Any]:
        if isinstance(result, dict) and result.get("__interrupt__"):
            return list(result["__interrupt__"])
        snapshot = await self.graph.aget_state(config)
        interrupts: list[Any] = []
        for task in snapshot.tasks:
            interrupts.extend(task.interrupts)
        return interrupts
