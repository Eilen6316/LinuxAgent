"""Render-model data for wizard UIs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .controller import CHAT_ABOUT_THIS_ROW, TYPE_SOMETHING_ROW, WizardController


@dataclass(frozen=True)
class WizardTabItem:
    label: str
    state: Literal["pending", "current", "confirmed", "submit"]
    current: bool
    enabled: bool

    @property
    def marker(self) -> str:
        if self.state == "confirmed":
            return "✓"
        if self.state == "current":
            return "■"
        return "□"

    @property
    def display(self) -> str:
        text = f"{self.marker} {self.label}"
        return f"[{text}]" if self.current else text


@dataclass(frozen=True)
class WizardOptionRow:
    id: str
    label: str
    description: str
    focused: bool
    selected: bool
    kind: Literal["option", "type_something", "chat_about_this"]
    multi: bool


@dataclass(frozen=True)
class WizardRenderModel:
    user_intent: str
    tabs: tuple[WizardTabItem, ...]
    current_title: str
    option_rows: tuple[WizardOptionRow, ...]
    footer_text: str
    editing_text: bool
    text_buffer: str
    can_submit: bool


FOOTER_TEXT = "Enter to select · Tab/Arrow keys to navigate · Esc to cancel"


def build_render_model(controller: WizardController) -> WizardRenderModel:
    return WizardRenderModel(
        user_intent=controller.plan.user_intent,
        tabs=_tabs(controller),
        current_title=_current_title(controller),
        option_rows=_option_rows(controller),
        footer_text=FOOTER_TEXT,
        editing_text=controller.editing_text,
        text_buffer=controller.text_buffer,
        can_submit=controller.can_submit,
    )


def _tabs(controller: WizardController) -> tuple[WizardTabItem, ...]:
    tabs: list[WizardTabItem] = []
    for index, step in enumerate(controller.plan.steps):
        confirmed = controller.is_step_confirmed(step.id)
        current = index == controller.current_step_index
        state: Literal["pending", "current", "confirmed", "submit"]
        if current and not confirmed:
            state = "current"
        elif confirmed:
            state = "confirmed"
        else:
            state = "pending"
        tabs.append(WizardTabItem(step.title, state, current, True))
    tabs.append(
        WizardTabItem(
            "Submit",
            "submit",
            controller.is_submit_tab,
            controller.can_submit,
        )
    )
    return tuple(tabs)


def _current_title(controller: WizardController) -> str:
    if controller.is_submit_tab:
        return "Submit"
    title = controller.current_step.title
    return f"[{title}]" if not controller.is_step_confirmed(controller.current_step.id) else title


def _option_rows(controller: WizardController) -> tuple[WizardOptionRow, ...]:
    if controller.is_submit_tab:
        return ()
    step = controller.current_step
    selected = set(controller.selected_ids_for_current_step())
    rows = [
        WizardOptionRow(
            id=option.id,
            label=option.label,
            description=option.description,
            focused=index == controller.option_focus_index,
            selected=option.id in selected,
            kind="option",
            multi=step.kind == "multi",
        )
        for index, option in enumerate(step.options)
    ]
    rows.append(
        WizardOptionRow(
            id=TYPE_SOMETHING_ROW,
            label="Type something",
            description="输入自定义答案",
            focused=len(step.options) == controller.option_focus_index,
            selected=controller.text_for_current_step() is not None,
            kind="type_something",
            multi=False,
        )
    )
    rows.append(
        WizardOptionRow(
            id=CHAT_ABOUT_THIS_ROW,
            label="Chat about this",
            description="转入普通对话补全",
            focused=len(step.options) + 1 == controller.option_focus_index,
            selected=False,
            kind="chat_about_this",
            multi=False,
        )
    )
    return tuple(rows)
