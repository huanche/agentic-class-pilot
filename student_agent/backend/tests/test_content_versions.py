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


@pytest.mark.parametrize("cached", [False, True])
def test_current_typed_preparation_ignores_simplified_archive(pg, monkeypatch, cached):
    compiler = "simplified-extractor"
    scenes = register(pg, compiler=compiler)
    typed = dict(point(), type="memory", details={"statement": QUOTE, "requiredElements": [QUOTE]})
    simple = {"id": "simple", "title": "平均数", "name": "平均数", "explanation": QUOTE, "content": QUOTE}
    archive = published_knowledge._compiled("course", "lesson", "rev", compiler, scenes, [simple], {})
    archive["schemaVersion"] = 3
    archive["points"] = [simple]
    archive["topics"][0].update(name=simple["name"], explanation=simple["explanation"])
    archive["contentId"] = "content:" + lesson_content.digest({key: value for key, value in archive.items() if key != "contentId"})
    with pg() as connection:
        connection.execute("UPDATE student.published_lesson_knowledge SET points=%s", (json.dumps([simple]),))
        connection.execute(
            "INSERT INTO student.lesson_content_versions "
            "(content_id,course_id,lesson_id,video_revision,compiler_version,source_manifest_hash,payload) "
            "VALUES (%s,'course','lesson','rev',%s,%s,%s)",
            (archive["contentId"], archive["compilerVersion"], archive["sourceManifestHash"], json.dumps(archive)),
        )
        if cached:
            body = published_knowledge._compiled("course", "lesson", "rev", published_knowledge.EXTRACTOR_HASH, scenes, [typed], {})
            content_store.store(body, connection=connection)
    calls = []

    def extract(*args):
        calls.append(args)
        return KnowledgeResult([typed], candidate_count=1)

    monkeypatch.setattr(published_knowledge, "learning_points", extract)
    result = published_knowledge.read("course", "lesson", "rev")
    assert result["status"] == ("ready" if cached else "pending")
    if not cached:
        assert published_knowledge.process_next()
        result = published_knowledge.read("course", "lesson", "rev")
    assert result["status"] == "ready"
    assert result["points"][0]["type"] == "memory"
    assert teaching.new_dialogue(result["points"])["flow_version"] == 4
    assert len(calls) == (0 if cached else 1)
    with pg() as connection:
        assert connection.execute("SELECT payload FROM student.lesson_content_versions WHERE content_id=%s",
                                  (archive["contentId"],)).fetchone() == (archive,)


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


def test_content_storage_failure_rolls_back_ready_and_preserves_old_pinned_version(pg, monkeypatch):
    register(pg)
    original = published_knowledge.read("course", "lesson", "rev")["contentModel"]
    monkeypatch.setattr(published_knowledge, "EXTRACTOR_HASH", "storage-failure-compiler")
    assert published_knowledge.read("course", "lesson", "rev")["status"] == "pending"
    monkeypatch.setattr(published_knowledge, "learning_points", lambda *args:
                        KnowledgeResult([point(ALTERNATIVE)], candidate_count=1))
    real_store = content_store.store

    def fail_after_insert(body, *, connection=None):
        saved = real_store(body, connection=connection)
        if body["compilerVersion"].endswith("storage-failure-compiler"):
            raise RuntimeError("injected failure after content insert")
        return saved

    monkeypatch.setattr(content_store, "store", fail_after_insert)
    assert published_knowledge.process_next()
    with pg() as connection:
        assert connection.execute("SELECT status,points FROM student.published_lesson_knowledge").fetchone() == ("failed", [point()])
        assert connection.execute("SELECT count(*) FROM student.lesson_content_versions").fetchone() == (1,)
    assert published_knowledge.read("course", "lesson", "rev")["status"] == "failed"
    assert content_store.hydrate(session(original))["lessonContent"] == original


def test_read_archives_without_retry_diagnostics_and_reschedules_old_compiler(pg, monkeypatch):
    register(pg)
    original = published_knowledge.read("course", "lesson", "rev")["contentModel"]
    with pg() as connection:
        connection.execute("DELETE FROM student.lesson_content_versions")
        connection.execute("UPDATE student.published_lesson_knowledge SET "
                           "coverage=coverage || '{\"extractionFailure\":{\"draft\":\"retry-only\"}}'::jsonb")
    monkeypatch.setattr(published_knowledge, "EXTRACTOR_HASH", "next-reader-compiler")
    result = published_knowledge.read("course", "lesson", "rev")
    assert result == {"status": "pending", "points": None, "coverage": None, "error": None}
    with pg() as connection:
        assert connection.execute("SELECT status FROM student.published_lesson_knowledge").fetchone() == ("pending",)
        assert connection.execute("SELECT payload FROM student.lesson_content_versions").fetchone() == (original,)


def test_read_prefers_current_cached_version_over_failed_job_without_rescheduling(pg):
    scenes = register(pg, compiler="old-reader-compiler")
    cached = published_knowledge._compiled("course", "lesson", "rev", published_knowledge.EXTRACTOR_HASH,
                                          scenes, [point(ALTERNATIVE)], {"acceptedCount": 1})
    content_store.store(cached)
    with pg() as connection:
        connection.execute("UPDATE student.published_lesson_knowledge SET status='failed',last_error='old-failure'")
    result = published_knowledge.read("course", "lesson", "rev")
    assert result == {"status": "ready", "points": cached["points"], "coverage": cached["coverage"],
                      "error": None, "contentRef": lesson_content.reference(cached), "contentModel": cached}
    with pg() as connection:
        assert connection.execute("SELECT status,last_error FROM student.published_lesson_knowledge").fetchone() == ("failed", "old-failure")
