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


def test_normalize_classroom_outlines_picks_and_orders() -> None:
    """学生桥的大纲转交（纯函数）：取有效场景、按 order 排序、清洗净化。"""
    from app.api.routes.student_bridge import _normalize_classroom_outlines

    raw = [
        {"id": "b", "order": 2, "title": "三级调度", "description": "对象与时机",
         "keyPoints": ["高级调度作业入内存", " "]},
        "not-a-dict",
        {"id": "a", "order": 1, "title": "调度概念", "keyPoints": None},
        {"id": "c", "title": "  ", "keyPoints": ["x"]},          # 空标题 → 丢弃
        {"id": "d", "order": "bad", "title": "时间片轮转"},      # 非法 order → 0
    ]
    out = _normalize_classroom_outlines(raw)
    assert [item["id"] for item in out] == ["d", "a", "b"]        # 非法 order=0 排最前
    assert out[0]["order"] == 0
    assert out[1]["title"] == "调度概念"
    assert out[1]["keyPoints"] == []
    assert out[2]["keyPoints"] == ["高级调度作业入内存"]           # 空白要点被清掉
    assert _normalize_classroom_outlines(None) == []
    assert _normalize_classroom_outlines("nope") == []


def test_normalize_graph_points_cleans_and_filters() -> None:
    """图谱知识点 → rubric 转交（纯函数）：去强调符/中文间空格、去重、黑名单。"""
    from app.api.routes.student_bridge import _normalize_graph_points

    rows = [
        ("n1", "**第2章  交换技术基础**", "交换技术的基础概念"),
        ("n2", "第2章 交换技术基础", "重复节点（清洗后同题）"),      # 去重
        ("n3", "**课   程   简   介**", "封面页，不是知识点"),        # 黑名单 + 中文间空格
        ("n4", "  第11章　光交换技术  ", None),                     # 全角空格+首尾空白
        ("n5", "**", None),                                        # 清洗后为空 → 丢弃
    ]
    out = _normalize_graph_points(rows)
    assert [item["title"] for item in out] == ["第2章交换技术基础", "第11章光交换技术"]
    assert out[0]["id"] == "n1"
    assert out[0]["expectedConcepts"] == ["交换技术的基础概念"]
    assert out[1]["expectedConcepts"] == []
    assert _normalize_graph_points([]) == []
