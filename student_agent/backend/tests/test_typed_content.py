"""Typed content survives compilation, persistence, hydration and session pinning."""
from copy import deepcopy
import json

import pytest

from backend.content import knowledge, lesson_content
from backend.content.knowledge_schema import submit_knowledge_points
from backend.infrastructure import content_store, persistence, published_knowledge
from backend.teaching import service as teaching


def points():
    return knowledge.compile_points(submit_knowledge_points.model_validate({"points": [
        {"title": "for 的结构", "type": "memory", "details": {
            "statement": "初始化、条件、更新。", "requiredElements": ["初始化", "条件", "更新"]}},
        {"title": "理解循环的执行顺序", "type": "concept", "details": {
            "explanation": "先初始化，再判断是否执行并更新。", "understandingPoints": ["初始化一次"]}},
        {"title": "设计循环累加", "type": "design", "details": {
            "capability": "编写给定范围的累加程序。", "constraints": [], "successCriteria": ["循环边界正确"]}},
    ]}))


def build():
    return lesson_content.build("course", "lesson", "rev", "typed-compiler", points(), [
        {"id": "scene:one", "content": "原课件的讲解可以与提取内容措辞不同。"}])


def session(body):
    return {"id": "typed-session", "context": {"courseId": "course", "userId": "learner",
            "publication": {"id": "pub", "version": 1}}, "lessonId": "lesson", "videoRevision": "rev",
            "phase": "video", "messages": [], "courses": [],
            "dialogue": teaching.new_dialogue(body["points"]), "preparation": "ready",
            "contentRef": lesson_content.reference(body), "lessonContent": body}


def test_typed_content_roundtrip_without_quotes_or_source_positions():
    body = json.loads(json.dumps(build(), ensure_ascii=False))
    lesson_content.validate(body)
    assert body["schemaVersion"] == 2 and body["lessonId"] == "lesson"
    assert body["validationStatus"] == "structure_checked"
    assert all(topic["sourceRefs"] == [] for topic in body["topics"])
    assert not any(gap["code"] == "topic_source_unknown" for gap in body["coverageGaps"])
    restored = lesson_content.bind(session(body))
    assert restored["lessonContent"]["points"] == points()
    assert [p["type"] for p in restored["dialogue"]["points"]] == ["memory", "concept", "design"]
    # Performance fields do not leak into the content version.
    assert "status" not in restored["lessonContent"]["points"][0]


@pytest.mark.parametrize("key", ["courseId", "lessonId", "videoRevision"])
def test_program_bound_context_cannot_be_reassigned(key):
    state = session(build())
    if key == "courseId":
        state["context"][key] = "another-course"
    else:
        state[key] = "another-value"
    with pytest.raises(ValueError, match="different lesson revision"):
        lesson_content.bind(state)


def test_structurally_bad_content_is_rejected_even_with_a_valid_fingerprint():
    body = build()
    body["points"][2]["details"]["successCriteria"] = []
    body["contentId"] = "content:" + lesson_content.digest({k: v for k, v in body.items() if k != "contentId"})
    with pytest.raises(ValueError):
        lesson_content.validate(body)


def test_learning_state_cannot_mutate_pinned_details():
    state = session(build())
    state["dialogue"]["points"][0]["details"]["statement"] = "修改教学内容"
    with pytest.raises(ValueError, match="differ from pinned content"):
        lesson_content.bind(state)


def test_legacy_versions_are_not_inferred_as_concept_or_upgraded():
    old_points = [{"id": "old", "title": "旧知识点", "content": "旧正文"}]
    body = lesson_content.build("course", "lesson", "rev", "old-compiler", old_points, [])
    lesson_content.validate(body)
    assert body["schemaVersion"] == 1 and "type" not in body["points"][0]
    bound = lesson_content.bind(session(body))
    assert bound["lessonContent"] == body


def test_optional_dynamic_consumer_accepts_typed_content_without_citations(monkeypatch):
    from backend.teaching import dynamic_teaching as dynamic
    from backend.evidence import records
    from test_dynamic_teaching import scripted, apply
    state = session(build())
    state.update(stateVersion=1, contentGeneration=0, flowVersion=dynamic.FLOW,
                 teachingPolicy=deepcopy(dynamic.POLICY))
    state = records.normalize(state)
    calls = scripted(monkeypatch)
    opened = apply(state, teaching.start_discussion(state), "typed-opening")
    records.validate(opened)
    assert opened["learningRecords"]["tasks"][0]["sourceRefs"] == []
    assert calls[0][1]["topics"][0]["details"] == points()[0]["details"]
    assert calls[1][1]["topic"]["type"] == "memory"


def test_json_storage_adapter_preserves_typed_fields(monkeypatch):
    # Exercise real store/find and hydration paths without a live database.
    saved = {}
    class Connection:
        def execute(self, sql, params):
            if sql.startswith("INSERT"):
                saved["body"] = json.loads(params[-1])
            return self
        def fetchone(self):
            return (deepcopy(saved["body"]),)
    connection = Connection()
    body = build()
    assert content_store.store(body, connection=connection) == body
    cold = session(body)
    del cold["lessonContent"]
    restored = content_store.hydrate(cold, connection=connection)
    assert restored["lessonContent"]["points"] == points()


def test_postgres_persist_restore_and_pin_v2_while_legacy_coexists(pg):
    body = build()
    content_store.store(body)
    state = session(body)
    persistence.save(state, 0)
    restored = persistence.restore(state["id"])
    assert restored["lessonContent"] == body
    assert [p["details"] for p in restored["dialogue"]["points"]] == [p["details"] for p in points()]
    old = lesson_content.build("course", "lesson", "rev", "legacy-compiler", [
        {"id": "old", "title": "旧内容", "content": "不改变已绑定的新内容"}], [])
    content_store.store(old)
    assert persistence.restore(state["id"])["contentRef"] == lesson_content.reference(body)


def register_job(pg):
    scenes = [{"id": "one", "visibleText": ["循环讲解"], "actions": []}]
    with pg() as connection:
        connection.execute("INSERT INTO student.published_lesson_knowledge "
            "(course_id,lesson_id,video_revision,classroom_id,scenes,status) "
            "VALUES ('course','lesson','rev','room',%s,'pending')", (json.dumps(scenes),))


def test_publication_worker_saves_typed_schema_and_server_bound_lesson(pg, monkeypatch):
    register_job(pg)
    monkeypatch.setattr(published_knowledge, "learning_points", lambda *args:
        knowledge.KnowledgeResult(points(), candidate_count=4, duplicate_count=1, model_calls=2, repair_attempted=True))
    assert published_knowledge.process_next()
    result = published_knowledge.read("course", "lesson", "rev")
    assert result["status"] == "ready"
    assert result["contentModel"]["schemaVersion"] == 2
    assert result["contentModel"]["lessonId"] == "lesson"
    assert result["points"] == points()
    assert result["coverage"]["modelCalls"] == 2 and result["coverage"]["duplicateCount"] == 1


def test_real_agent_repair_to_postgres_publication_and_student_binding(pg, monkeypatch):
    from test_typed_knowledge import run, submission, MEMORY, CONCEPT, DESIGN
    register_job(pg)
    client = run(monkeypatch, submission({**MEMORY, "details": {}}), submission(MEMORY, CONCEPT, DESIGN))
    assert published_knowledge.process_next()
    published = published_knowledge.read("course", "lesson", "rev")
    body = published["contentModel"]
    expected = knowledge.compile_points(submit_knowledge_points(points=[MEMORY, CONCEPT, DESIGN]),
                                        scope=("course", "lesson"))
    assert body["points"] == published["points"] == expected
    assert body["schemaVersion"] == 2 and body["lessonId"] == "lesson"
    assert len(client.seen) == published["coverage"]["modelCalls"] == 2
    state = session(body)
    persistence.save(state, 0)
    restored = persistence.restore(state["id"])
    assert [p["details"] for p in restored["dialogue"]["points"]] == [p["details"] for p in expected]


def test_failed_agent_keeps_draft_without_publishing_partial_points(pg, monkeypatch):
    register_job(pg)
    def fail(*args):
        raise knowledge.KnowledgePreparationError("format", model_calls=3, draft={"points": ["invalid"]},
            issues=[knowledge.ValidationIssue(-1, "format", "missing_field")])
    monkeypatch.setattr(published_knowledge, "learning_points", fail)
    assert published_knowledge.process_next()
    result = published_knowledge.read("course", "lesson", "rev")
    assert result["status"] == "failed" and result["points"] is None
    with pg() as connection:
        assert connection.execute("SELECT count(*) FROM student.lesson_content_versions").fetchone() == (0,)
        coverage = connection.execute("SELECT coverage FROM student.published_lesson_knowledge").fetchone()[0]
    assert coverage["extractionFailure"]["modelCalls"] == 3
    assert coverage["extractionFailure"]["draft"] == {"points": ["invalid"]}
    # The durable worker must not restart another three-call loop in the background.
    with pg() as connection:
        connection.execute("UPDATE student.published_lesson_knowledge SET next_retry_at=now()")
    assert not published_knowledge.process_next()
    assert published_knowledge.retry("course", "lesson", "rev")
    monkeypatch.setattr(published_knowledge, "learning_points", lambda *args: knowledge.KnowledgeResult(points()))
    assert published_knowledge.process_next()
    assert published_knowledge.read("course", "lesson", "rev")["status"] == "ready"


def test_failed_upgrade_retains_existing_v2_content_and_records_failure(pg, monkeypatch):
    register_job(pg)
    monkeypatch.setattr(published_knowledge, "learning_points", lambda *args:
        knowledge.KnowledgeResult(points(), candidate_count=3, model_calls=1))
    published_knowledge.process_next()
    original = published_knowledge.read("course", "lesson", "rev")["contentModel"]
    monkeypatch.setattr(published_knowledge, "EXTRACTOR_HASH", "next-version")
    assert published_knowledge.read("course", "lesson", "rev")["status"] == "pending"
    def fail(*args):
        raise knowledge.KnowledgePreparationError("format", model_calls=3, draft="failed-upgrade")
    monkeypatch.setattr(published_knowledge, "learning_points", fail)
    published_knowledge.process_next()
    assert published_knowledge.read("course", "lesson", "rev")["status"] == "failed"
    assert content_store.hydrate(session(original))["lessonContent"] == original
    with pg() as connection:
        coverage = connection.execute("SELECT coverage FROM student.published_lesson_knowledge").fetchone()[0]
    assert coverage["acceptedCount"] == original["coverage"]["acceptedCount"]
    assert coverage["extractionFailure"]["draft"] == "failed-upgrade"
