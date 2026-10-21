"""Student bridge: launch-token and authorize semantics (no external services)."""
import time

import pytest
from fastapi.testclient import TestClient

from app.api.routes.student_bridge import issue_launch_token, verify_launch_token
from app.core.config import settings

BRIDGE_KEY = "student-bridge-test-key"


@pytest.fixture(autouse=True)
def bridge_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "STUDENT_SERVICE_KEY", BRIDGE_KEY)


def _token(exp_offset: int = 600) -> str:
    # Bypass the settings TTL for expired-token crafting via direct issue + expiry edit.
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(settings, "STUDENT_LAUNCH_TOKEN_TTL_SECONDS", exp_offset)
    try:
        return issue_launch_token("00000000-0000-0000-0000-000000000001",
                                  "00000000-0000-0000-0000-000000000002",
                                  "cls-1", {"publicationId": "pkg-1", "version": 3})
    finally:
        monkeypatch.undo()


def test_launch_token_roundtrip() -> None:
    payload = verify_launch_token(_token())
    assert payload["uid"] == "00000000-0000-0000-0000-000000000001"
    assert payload["cid"] == "00000000-0000-0000-0000-000000000002"
    assert payload["rid"] == "cls-1"
    assert payload["pub"] == {"publicationId": "pkg-1", "version": 3}


def test_launch_token_tamper_rejected() -> None:
    token = _token()
    with pytest.raises(Exception):
        verify_launch_token(token[:-2] + "zz")
    with pytest.raises(Exception):
        verify_launch_token("garbage")
    with pytest.raises(Exception):
        verify_launch_token("eyJ1aWQiOiJ4In0.deadbeef")


def test_launch_token_expiry_rejected() -> None:
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(settings, "STUDENT_LAUNCH_TOKEN_TTL_SECONDS", -10)
    try:
        expired = issue_launch_token("00000000-0000-0000-0000-000000000001",
                                     "00000000-0000-0000-0000-000000000002",
                                     "cls-1", {"publicationId": "pkg-1", "version": 1})
    finally:
        monkeypatch.undo()
    with pytest.raises(Exception):
        verify_launch_token(expired)


def test_authorize_rejects_wrong_service_key(client: TestClient) -> None:
    response = client.post("/api/v1/internal/student/authorize",
                           json={"cookie": None, "launch_token": None})
    assert response.status_code == 403


def test_authorize_rejects_launch_token_without_enrollment(client: TestClient) -> None:
    token = issue_launch_token("00000000-0000-0000-0000-000000000001",
                               "00000000-0000-0000-0000-000000000002",
                               "cls-1", {"publicationId": "pkg-1", "version": 3})
    response = client.post("/api/v1/internal/student/authorize",
                           headers={"X-Student-Service-Key": BRIDGE_KEY},
                           json={"launch_token": token})
    # valid signature, but the enrollment re-check finds no matching row -> denied
    assert response.status_code == 403


KNOWLEDGE_ARTIFACT_MD = """# 第2周知识点

依据教师材料，第2周知识点覆盖第2章“交换技术基础”（材料16su page:1-30）。
本段引言不是知识点，应被忽略。

## 一、语音通信与数据通信的差异及交换方式选择
- 语音通信是人与人的通信，数据通信需要严格协议（16su page:4）。
- 电话通信平均持续约5分钟，数据通信波动大（16su page:4）。

## 二、交换与交换机的定义及分类
- 交换是按通信两端传输信息需要完成信息传送的技术统称（16su page:6）。
- 交换机分为语音交换机和数据网络交换机（16su page:6）。
- 电话交换采用电路交换（16su page:7）。

## 二、交换与交换机的定义及分类
- 同名分节应被去重，只保留第一份。

## 三、无列表的知识点
"""


def test_knowledge_points_from_markdown_parses_sections() -> None:
    """知识点工件解析（纯函数）：## 大标题=知识点、列表=应会要点、剥中文序号、去重。"""
    from app.api.routes.student_bridge import _knowledge_points_from_markdown

    out = _knowledge_points_from_markdown(KNOWLEDGE_ARTIFACT_MD)
    assert [item["title"] for item in out] == [
        "语音通信与数据通信的差异及交换方式选择",
        "交换与交换机的定义及分类",
        "无列表的知识点",
    ]
    # 引言（首个 ## 之前）不产生知识点
    # 中文序号已剥；要点保留原文（含出处标注，供出题上下文用）
    assert out[0]["expectedConcepts"] == [
        "语音通信是人与人的通信，数据通信需要严格协议（16su page:4）。",
        "电话通信平均持续约5分钟，数据通信波动大（16su page:4）。",
    ]
    assert out[1]["expectedConcepts"] == [
        "交换是按通信两端传输信息需要完成信息传送的技术统称（16su page:6）。",
        "交换机分为语音交换机和数据网络交换机（16su page:6）。",
        "电话交换采用电路交换（16su page:7）。",
    ]
    assert out[2]["expectedConcepts"] == []                      # 无列表的知识点照常保留
    # id 来自标题哈希：同标题稳定、不同标题不同
    assert out[0]["id"] == _knowledge_points_from_markdown(
        KNOWLEDGE_ARTIFACT_MD)[0]["id"]
    assert out[0]["id"] != out[1]["id"]
    # 健壮性：空/非 markdown 输入不炸、返回空
    assert _knowledge_points_from_markdown("") == []
    assert _knowledge_points_from_markdown("没有二级标题的普通文本") == []


def test_knowledge_artifact_rubric_picks_by_lesson() -> None:
    """工件选份（纯函数）：课时归属优先、唯一一份可无归属、没有 → None。"""
    from app.api.routes.student_bridge import _knowledge_artifact_rubric

    entries = [
        {"id": "a1", "title": "讲稿", "resourceType": "courseware",
         "scope": {"type": "lesson", "lessonId": "L1"}, "content": "## 忽我"},
        {"id": "k1", "title": "第1周知识点", "resourceType": "knowledge-points",
         "scope": {"type": "lesson", "lessonId": "L1"},
         "content": "## 一、周一的要点\n- 要点甲（page:1）。"},
        {"id": "k2", "title": "第2周知识点", "resourceType": "knowledge-points",
         "scope": {"type": "lesson", "lessonId": "L2"},
         "content": "## 二、周二的要点\n- 要点乙（page:2）。"},
    ]
    rubric = _knowledge_artifact_rubric(entries, "L2")
    assert rubric is not None
    assert [p["title"] for p in rubric["knowledgePoints"]] == ["周二的要点"]
    assert rubric["knowledgePoints"][0]["expectedConcepts"] == ["要点乙（page:2）。"]

    # 唯一一份且无课时归属匹配 → 仍可用
    only = [entries[2]]
    assert _knowledge_artifact_rubric(only, "L9") is not None
    # 多份且都匹配不上 → None（宁缺毋滥，学生端明说没有）
    assert _knowledge_artifact_rubric(entries, "L9") is None
    # 没有 knowledge-points 工件 → None
    assert _knowledge_artifact_rubric([entries[0]], "L1") is None
