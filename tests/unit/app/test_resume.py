"""Resume rendering tests."""

from __future__ import annotations

from datetime import datetime

from langchain_core.messages import AIMessage, HumanMessage

from linuxagent.app.resume import resume_choice_label, resume_item, resume_list
from linuxagent.services import ChatSession


def test_resume_choice_label_is_compact_and_status_aware() -> None:
    session = _session(
        title="修改 /tmp/disk_info.sh 并添加 CPU 和 MEM 采集信息到脚本末尾",
        message_count=2,
    )
    label = resume_choice_label(resume_item(session, status="pending confirm"))

    assert label.startswith("[pending confirm] ")
    assert "修改 /tmp/disk_info.sh" in label
    assert "2 messages" in label
    assert len(label) < 90


def test_resume_list_uses_compact_labels() -> None:
    item = resume_item(_session(title="查看磁盘信息", message_count=1))

    rendered = resume_list([item])

    assert "1." in rendered
    assert "查看磁盘信息" in rendered
    assert "1 messages" in rendered


def _session(title: str, message_count: int) -> ChatSession:
    messages = [HumanMessage(content=title)]
    if message_count > 1:
        messages.append(AIMessage(content="done"))
    now = datetime.now().astimezone()
    return ChatSession(
        thread_id="thread",
        title=title,
        messages=tuple(messages),
        created_at=now,
        updated_at=now,
    )
