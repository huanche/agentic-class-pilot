"""Immutable content, pinned sessions and publication worker fencing on PostgreSQL."""

from backend.infrastructure import content_store
from copy import deepcopy
import json

import pytest

from backend.content import lesson_content
from backend.infrastructure import persistence
from backend.infrastructure import published_knowledge
from backend.content.context import classroom_materials
from backend.content.knowledge import KnowledgeResult
from backend.teaching import service as teaching
from backend.session import service as learning_session

QUOTE = "平均数由全部数据的总和除以数据个数得到。"
ALTERNATIVE = "平均数受每个数据的取值影响。"


def point(quote=QUOTE):
    return {"id": "p", "title": "平均数", "content": quote, "sourceIds": ["scene:one"]}


def register(pg, *, compiler=None, status="ready", revision="rev"):
    scenes = [{"id": "one", "title": "平均数", "visibleText": [QUOTE, ALTERNATIVE], "actions": []}]
    with pg() as connection:
        connection.execute("INSERT INTO student.published_lesson_knowledge "
            "(course_id,lesson_id,video_revision,classroom_id,extractor_hash,scenes,points,coverage,status) "
            "VALUES ('course','lesson',%s,'room',%s,%s,%s,%s,%s)",
            (revision, compiler or published_knowledge.EXTRACTOR_HASH, json.dumps(scenes),
             json.dumps([point()]) if status == "ready" else None, json.dumps({"acceptedCount": 1}), status))
    return scenes


def session(body, *, sid="learner", user="student"):
    return {"id": sid, "context": {"userId": user, "courseId": "course", "publication": {"id": "pub", "version": 1}},
            "lessonId": "lesson", "classroomId": "room", "videoRevision": "rev", "courses": [],
            "phase": "video", "messages": [], "dialogue": teaching.new_dialogue(body["points"]),
            "contentRef": lesson_content.reference(body), "lessonContent": body, "preparation": "ready"}


def test_ready_content_is_shared_with_exact_sources_and_no_new_model_call(pg, monkeypatch):
    register(pg)
    monkeypatch.setattr(published_knowledge, "learning_points", lambda *args: pytest.fail("ready content must not call model"))
    first = published_knowledge.read("course", "lesson", "rev")
    body = first["contentModel"]
    assert body["validationStatus"] == "source_checked"
    assert body["topics"][0]["sourceRefs"][0]["quote"] == QUOTE
    assert first["contentRef"] == published_knowledge.read("course", "lesson", "rev")["contentRef"]
    assert not published_knowledge.process_next()
    for user in ("a", "b"):
        persistence.save(session(body, sid=user, user=user), 0)
    with pg() as connection:
        assert connection.execute("SELECT count(*) FROM student.lesson_content_versions").fetchone() == (1,)
        assert connection.execute("SELECT count(DISTINCT content_id) FROM student.student_sessions").fetchone() == (1,)


def test_compiler_upgrade_keeps_existing_sessions_on_their_original_version(pg, monkeypatch):
    register(pg)
    original = published_knowledge.read("course", "lesson", "rev")["contentModel"]
    persistence.save(session(original), 0)
    monkeypatch.setattr(published_knowledge, "EXTRACTOR_HASH", "new-extractor")
    assert published_knowledge.read("course", "lesson", "rev")["status"] == "pending"
    monkeypatch.setattr(published_knowledge, "learning_points", lambda *args: KnowledgeResult([point(ALTERNATIVE)], candidate_count=1))
    assert published_knowledge.process_next()
    latest = published_knowledge.read("course", "lesson", "rev")["contentModel"]
    assert latest["contentId"] != original["contentId"]
    assert latest["sourceManifestHash"] == original["sourceManifestHash"]
    old_session = persistence.restore("learner")
    assert old_session["contentRef"]["contentId"] == original["contentId"]
    assert old_session["dialogue"]["points"][0]["content"] == QUOTE
    monkeypatch.setattr(published_knowledge, "read", lambda *args: pytest.fail("pinned session must not upgrade"))
    learning_session.upgrade_curriculum(old_session)
    persistence.save(session(latest, sid="new-learner"), 0)
    with pg() as connection:
        assert connection.execute("SELECT count(*) FROM student.lesson_content_versions").fetchone() == (2,)


def test_an_existing_compiler_version_cannot_be_overwritten(pg):
    scenes = register(pg)
    original = published_knowledge.read("course", "lesson", "rev")["contentModel"]
    changed = lesson_content.build("course", "lesson", "rev", original["compilerVersion"],
                                   [point(ALTERNATIVE)], classroom_materials(scenes), coverage=original["coverage"])
    with pytest.raises(ValueError):
        content_store.store(changed)
    assert content_store.hydrate(session(original))["lessonContent"] == original


@pytest.mark.parametrize("lost", ["claim", "lease"])
def test_preparation_does_not_publish_results_after_losing_ownership(pg, monkeypatch, lost):
    register(pg, status="pending")
    def extract(*args):
        with pg() as connection:
            if lost == "claim":
                connection.execute("UPDATE student.published_lesson_knowledge SET claim_token='new-worker'")
            else:
                connection.execute("UPDATE student.published_lesson_knowledge SET lease_until=now()-interval '1 second'")
        return KnowledgeResult([point()], candidate_count=1)
    monkeypatch.setattr(published_knowledge, "learning_points", extract)
    assert published_knowledge.process_next()
    with pg() as connection:
        assert connection.execute("SELECT count(*) FROM student.lesson_content_versions").fetchone() == (0,)
        assert connection.execute("SELECT status FROM student.published_lesson_knowledge").fetchone() == ("running",)


def test_failed_new_preparation_and_retry_do_not_damage_old_content(pg, monkeypatch):
    register(pg)
    original = published_knowledge.read("course", "lesson", "rev")["contentModel"]
    monkeypatch.setattr(published_knowledge, "EXTRACTOR_HASH", "retry-compiler")
    assert published_knowledge.read("course", "lesson", "rev")["status"] == "pending"
    def fail(*args):
        raise TimeoutError("isolated extraction timeout")
    monkeypatch.setattr(published_knowledge, "learning_points", fail)
    assert published_knowledge.process_next()
    assert published_knowledge.read("course", "lesson", "rev")["status"] == "failed"
    assert content_store.hydrate(session(original))["lessonContent"] == original
    assert published_knowledge.retry("course", "lesson", "rev")
    monkeypatch.setattr(published_knowledge, "learning_points", lambda *args: KnowledgeResult([point(ALTERNATIVE)], candidate_count=1))
    assert published_knowledge.process_next()
    assert published_knowledge.read("course", "lesson", "rev")["contentRef"]["contentId"] != original["contentId"]


def test_worker_result_is_tagged_with_the_compiler_that_started_it(pg, monkeypatch):
    register(pg, status="pending")
    started = published_knowledge.EXTRACTOR_HASH
    def extract(*args):
        monkeypatch.setattr(published_knowledge, "EXTRACTOR_HASH", "next-deployment")
        return KnowledgeResult([point()], candidate_count=1)
    monkeypatch.setattr(published_knowledge, "learning_points", extract)
    assert published_knowledge.process_next()
    with pg() as connection:
        compiler = connection.execute("SELECT compiler_version FROM student.lesson_content_versions").fetchone()[0]
    assert compiler.endswith(started)
    assert published_knowledge.read("course", "lesson", "rev")["status"] == "pending"


def test_visual_or_missing_sources_are_reported_as_limitations():
    scenes = [{"id": "one", "visibleText": [QUOTE], "content": {"canvas": {"elements": [{"type": "image"}]}}}]
    body = lesson_content.build("course", "lesson", "rev", "compiler", [point()], classroom_materials(scenes), scenes=scenes)
    assert {"code": "visual_content_not_interpreted"} in body["coverageGaps"]
    assert body["inputCapabilities"]["originalPpt"] is False
    legacy = lesson_content.build("course", "lesson", "rev", "unknown", [point()], [])
    assert legacy["validationStatus"] == "limited" and legacy["topics"][0]["sourceRefs"] == []
