"""Wizard test helpers."""

from __future__ import annotations

from linuxagent.wizard import WizardOption, WizardPlan, WizardStep


def wizard_plan() -> WizardPlan:
    return WizardPlan(
        user_intent="部署服务",
        steps=(
            WizardStep(
                id="database",
                title="选择数据库",
                kind="single",
                options=(
                    WizardOption(id="postgres", label="PostgreSQL", description="关系型数据库"),
                    WizardOption(id="mysql", label="MySQL", description="常见关系型数据库"),
                    WizardOption(id="redis", label="Redis", description="缓存数据库"),
                ),
            ),
            WizardStep(
                id="target",
                title="部署目标",
                kind="single",
                options=(
                    WizardOption(id="dev", label="Dev", description="开发环境"),
                    WizardOption(id="stage", label="Stage", description="预发环境"),
                    WizardOption(id="prod", label="Prod", description="生产环境"),
                ),
            ),
        ),
    )
