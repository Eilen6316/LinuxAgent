"""Concurrent direct-answer subtasks."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from langchain_core.messages import AIMessage, BaseMessage

from ..interfaces import CommandSource
from ..providers.errors import ProviderError
from ..runtime_events import RuntimeWorker, WorkerStatus, worker_group_event
from .direct_answer import DirectAnswerContext, _complete_direct_answer
from .events import RuntimeEventObserver, notify_event
from .intent_router import ParallelDirectTask
from .state import AgentState, reset_planning_for_response


@dataclass(frozen=True)
class ParallelDirectResult:
    task: ParallelDirectTask
    answer: str = ""
    error: str = ""

    @property
    def succeeded(self) -> bool:
        return bool(self.answer) and not self.error


async def complete_parallel_direct_answer(
    context: DirectAnswerContext,
    *,
    runtime_observer: RuntimeEventObserver | None,
    messages: list[BaseMessage],
    user_text: str,
    current_trace_id: str,
    tasks: tuple[ParallelDirectTask, ...],
    router_answer: str,
) -> AgentState:
    await _notify_parallel_direct(runtime_observer, current_trace_id, WorkerStatus.RUNNING, tasks)
    results = await asyncio.gather(
        *(_complete_parallel_task(context, messages, current_trace_id, task) for task in tasks)
    )
    await _notify_parallel_direct_results(runtime_observer, current_trace_id, tuple(results))
    return _parallel_direct_response_update(
        current_trace_id,
        _merge_parallel_answers(user_text, tuple(results), router_answer),
    )


async def _complete_parallel_task(
    context: DirectAnswerContext,
    messages: list[BaseMessage],
    current_trace_id: str,
    task: ParallelDirectTask,
) -> ParallelDirectResult:
    try:
        answer = await _complete_direct_answer(
            context,
            messages,
            task.prompt,
            current_trace_id,
            mode="parallel_direct_answer",
        )
    except ProviderError as exc:
        return ParallelDirectResult(task, error=str(exc))
    if not answer:
        return ParallelDirectResult(task, error="empty answer")
    return ParallelDirectResult(task, answer=answer)


async def _notify_parallel_direct(
    observer: RuntimeEventObserver | None,
    trace_id: str,
    phase: WorkerStatus,
    tasks: tuple[ParallelDirectTask, ...],
) -> None:
    await notify_event(
        observer,
        worker_group_event(
            trace_id=trace_id,
            phase=phase,
            label_key="runtime.group.direct_answer_tasks",
            active=len(tasks) if phase is WorkerStatus.RUNNING else None,
            workers=(
                RuntimeWorker(
                    id=task.id,
                    name_key="runtime.agent.direct_answer_worker",
                    name_params={"index": index + 1},
                    status=phase,
                    goal=task.goal,
                    detail=task.goal,
                )
                for index, task in enumerate(tasks)
            ),
        ),
    )


async def _notify_parallel_direct_results(
    observer: RuntimeEventObserver | None,
    trace_id: str,
    results: tuple[ParallelDirectResult, ...],
) -> None:
    await notify_event(
        observer,
        worker_group_event(
            trace_id=trace_id,
            phase=WorkerStatus.FINISHED,
            label_key="runtime.group.direct_answer_tasks",
            active=0,
            workers=(
                RuntimeWorker(
                    id=result.task.id,
                    name_key="runtime.agent.direct_answer_worker",
                    name_params={"index": index + 1},
                    status=WorkerStatus.FINISHED if result.succeeded else WorkerStatus.FAILED,
                    goal=result.task.goal,
                    summary=result.answer,
                    error=result.error,
                )
                for index, result in enumerate(results)
            ),
        ),
    )


def _merge_parallel_answers(
    user_text: str,
    results: tuple[ParallelDirectResult, ...],
    router_answer: str,
) -> str:
    del user_text
    successful = tuple(result for result in results if result.succeeded)
    if not successful:
        return router_answer
    return "\n\n".join(_result_section(result) for result in successful)


def _result_section(result: ParallelDirectResult) -> str:
    return f"**{result.task.goal}**\n\n{result.answer}"


def _parallel_direct_response_update(current_trace_id: str, response: str) -> AgentState:
    return {
        "trace_id": current_trace_id,
        "messages": [AIMessage(content=response)],
        **reset_planning_for_response(source=CommandSource.USER),
        "wizard_result": None,
        "wizard_failed_reason": None,
        "wizard_attempted": False,
    }
